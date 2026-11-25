import asyncio
import httpx
import json
import math
import re
import shutil
import socket
import threading
from datetime import datetime, timezone
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal
from urllib.parse import unquote

from .. import app as core
from .. import db, egress, handwork, hub, resources, sandbox, search, sources, vault
from ..tools import course_plan as plan_tools, practice as practice_tools
from ..app import Decision, SITTING_GAP, SOURCES_PER_COURSE, _areas_line, _course, _due, _lesson, _lesson_view, _map_outline, _playbook_line, _profile, _queue_claims, _turns, _untrusted, _warmed, app, log


SOURCE_LIMIT = 50 * 1024 * 1024
COURSE_SOURCE_BYTES = 200 * 1024 * 1024
_jobs: set[asyncio.Task] = set()
# placement questions for a course of an hour and for the longest; a course with no teaching time set gets the untimed count
PLACEMENT_QUESTIONS = (4, 20)
PLACEMENT_UNTIMED = 8


class NewCourse(BaseModel):
    topic: str
    profile_id: int


class SourceUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


# A fetched material: hops followed by hand so each one is checked, time per hop, and the file types accepted.
FETCH_HOPS = 5
FETCH_TIMEOUT = 30
# Whole download, all hops included.
FETCH_DEADLINE = 300
FETCH_TYPES = {
    "application/pdf": ".pdf", "application/epub+zip": ".epub", "text/html": ".html", "text/markdown": ".md",
    "text/plain": ".txt", "application/xhtml+xml": ".html",
}


class Scope(BaseModel):
    details: str = Field(default="", max_length=2000)
    hours: int | None = Field(default=None, ge=1, le=5000)


class Archive(BaseModel):
    archived: bool


class Topic(BaseModel):
    topic: str = Field(min_length=1, max_length=200)


class Choice(BaseModel):
    mechanism: str
PLACEMENT_TITLE = {"en": "What you already know", "fr": "Ce que vous savez déjà", "ar": "ما تعرفه مسبقًا"}


def _require_unplaced(course: dict) -> None:
    if course["concepts"]:
        raise HTTPException(409, "the course map already exists")
    if any(lesson["phase"] == "placement" for lesson in course["lessons"]):
        raise HTTPException(409, "the placement check already started")


def _require_learner(course: dict) -> None:
    if course["mode"] == "teacher":
        raise HTTPException(409, "a prepared course has no placement check")


@app.get("/api/courses")
def list_courses(profile: int) -> list[dict]:
    return db.rows(
        "SELECT c.id, c.topic, c.slug, c.mechanism, c.level, c.archived, c.mode, c.cover IS NOT NULL AS cover, c.cover_alt, r.finished "
        "FROM courses c LEFT JOIN recaps r ON r.course_id = c.id WHERE c.profile_id = ? ORDER BY c.id DESC",
        profile,
    )


# A copy's name is picked from the names taken before its row is written: a double click makes two copies of a course,
# one after the other.
_copying: dict[int, threading.Lock] = {}


