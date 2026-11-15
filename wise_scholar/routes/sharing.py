import asyncio
import os
import re
from datetime import datetime, timezone
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from typing import Literal

from .. import app as core
from .. import book, bundle, db, hub, obsidian, recap
from ..tools import side_turns as side_tools
from ..app import LOCALE_NAMES, _course, _cut, _now, _profile, _turns, _untrusted, app, log


@app.get("/api/courses/{course_id}/publish")
def publish_preview(course_id: int) -> dict:
    """What a new version would carry, for the author to check before publishing."""
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    return bundle.preview(course_id)


class Publish(BaseModel):
    notes: str = Field(default="", max_length=4000)
    licence: Literal[bundle.LICENCES] = "CC-BY-SA-4.0"  # type: ignore[valid-type]
    forkable: bool = True
    sources: list[int] = []


@app.post("/api/courses/{course_id}/versions")
def publish_version(course_id: int, body: Publish) -> dict:
    """Freeze the course as its next version, a bundle anyone can import."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if (origin := bundle.preview(course_id)["forked_from"]) and not origin["forkable"]:
        raise HTTPException(409, "the author of this course does not allow versions made from it")
    if any(lesson["id"] in _turns for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course_id)):
        raise HTTPException(409, "wait for the tutor to finish before publishing")
    if not bundle.finished_lessons(course_id):
        raise HTTPException(409, "no lesson of this course is finished yet, so there is nothing to publish")
    if course_id in _checks:
        raise HTTPException(409, "wait for the check of this course to finish before publishing")
    return bundle.publish(course_id, notes=body.notes, licence=body.licence, forkable=body.forkable, sources=body.sources,
                          source_dir=core.SOURCES, store=core.VERSIONS)


# --- Publish check: before a version goes out, the tutor reads it for what points at its author -------------------
CHECK_CHARS = 40000
CHECK_PIECE_CHARS = 12000
_checks: dict[int, asyncio.Task] = {}
_checks_failed: set[int] = set()


def _check_prompts(course: dict, lesson: dict, pieces: dict[tuple[str, str], str], manifest: dict) -> list[str]:
    """The version's pieces cut into turns of about CHECK_CHARS, each opened by the same header lines."""
    titles = {b["key"]: x["title"] for x in manifest["lessons"] for b in x["blocks"]} | {x["key"]: x["title"] for x in manifest["lessons"]}
    header = "\n".join([
        f"[state] course_id={course['id']} course={course['topic']!r}",
        f"[language] Write the edits in {LOCALE_NAMES[lesson['locale']]}; code, commands and identifiers stay as they are.",
        f"[author] {lesson['profile']!r}",
        *(f"[known of the author] {_untrusted(f['text'])}" for f in db.facts(course["id"])),
    ])
    turns, lines, size = [], [], 0
    for (target, ref), text in pieces.items():
        head = f"[{target} {ref}" + (f', lesson "{titles[ref]}"' if ref in titles else "") + "]"
        line = f"{head}\n{_untrusted(_cut(text, CHECK_PIECE_CHARS))}"
        if lines and size + len(line) > CHECK_CHARS:
            turns.append("\n\n".join([header, *lines]))
            lines, size = [], 0
        lines.append(line)
        size += len(line)
    return turns + (["\n\n".join([header, *lines])] if lines else [])