@app.post("/api/courses/{course_id}/duplicate")
def duplicate_course(course_id: int) -> dict:
    """A prepared course again, for the next class: plan, lessons, materials and exercise files, no record."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if course["mode"] != "teacher":
        raise HTTPException(409, "only a prepared course can be duplicated")
    with _copying.setdefault(course_id, threading.Lock()):
        if any(lesson["id"] in _turns for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course_id)):
            raise HTTPException(409, "the designer is still answering in this course")
        copied = db.copy_course(course_id, _copy_name(course))
    try:
        for old, new in copied.pop("sources").items():
            for path in (core.SOURCES / str(course_id)).glob(f"{old}-*"):
                target = core.SOURCES / str(copied["id"]) / f"{new}-{path.name.split('-', 1)[1]}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        workspace = db.WORKSPACE / course["slug"]
        if workspace.exists():
            shutil.copytree(workspace, db.workspace(copied["slug"]), dirs_exist_ok=True)
    except OSError as e:
        # Half a copy is no copy: the rows go, the files that did land go with them.
        log.warning("files of the copy of course %s not made: %s", course_id, e)
        _remove_course(db.course(copied["id"]))
        raise HTTPException(500, "the copy could not be made") from None
    return {k: copied[k] for k in ("id", "topic", "slug", "mechanism", "level", "archived", "mode")}


def _copy_name(course: dict) -> str:
    """"Topic (2)", "Topic (3)", …: a number after the topic, past any number it already carries."""
    base = re.sub(r" \(\d+\)$", "", course["topic"])
    n = 2
    while db.row("SELECT 1 FROM courses WHERE profile_id = ? AND topic = ?", course["profile_id"], f"{base} ({n})"):
        n += 1
    return f"{base} ({n})"


def _placement_picks(course_id: int) -> list[dict]:
    finished = {r["concept_id"] for r in db.rows(
        "SELECT DISTINCT l.concept_id FROM lessons l JOIN blocks b ON b.lesson_id = l.id WHERE l.course_id = ? AND b.kind = 'done'", course_id,
    )}
    return [
        card for unit in db.concepts(course_id)
        if unit["kind"] == "concept" and not unit["unwritten"] and not unit["known"] and unit["id"] not in finished
        if (card := db.row(
            "SELECT * FROM cards k WHERE concept_id = ? AND parent_id IS NULL AND retired = 0 AND NOT EXISTS ("
            # a teach-back's hidden card holds its key points; one installed before it got its card names it by key
            "SELECT 1 FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = k.course_id AND json_extract(b.data, '$.teachback') "
            "AND (json_extract(b.data, '$.card_id') = k.id OR json_extract(b.data, '$.card') = k.key)"
            ") ORDER BY kind = 'open', id LIMIT 1", unit["id"],
        ))
    ]


def _add_placement_quiz(lesson_id: int, card: dict) -> None:
    options = json.loads(card["options"])
    shown = {"card_id": card["id"], "kind": card["kind"], "answer": None, "pretest": False, "unit": card["concept_id"],
             "options": [{"text": o["text"]} for o in options] if card["kind"] == "sort" else options}
    if card["kind"] == "sort":
        shown["categories"] = json.loads(card["answer_key"])
    db.add_block(lesson_id, "quiz", card["question"], shown)


@app.post("/api/courses/{course_id}/placement/cards")
def card_placement(course_id: int) -> dict:
    """An imported course places the learner from its own cards, one per written unit, with no tutor: a unit whose card
    is answered right is marked known."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if course["mode"] != "replay":
        raise HTTPException(409, "only an imported course places you from its cards")
    picks = _placement_picks(course_id)
    if not picks:
        raise HTTPException(409, "this course has no cards left to place you with")
    locale = db.profile(course["profile_id"])["locale"]
    lesson_id = db.create_lesson(course_id, PLACEMENT_TITLE.get(locale, PLACEMENT_TITLE["en"]), "placement")
    for card in picks:
        _add_placement_quiz(lesson_id, card)
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    return view


@app.post("/api/courses/{course_id}/setup/{index}", status_code=202)
async def decide_setup(course_id: int, index: int, body: Decision) -> dict:
    """The learner's answer to one setup command an imported course came with: allowed, it runs in the course's
    sandbox with internet, logged like any command; no tutor turn follows."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    steps = json.loads(course["setup"] or "[]")
    if not 0 <= index < len(steps):
        raise HTTPException(404, "no such setup command")
    if steps[index]["status"] not in ("asked", "failed"):
        raise HTTPException(409, "already decided")
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? ORDER BY id LIMIT 1", course_id)["id"])
    command = steps[index]["command"]

    def save(status: str, **extra) -> list[dict]:
        steps[index] = {"command": command, "status": status, **extra}
        db.conn.execute("UPDATE courses SET setup = ? WHERE id = ?", (json.dumps(steps), course_id))
        hub.publish(course_id, {"type": "setup.updated", "setup": steps})
        return steps

    if not body.allow:
        db.log_command(lesson, "network", command, consent="refused")
        return {"setup": save("refused")}
    if not sandbox.commands() or not sandbox.networked():
        raise HTTPException(409, "this server cannot give commands the internet")
    save("running")

    async def run() -> None:
        try:
            result = await practice_tools._logged(lesson, "network", command, sandbox.run(command, db.workspace(course["slug"]), network=True), consent="allowed")
            save("done" if result["exit_code"] == 0 else "failed", exit_code=result["exit_code"])
        except Exception as e:
            log.warning("setup command of course %s failed: %s", course_id, e)
            save("failed", exit_code=None)

    job = asyncio.create_task(run())
    _jobs.add(job)
    job.add_done_callback(_jobs.discard)
    return {"setup": steps}


@app.post("/api/courses/{course_id}/resources/{kind}")
async def decide_resource(course_id: int, kind: str, body: Decision) -> dict:
    """The learner's answer to language data the tutor offered: refused, or downloaded in the background."""
    _course(course_id)
    row = db.row("SELECT status FROM course_resources WHERE course_id = ? AND kind = ?", course_id, kind)
    if not row:
        raise HTTPException(404, "no such resource")
    if row["status"] not in ("asked", "failed"):
        raise HTTPException(409, "already decided")
    resources.decide(course_id, kind, body.allow)
    return {"resources": resources.view(course_id)}


@app.post("/api/courses/{course_id}/archive")
def archive_course(course_id: int, body: Archive) -> dict:
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    db.conn.execute("UPDATE courses SET archived = ? WHERE id = ?", (int(body.archived), course_id))
    return {"archived": body.archived}


@app.post("/api/courses/{course_id}/rename")
def rename_course(course_id: int, body: Topic) -> dict:
    """Only the name changes: the course's workspace folder keeps the name it was made with."""
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(422, "a course needs a name")
    db.conn.execute("UPDATE courses SET topic = ? WHERE id = ?", (topic, course_id))
    return db.course(course_id)


@app.post("/api/courses/{course_id}/delete", status_code=204)
def delete_course(course_id: int) -> None:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if any(lesson["id"] in _turns for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course_id)):
        raise HTTPException(409, "the tutor is still answering in this course")
    _remove_course(course)


def _remove_course(course: dict) -> None:
    """The course's rows and every folder of its own: workspace, materials, command cache, agent sessions, vault mirror."""
    if vault.enabled():
        try:
            vault.remove(course["id"])
        except Exception as e:  # the vault is a mirror: a failure there must not keep the course alive
            log.warning("vault folder of course %s not removed: %s", course["id"], e)
    db.delete_course(course["id"])
    shutil.rmtree(db.workspace(course["slug"]), ignore_errors=True)
    shutil.rmtree(core.SOURCES / str(course["id"]), ignore_errors=True)
    handwork.remove_course(course["id"])
    # A later course may get the same slug: it must not inherit this one's command cache or agent folder.
    for leftover in ("sandbox-cache", "agents"):
        shutil.rmtree(db.DB_PATH.parent / leftover / course["slug"], ignore_errors=True)


@app.post("/api/courses")
async def create_course(body: NewCourse) -> dict:
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(422, "topic is empty")
    return db.create_course(topic, _profile(body.profile_id)["id"])


@app.post("/api/courses/{course_id}/start", status_code=202)
async def start_course(course_id: int, body: Scope) -> dict:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if course["started"]:
        raise HTTPException(409, "the interview already started")
    # One line: the scope rides in every turn prompt, where a line break could pass for a new [event] or [state] line.
    details = " ".join(body.details.split())
    db.conn.execute("UPDATE courses SET details = ?, hours = ?, started = 1 WHERE id = ?", (details, body.hours, course_id))
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course_id)
    core._start_turn(db.lesson(interview["id"]), "[event] The learner just created this course. Begin the interview.")
    return db.course(course_id)


@app.get("/api/courses/{course_id}")
def get_course(course_id: int) -> dict:
    return _course(course_id)


@app.get("/api/courses/{course_id}/events", response_class=EventSourceResponse)
async def events(course_id: int):
    async for event in hub.subscribe(course_id):
        yield ServerSentEvent(data=event)


class Pace(BaseModel):
    pace: Literal["momentum", "speed"]