async def _check(course_id: int) -> None:
    """Read the version as it would be published now, accepted edits made, and leave the edits proposed for the author."""
    course = db.course(course_id)
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? ORDER BY id LIMIT 1", course_id)["id"])
    manifest, assets, _ = bundle.build(course_id, notes="", licence=bundle.LICENCES[0], forkable=True, sources=[], source_dir=core.SOURCES,
                                       edits=bundle.accepted_edits(course_id))
    pieces = bundle.texts(manifest, assets)
    db.conn.execute("DELETE FROM publish_edits WHERE course_id = ? AND status = 'proposed'", (course_id,))
    side_tools.cleanup_jobs[course_id] = pieces
    try:
        for prompt in _check_prompts(course, lesson, pieces, manifest):
            if not await core._background_turn(lesson, prompt, "cleanup", "publish check"):
                _checks_failed.add(course_id)
                return
    finally:
        side_tools.cleanup_jobs.pop(course_id, None)
    db.conn.execute("UPDATE courses SET checked = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), course_id))


def _edit_view(edit: dict) -> dict:
    where = None
    if edit["target"] == "block":
        where = db.row("SELECT l.title FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE b.key = ? AND l.course_id = ?",
                       edit["ref"], edit["course_id"])
    elif edit["target"] == "summary":
        where = db.row("SELECT title FROM lessons WHERE key = ? AND course_id = ?", edit["ref"], edit["course_id"])
    return {**{k: edit[k] for k in ("id", "target", "ref", "old", "new", "reason", "status")}, "lesson": where and where["title"]}


@app.get("/api/courses/{course_id}/check")
def publish_check(course_id: int) -> dict:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    edits = db.rows("SELECT * FROM publish_edits WHERE course_id = ? ORDER BY id", course_id)
    return {"running": course_id in _checks, "failed": course_id in _checks_failed, "checked": course["checked"], "edits": list(map(_edit_view, edits))}


@app.post("/api/courses/{course_id}/check")
async def start_publish_check(course_id: int) -> dict:
    """Have the tutor read the version for the author's name, places, paths and personal context, and propose edits."""
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    if course_id in _checks:
        raise HTTPException(409, "this course is already being checked")
    if not bundle.finished_lessons(course_id):
        raise HTTPException(409, "no lesson of this course is finished yet, so there is nothing to check")
    _checks_failed.discard(course_id)

    async def run() -> None:
        try:
            await _check(course_id)
        except Exception:
            log.exception("publish check of course %s", course_id)
            _checks_failed.add(course_id)
        finally:
            _checks.pop(course_id, None)

    _checks[course_id] = asyncio.create_task(run())
    return publish_check(course_id)


class EditStatus(BaseModel):
    status: Literal["proposed", "accepted", "rejected"]


@app.post("/api/courses/{course_id}/check/{edit_id}")
def decide_edit(course_id: int, edit_id: int, body: EditStatus) -> dict:
    """The author's say on one proposed edit; an accepted one changes every version published from now on, never the course."""
    if not db.row("SELECT 1 FROM publish_edits WHERE id = ? AND course_id = ?", edit_id, course_id):
        raise HTTPException(404, "no such edit")
    db.conn.execute("UPDATE publish_edits SET status = ? WHERE id = ?", (body.status, edit_id))
    return publish_check(course_id)


@app.get("/api/versions/{version_hash}/bundle")
def version_bundle(version_hash: str) -> FileResponse:
    v = db.row("SELECT * FROM versions WHERE hash = ?", version_hash) if re.fullmatch(r"[0-9a-f]{64}", version_hash) else None
    path = core.VERSIONS / f"{version_hash}.zip"
    if not v or not path.exists():
        raise HTTPException(404, "no such version")
    name = f"{re.sub(r'[^a-z0-9]+', '-', v['topic'].lower()).strip('-')[:60] or 'course'}-v{v['number']}.zip"
    return FileResponse(path, media_type="application/zip", filename=name)


@app.post("/api/import")
async def import_course(profile: int, file: UploadFile) -> dict:
    """A course from a version bundle, in replay mode for the profile; the bundle comes from anyone, so it is
    checked whole before anything is written."""
    _profile(profile)
    data = await file.read(bundle.BUNDLE_LIMIT + 1)
    try:
        version_hash, manifest, assets = bundle.unpack(data)
    except ValueError as e:
        log.warning("bundle not imported: %s", e)
        raise HTTPException(422, "that file is not a course bundle this app can read") from None
    core.VERSIONS.mkdir(parents=True, exist_ok=True)
    if not (core.VERSIONS / f"{version_hash}.zip").exists():
        (core.VERSIONS / f"{version_hash}.zip").write_bytes(data)
    # A newer version of a course the profile already plays is offered on that course rather than added beside it.
    if older := manifest.version.lineage and db.row(
        "SELECT c.id, c.topic, c.slug, c.mode FROM courses c JOIN versions v ON v.hash = c.source_version "
        "WHERE c.profile_id = ? AND c.mode = 'replay' AND v.lineage = ? AND v.number < ? ORDER BY v.number DESC LIMIT 1",
        profile, manifest.version.lineage, manifest.version.number,
    ):
        bundle.record_version(version_hash, manifest)
        db.conn.execute("UPDATE courses SET skipped_version = NULL WHERE id = ?", (older["id"],))
        return {**older, "refused_files": [], "upgrade": manifest.version.number}
    try:
        course = bundle.install(profile, version_hash, manifest, assets, core.SOURCES)
    except ValueError as e:
        log.warning("bundle not imported: %s", e)
        raise HTTPException(422, "that file is not a course bundle this app can read") from None
    return {k: course[k] for k in ("id", "topic", "slug", "mode", "refused_files")}


class Upgrade(BaseModel):
    hash: str


@app.post("/api/courses/{course_id}/upgrade")
def upgrade_course(course_id: int, body: Upgrade) -> dict:
    """Move a replayed course to the newer version it was offered: unchanged units keep the learner's progress."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    v = bundle.newer(course, core.VERSIONS)
    if not v or v["hash"] != body.hash:
        raise HTTPException(409, "that version is not the one this course can move to")
    if any(lesson["id"] in _turns for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course_id)):
        raise HTTPException(409, "wait for the tutor to finish before upgrading")
    _, new, assets = bundle.unpack((core.VERSIONS / f"{v['hash']}.zip").read_bytes())
    done = bundle.upgrade(course_id, v["hash"], new, assets, bundle.stored(core.VERSIONS, course["source_version"]), core.SOURCES)
    hub.publish(course_id, {"type": "map.set", "concepts": db.concept_view(course_id)})
    return {**_course(course_id), "upgraded": done}


@app.post("/api/courses/{course_id}/upgrade/skip")
def skip_upgrade(course_id: int, body: Upgrade) -> dict:
    """Stay on the version played; the offer comes back when a still newer one arrives."""
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    db.conn.execute("UPDATE courses SET skipped_version = ? WHERE id = ?", (body.hash, course_id))
    return _course(course_id)


# --- Recap: a finished course told back to the learner, its narrative written once by a turn of its own --------------
# A developer setting: shows any learner course as a recap so far, without its narrative.
RECAP_PREVIEW = os.environ.get("WISE_SCHOLAR_RECAP_PREVIEW") == "1"
_recapping: dict[int, asyncio.Task] = {}
_recap_failed: set[int] = set()  # tried in this process and failed: only the learner's asking tries again before a restart


async def _write_recap(course_id: int) -> None:
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? ORDER BY id LIMIT 1", course_id)["id"])
    story = await asyncio.to_thread(recap.story, course_id, _now())
    job = {"weeks": story["weeks"], "locale": lesson["locale"], "finished": story["finished"], "done": False}
    side_tools.recap_jobs[course_id] = job
    try:
        prompt = "\n".join([
            f"[state] course_id={course_id}",
            f"[language] Write in {LOCALE_NAMES[lesson['locale']]}; code, commands and identifiers stay as they are.",
            recap.outline(story),
        ])
        ok = await core._background_turn(lesson, prompt, "recap", "course recap")
    finally:
        side_tools.recap_jobs.pop(course_id, None)
    if not ok or not job["done"]:
        _recap_failed.add(course_id)


def _start_recap(course_id: int) -> None:
    async def run() -> None:
        try:
            await _write_recap(course_id)
        except Exception:
            log.exception("recap of course %s", course_id)
            _recap_failed.add(course_id)
        finally:
            _recapping.pop(course_id, None)
            # the open recap page reloads, written or not
            hub.publish(course_id, {"type": "recap.written"})

    _recapping[course_id] = asyncio.create_task(run())


def _recap_course(course_id: int) -> dict:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if course["mode"] == "teacher":
        raise HTTPException(409, "a prepared course has no recap")
    return course


@app.get("/api/courses/{course_id}/recap")
async def get_recap(course_id: int, preview: bool = False) -> dict:
    """The finished course as a story. Its narrative is written the first time the recap is opened after the course
    is finished, and again after it is finished anew."""
    _recap_course(course_id)
    state = db.sync_recap(course_id)
    finished = bool(state and state["finished"])
    if not finished and not (preview and RECAP_PREVIEW):
        raise HTTPException(409, "this course is not finished yet")
    story = await asyncio.to_thread(recap.story, course_id, _now())
    stale = finished and (not story["narrative"] or story["narrative"]["finished"] != story["finished"])
    if stale and course_id not in _recapping and course_id not in _recap_failed:
        _start_recap(course_id)
    return {**story, "preview": not finished, "writing": course_id in _recapping, "failed": course_id in _recap_failed}


@app.post("/api/courses/{course_id}/recap/write", status_code=202)
async def rewrite_recap(course_id: int) -> dict:
    """The learner asked for the narrative again, in the profile's language as it is now."""
    _recap_course(course_id)
    state = db.sync_recap(course_id)
    if not (state and state["finished"]):
        raise HTTPException(409, "this course is not finished yet")
    if course_id not in _recapping:
        _recap_failed.discard(course_id)
        _start_recap(course_id)
    return {"writing": True}


@app.post("/api/courses/{course_id}/recap/seen")
def see_recap(course_id: int) -> dict:
    if db.recap(course_id):
        db.set_recap(course_id, seen=1)
    return {"seen": True}


class RecapLayout(BaseModel):
    positions: dict[int, tuple[float, float]]


@app.post("/api/courses/{course_id}/recap/positions")
def save_recap_layout(course_id: int, body: RecapLayout) -> dict:
    """Where each claim sits in the recap's graph, laid out once so the graph grows without moving."""
    if not db.recap(course_id):
        raise HTTPException(409, "this course has no recap")
    db.set_recap(course_id, positions={str(k): list(v) for k, v in body.positions.items()})
    return {"saved": len(body.positions)}


@app.get("/api/courses/{course_id}/book.pdf")
async def course_book(course_id: int, theme: Literal["light", "dark"] = "light") -> Response:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if not book.available():
        raise HTTPException(503, "PDF export is not installed; run make pdf")
    try:
        pdf = await book.render(course_id, course["profile_id"], theme)
    except book.NoBrowser:
        raise HTTPException(503, "PDF export has no browser to print with; run make pdf") from None
    except TimeoutError as e:
        log.warning("book export timed out: %s", e)
        raise HTTPException(504, "the book did not finish drawing") from None
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{course["slug"]}.pdf"'})


@app.get("/api/courses/{course_id}/obsidian.zip")
async def course_vault(course_id: int) -> Response:
    """The course as a folder of linked Markdown notes for Obsidian; plots become PNGs when a browser is installed."""
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    pictures = {}
    if book.available():
        try:
            pictures = await book.plots(course_id, course["profile_id"], obsidian.plot_blocks(course_id))
        except Exception as e:  # the browser is optional here: specs stand in for pictures
            log.warning("plots left as specs in the Obsidian export: %s", e)
    data = await asyncio.to_thread(obsidian.export, course_id, pictures)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{course["slug"]}-obsidian.zip"'})