@app.post("/api/courses/{course_id}/pace")
def set_pace(course_id: int, body: Pace) -> dict:
    """momentum: short units at a steady pace; speed: longer units the learner can test out of. Changeable any time."""
    if _course(course_id)["mode"] == "teacher":
        raise HTTPException(409, "a prepared course has no pace")
    plan_tools.save_pace(course_id, body.pace)
    return {"pace": body.pace}


@app.post("/api/courses/{course_id}/mechanism")
async def choose_mechanism(course_id: int, body: Choice) -> dict:
    course = _course(course_id)
    if body.mechanism not in [r["mechanism"] for r in course["ranking"]]:
        raise HTTPException(422, "that approach is not in the plan")
    db.conn.execute("UPDATE courses SET mechanism = ? WHERE id = ?", (body.mechanism, course_id))
    hub.publish(course_id, {"type": "plan.chosen", "mechanism": body.mechanism})
    return {"mechanism": body.mechanism}


@app.post("/api/courses/{course_id}/plan/accept", status_code=202)
async def accept_plan(course_id: int) -> None:
    course = _course(course_id)
    if not course["mechanism"]:
        raise HTTPException(409, "there is no plan yet")
    _require_unplaced(course)
    interview = _lesson(course["lessons"][0]["id"])
    core._require_idle(interview["id"])
    who = "The teacher" if course["mode"] == "teacher" else "The learner"
    tail = "" if course["mode"] == "teacher" else " and skipped the placement check"
    core._start_turn(interview, f"[event] {who} accepted the plan with mechanism {course['mechanism']}{tail}. Build the course map.{_playbook_line(course['mechanism'])}")


LINK_MAP = (
    "[event] The course map was made before units had prerequisites. Call set_prerequisites once: for each unit, "
    "the earlier units it builds on directly, by the exact titles below. Ask nothing and write nothing in the chat; "
    "end the turn after the call. Course map:\n"
)


@app.post("/api/courses/{course_id}/prerequisites")
async def link_map(course_id: int) -> dict:
    """A map made before units had prerequisites gets them worked out once, in the interview's session, without a word
    to the learner. Asked again while that runs, or after, it starts nothing."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    interview = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'interview' ORDER BY id LIMIT 1", course_id)
    if course["prerequisites"] or not db.concepts(course_id) or not interview or interview["id"] in _turns:
        return {"started": False}
    core._start_turn(_lesson(interview["id"]), LINK_MAP + _map_outline(course_id, None), quiet=True)
    return {"started": True}


DRAW_COVER = (
    "[event] The course has no cover yet. Call set_cover once with a cover for it, drawn from its topic, scope and "
    "map below. Ask nothing and write nothing in the chat; end the turn after the call.\n"
)


@app.post("/api/courses/{course_id}/cover")
async def draw_cover(course_id: int) -> dict:
    """A course with a map and no cover gets one drawn, in the interview's session, without a word to the learner.
    Asked again while that runs, or after, it starts nothing."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    interview = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'interview' ORDER BY id LIMIT 1", course_id)
    if course["cover"] or not db.concepts(course_id) or not interview or interview["id"] in _turns:
        return {"started": False}
    scope = f"Topic: {course['topic']}. Scope: {course['details'] or 'none given'}. Course map:\n"
    core._start_turn(_lesson(interview["id"]), DRAW_COVER + scope + _map_outline(course_id, None), quiet=True)
    return {"started": True}


@app.get("/api/courses/{course_id}/cover")
def get_cover(course_id: int) -> Response:
    course = db.course(course_id)
    if not course or not course["cover"]:
        raise HTTPException(404, "no cover")
    return Response(course["cover"], media_type="image/svg+xml", headers={"Content-Security-Policy": "default-src 'none'"})


@app.post("/api/courses/{course_id}/claims")
async def extract_claims(course_id: int) -> dict:
    """The finished lessons of a learner's course whose claims were not taken out yet go to the extractor."""
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    return {"queued": _queue_claims(db.unextracted(course_id))}


@app.post("/api/courses/{course_id}/placement")
async def start_placement(course_id: int) -> dict:
    course = _course(course_id)
    _require_learner(course)
    if not course["mechanism"]:
        raise HTTPException(409, "there is no plan yet")
    _require_unplaced(course)
    questions = placement_length(course["hours"])
    lesson_id = db.create_lesson(course_id, "Placement", "placement", questions=questions)
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    core._start_turn(
        _lesson(lesson_id),
        f"[event] The learner accepted the plan with mechanism {course['mechanism']}. The placement check begins. "
        f"It has {questions} questions{_batches(questions)}.{_playbook_line(course['mechanism'])}",
    )
    return view


# A placement check of up to this many questions comes in two batches, a longer one in three.
PLACEMENT_TWO_BATCHES = 6


def _batches(questions: int) -> str:
    """How the start of a placement check asks for its questions: a few batches, each answered before the next."""
    batches = 2 if questions <= PLACEMENT_TWO_BATCHES else 3
    return f", posed in {batches} batches of about {math.ceil(questions / batches)}"


def placement_length(hours: float | None) -> int:
    """Questions in a placement check: a few for a course of an hour or two, more the longer the course."""
    if hours is None:
        return PLACEMENT_UNTIMED
    fewest, most = PLACEMENT_QUESTIONS
    return max(fewest, min(most, round(fewest + 2 * math.log2(max(hours, 1)))))


def _hours_left(course: dict) -> float | None:
    """The course's teaching time still ahead: its hours, less the share of the map already mastered or placed out."""
    if not course["hours"] or not course["concepts"]:
        return course["hours"]
    return course["hours"] * sum(1 - (c["mastery"] or 0) for c in course["concepts"]) / len(course["concepts"])


@app.post("/api/courses/{course_id}/placement/retake")
async def retake_placement(course_id: int) -> dict:
    """A fresh placement check at any time; its result recalibrates the level, the vocabulary tier and the map."""
    course = _course(course_id)
    _require_learner(course)
    if not course["concepts"]:
        raise HTTPException(409, "there is no course map yet; the first placement comes with the plan")
    earlier = [lesson for lesson in course["lessons"] if lesson["phase"] == "placement"]
    for lesson in earlier:
        core._require_idle(lesson["id"])
    hours = _hours_left(course)
    questions = placement_length(hours)
    lesson_id = db.create_lesson(course_id, f"Placement · retake {len(earlier)}" if earlier else "Placement", "placement", questions=questions)
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    before = f"level {course['level']!r}: {course['placement']}" if course["level"] else "none; the check was skipped"
    if areas := db.placement_areas(course_id):
        before += f" By area: {_areas_line(areas)}."
    core._start_turn(
        _lesson(lesson_id),
        f"[event] The learner retakes the placement check. Earlier result: {before}. Run the check again from the start. "
        + (f"About {math.ceil(hours)} of the course's {course['hours']} hours are still ahead. " if hours is not None else "")
        + f"It has {questions} questions{_batches(questions)}. At the end call set_placement, then set_known for the existing course map instead of set_course_map.",
    )
    return view


@app.get("/api/courses/{course_id}/search")
def search_course(course_id: int, q: str = "", kind: Literal["", "source", "card", "chat", "code"] = "", n: int = 20) -> list[dict]:
    """The course's sources, cards, chats and code best matching q, or only those of one kind, each with its snippet
    cut into plain and matched parts."""
    _course(course_id)
    return [
        {**{k: h[k] for k in ("kind", "ref", "lesson_id", "concept_id", "title", "text", "by")}, "snippet": _parts(h["snippet"])}
        for h in search.search(course_id, q, min(n, 50), (kind,) if kind else search.KINDS)
    ]


def _parts(snippet: str) -> list[tuple[str, bool]]:
    pieces = re.split(f"{search.MARK[0]}(.*?){search.MARK[1]}", snippet)
    return [(piece, i % 2 == 1) for i, piece in enumerate(pieces) if piece]


@app.get("/api/courses/{course_id}/sources")
def list_sources(course_id: int) -> list[dict]:
    _course(course_id)
    return db.sources(course_id)


def _store_source(course_id: int, name: str, data: bytes) -> dict:
    if len(db.sources(course_id)) >= SOURCES_PER_COURSE:
        raise HTTPException(409, f"a course holds at most {SOURCES_PER_COURSE} files")
    if len(data) > SOURCE_LIMIT:
        raise HTTPException(413, "files are limited to 50 MB")
    if sum(s["size"] for s in db.sources(course_id)) + len(data) > COURSE_SOURCE_BYTES:
        raise HTTPException(413, "a course holds at most 200 MB of files")
    source = db.add_source(course_id, name, len(data))
    path = core.SOURCES / str(course_id) / f"{source['id']}-{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    job = asyncio.create_task(_process_source(source["id"], course_id, path))
    _jobs.add(job)
    job.add_done_callback(_jobs.discard)
    return source


@app.post("/api/courses/{course_id}/sources")
async def upload_source(course_id: int, file: UploadFile) -> dict:
    _course(course_id)
    data = await file.read(SOURCE_LIMIT + 1)
    return _store_source(course_id, Path(file.filename or "file").name, data)


async def _public_address(host: str, networks: list) -> str:
    """The address the server will connect to: resolved here, checked here, and used for the connection itself,
    so a name cannot answer one thing to the check and another to the connect."""
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(422, "that address does not resolve") from None
    addresses = [info[4][0] for info in found]
    if not addresses or not all(egress.allowed(address, networks) for address in addresses):
        raise HTTPException(422, "only public web addresses can be fetched")
    return addresses[0]


def _material_name(url: httpx.URL, kind: str) -> str:
    """A file name for a fetched document: from the address, else from its type; bounded and plain."""
    name = Path(unquote(url.path)).name
    if name in ("", ".", ".."):
        name = url.host
    name = re.sub(r"[\\/\n\r\t\[\]]+", " ", name).strip()[:100] or "document"
    suffix = FETCH_TYPES.get(kind)
    if suffix and Path(name).suffix.lower() != suffix:
        name = Path(name).stem + suffix
    if Path(name).suffix.lower() not in sources.HEADING_SUFFIXES | sources.TEXT_SUFFIXES:
        raise HTTPException(422, "that address is not a PDF, EPUB, HTML, Markdown or text document")
    return name


def _require_public_web(target: httpx.URL) -> None:
    if target.scheme not in ("http", "https") or not target.host:
        raise HTTPException(422, "the address must start with http:// or https://")
    if target.port not in (None, 80, 443):
        raise HTTPException(422, "only public web addresses can be fetched")


def _follow(target: httpx.URL, location: str) -> httpx.URL:
    try:
        return target.join(location)
    except httpx.InvalidURL:
        raise HTTPException(422, "the address must start with http:// or https://") from None


async def _read_limited(res: httpx.Response) -> bytearray:
    data = bytearray()
    async for chunk in res.aiter_bytes():
        data += chunk
        if len(data) > SOURCE_LIMIT:
            raise HTTPException(413, "files are limited to 50 MB")
    return data


async def fetch_material(url: str) -> tuple[str, bytes]:
    """Download a document for a course on the learner's behalf: public addresses only, ports 80 and 443, every
    redirect hop checked, the connection made to the checked address; returns (file name, bytes)."""
    try:
        target = httpx.URL(url)
    except httpx.InvalidURL:
        raise HTTPException(422, "the address must start with http:// or https://") from None
    networks = await asyncio.to_thread(egress.local_networks)
    async with httpx.AsyncClient(follow_redirects=False, timeout=FETCH_TIMEOUT, trust_env=False, headers={"User-Agent": "wise-scholar"}) as client:
        for _ in range(FETCH_HOPS):
            _require_public_web(target)
            address = await _public_address(target.host, networks)
            request = client.build_request(
                "GET", target.copy_with(host=address), headers={"Host": target.host}, extensions={"sni_hostname": target.host}
            )
            res = await client.send(request, stream=True)
            try:
                if res.is_redirect and res.headers.get("location"):
                    target = _follow(target, res.headers["location"])
                    continue
                if res.status_code != 200:
                    raise HTTPException(422, "the address did not answer with a document")
                kind = (res.headers.get("content-type") or "").split(";")[0].strip().lower()
                data = await _read_limited(res)
                break
            finally:
                await res.aclose()
        else:
            raise HTTPException(422, "the address redirects too many times")
    return _material_name(target, kind), bytes(data)


@app.post("/api/courses/{course_id}/sources/url")
async def fetch_source(course_id: int, body: SourceUrl) -> dict:
    _course(course_id)
    if len(db.sources(course_id)) >= SOURCES_PER_COURSE:
        raise HTTPException(409, f"a course holds at most {SOURCES_PER_COURSE} files")
    try:
        name, data = await asyncio.wait_for(fetch_material(body.url.strip()), FETCH_DEADLINE)
    except httpx.HTTPError as e:
        raise HTTPException(422, "the address could not be fetched") from e
    except TimeoutError:
        raise HTTPException(422, "the address took too long to answer") from None
    return _store_source(course_id, name, data)


async def _process_source(source_id: int, course_id: int, path: Path) -> None:
    try:
        parts = await asyncio.to_thread(sources.extract, path)
        cut = sources.sections(parts, path.name.split("-", 1)[-1])
        source = db.finish_source(source_id, cut, None if cut else "no text could be read from the file")
    except sources.Unreadable as e:
        source = db.finish_source(source_id, [], str(e))
    except Exception as e:
        log.warning("source %s failed: %s", source_id, e)
        source = db.finish_source(source_id, [], "the file could not be read")
    if source:
        hub.publish(course_id, {"type": "source.updated", "source": source})


@app.post("/api/courses/{course_id}/episode")
async def next_episode(course_id: int) -> dict:
    course = _course(course_id)
    if not course["lang"]:
        raise HTTPException(409, "episodes are for language courses; the first reading sets the language")
    show = db.series(course_id)
    n = (show["episodes"] if show else 0) + 1
    lesson_id = db.create_lesson(course_id, f"Episode {n}", "story")
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    if show:
        line = (
            f"[event] Episode {n} of the series {show['title']!r}. Characters:\n{_untrusted(show['characters'])}\nSynopsis so far:{_untrusted(show['synopsis'])}"
        )
    else:
        line = "[event] The learner wants to start reading a series. There is no series yet."
    core._start_turn(_lesson(lesson_id), line)
    return view


@app.post("/api/courses/{course_id}/writing")
async def writing_session(course_id: int) -> dict:
    course = _course(course_id)
    if not course["mechanism"]:
        raise HTTPException(409, "there is no plan yet")
    n = sum(1 for lesson in course["lessons"] if lesson["phase"] == "writing") + 1
    lesson_id = db.create_lesson(course_id, f"Writing session {n}", "writing")
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    core._start_turn(_lesson(lesson_id), "[event] The learner opens a writing session. Pose one writing task for their level.")
    return view


@app.post("/api/courses/{course_id}/roleplay")
async def roleplay_session(course_id: int) -> dict:
    course = _course(course_id)
    if not course["lang"]:
        raise HTTPException(409, "role-plays are for language courses; the first reading sets the language")
    n = sum(1 for lesson in course["lessons"] if lesson["phase"] == "roleplay") + 1
    lesson_id = db.create_lesson(course_id, f"Role-play {n}", "roleplay")
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    core._start_turn(_lesson(lesson_id), "[event] The learner opens a role-play. Set the scene and speak first, in character.")
    return view


@app.get("/api/courses/{course_id}/errors")
def list_course_errors(course_id: int) -> list[dict]:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    return db.errors(course["profile_id"], course_id)


@app.get("/api/courses/{course_id}/warmup")
def warmup(course_id: int) -> dict:
    """How many cards open the sitting: a learner back after SITTING_GAP or more starts with a few due reviews."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    now, profile = datetime.now(timezone.utc), course["profile_id"]
    recent = [t for t in (db.last_activity(profile), _warmed.get(profile)) if t and now - t < SITTING_GAP]
    if recent:
        return {"due": 0}
    return {"due": len(_due(profile))}
