import asyncio
import logging
import os
import shutil
import signal
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import simplemma

from . import challenge, db, history, hub, quiz, review, speech, tutor, vocab
from .backends import AGENT, BACKEND, claude, opencode
from .playbooks import describe

WEB_DIST = db.ROOT / "web" / "dist"
RUN_TIMEOUT = 30
OUTPUT_LIMIT = 20_000
CLIP_LIMIT = 25 * 1024 * 1024
# ponytail: on synthesized references right words score 0.97+ and wrong ones under 0.45; real accents are untested.
WEAK_WORD = 0.5
MISMATCH_SHARE = 0.5
backend = {"claude": claude, "opencode": opencode}[BACKEND]

log = logging.getLogger("wise_scholar")
_turns: dict[int, asyncio.Task] = {}

mcp_app = tutor.mcp.streamable_http_app(stateless_http=True, json_response=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A cast still rendering when the last process stopped will never finish.
    db.conn.execute(
        "UPDATE blocks SET data = json_set(data, '$.status', 'failed', '$.error', 'the server restarted') "
        "WHERE kind = 'podcast' AND json_extract(data, '$.status') = 'rendering'"
    )
    async with tutor.mcp.session_manager.run():
        await backend.start()
        try:
            yield
        finally:
            await backend.stop()
            speech.worker.stop()


app = FastAPI(lifespan=lifespan)
app.router.routes.extend(mcp_app.routes)


class NewCourse(BaseModel):
    topic: str
    profile_id: int


class Archive(BaseModel):
    archived: bool


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class Turn(BaseModel):
    text: str


class Answer(BaseModel):
    answer: str


class Choice(BaseModel):
    mechanism: str


class QuizAnswer(BaseModel):
    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class SelfGrade(BaseModel):
    correct: bool


class Word(BaseModel):
    word: str


class Known(BaseModel):
    known: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lesson(lesson_id: int) -> dict:
    lesson = db.lesson(lesson_id)
    if not lesson:
        raise HTTPException(404, "no such lesson")
    return lesson


def _course(course_id: int) -> dict:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    lessons = db.rows("SELECT id FROM lessons WHERE course_id = ? ORDER BY id", course_id)
    mastery = db.concept_mastery(course_id)
    return {
        **course,
        "ranking": describe(course["ranking"]),
        "concepts": [
            {**c, "mastery": mastery.get(c["id"], 1.0 if c["known"] else None)} for c in db.concepts(course_id)
        ],
        "strands": db.strand_counts(course_id) if course["mechanism"] == "leveled-course" else None,
        "vocabulary": {**db.vocabulary(course_id, _now()), **_tier_view(course)},
        "lessons": [_lesson_view(lesson["id"]) for lesson in lessons],
    }


def _tier_view(course: dict) -> dict:
    if not course["lang"]:
        return {}
    tier = db.vocab_tier(course["profile_id"], course["lang"], vocab.starting_tier(course["level"], course["lang"]))
    progress = vocab.tier_progress(course["lang"], tier, db.vocab_lemmas(course["profile_id"], course["lang"], ("known",)))
    return {"tier": tier, "tier_size": progress["size"], "tier_known": progress["known"], "tier_words": tier * vocab.TIER}


def _lesson_view(lesson_id: int) -> dict:
    lesson = db.row("SELECT id, title, phase, concept_id FROM lessons WHERE id = ?", lesson_id)
    lesson["messages"] = db.rows("SELECT * FROM messages WHERE lesson_id = ? ORDER BY id", lesson_id)
    lesson["blocks"] = db.blocks(lesson_id)
    lesson["running"] = lesson_id in _turns
    return lesson


def _challenge_block(block_id: int) -> dict:
    block = db.block(block_id)
    if not block or block["kind"] not in challenge.KINDS:
        raise HTTPException(404, "no such challenge")
    _require_idle(block["lesson_id"])
    if not challenge.is_open(block["data"]):
        raise HTTPException(409, "this challenge is closed")
    return block


def _challenge_state(block: dict) -> str:
    data = block["data"]
    return (
        f"challenge {block['id']}; attempts {len(data['attempts'])}; "
        f"hints given {len(data['hints'])} of {data['max_hints']}; "
        f"solution {'locked' if challenge.reveal_blocker(data) else 'unlocked'}"
    )


def _update_block(block: dict, change: dict) -> tuple[dict, dict]:
    lesson = _lesson(block["lesson_id"])
    block = db.set_block_data(block["id"], {**block["data"], **change})
    hub.publish(lesson["course_id"], {"type": "block.updated", "lesson_id": lesson["id"], "block": block})
    return lesson, block


def _map_outline(course_id: int, current: int) -> str:
    started = {r["concept_id"] for r in db.rows("SELECT concept_id FROM lessons WHERE course_id = ?", course_id)}
    lines, module = [], None
    for c in db.concepts(course_id):
        if c["module"] != module:
            module = c["module"]
            lines.append(f"{module}:")
        mark = "this lesson" if c["id"] == current else "already opened" if c["id"] in started else "not started"
        lines.append(f"  - {c['title']} ({mark})")
    return "\n".join(lines)


def _turn_prompt(lesson: dict, line: str) -> str:
    state = (
        f"[state] course_id={lesson['course_id']} topic={lesson['topic']!r} lesson_id={lesson['id']} "
        f"lesson={lesson['title']!r} phase={lesson['phase']} mechanism={lesson['mechanism'] or 'not chosen'}"
    )
    if lesson["level"]:
        state += f" level={lesson['level']!r}"
    if lesson["concept"]:
        state += f" module={lesson['module']!r} concept={lesson['concept']!r}"
    known = [
        f"[known] ({'this course' if f['course_id'] else 'learner'}) {f['text']}" for f in db.facts(lesson["course_id"])
    ]
    # Resumed sessions keep the style of their earlier replies, so the math rule rides along with every turn.
    fmt = "[format] All math in LaTeX: $...$ inline, $$...$$ displayed. No Unicode math symbols such as x², √, ∫; ordinary letters, accents, currency and units stay as they are."
    return "\n".join([state, *known, fmt, line])


async def _run_turn(lesson: dict, line: str) -> None:
    lesson_id, course_id = lesson["id"], lesson["course_id"]
    reply = ""
    final = {"type": "turn.done", "ok": False, "error": "stopped"}
    # A lesson started on another backend gets a fresh session here; the state header carries it over.
    resume = bool(lesson["session_started"]) and lesson["backend"] == BACKEND
    session_id = lesson["session_id"] if resume else str(uuid.uuid4())
    try:
        async for event in backend.run_turn(
            _turn_prompt(lesson, line),
            session_id=session_id,
            resume=resume,
            name=f"wise-scholar · {lesson['profile']} · {lesson['topic']} · {lesson['title']}",
            cwd=db.workspace(lesson["slug"]),
            phase=lesson["phase"],
        ):
            if event["type"] == "session.started":
                db.conn.execute(
                    "UPDATE lessons SET session_started = 1, backend = ?, session_id = ? WHERE id = ?",
                    (BACKEND, event.get("session_id", session_id), lesson_id),
                )
                continue
            if event["type"] == "chat.break":
                if not reply:
                    continue
                event = {"type": "chat.delta", "text": "\n\n"}
            if event["type"] == "chat.delta":
                reply += event["text"]
            if event["type"] == "turn.done":
                final = event
                break
            hub.publish(course_id, {**event, "lesson_id": lesson_id})
    except asyncio.CancelledError:
        pass
    finally:
        del _turns[lesson_id]
    message = db.add_message(lesson_id, "tutor", reply) if reply.strip() else None
    hub.publish(course_id, {**final, "lesson_id": lesson_id, "message": message})


def _start_turn(lesson: dict, line: str) -> None:
    _turns[lesson["id"]] = asyncio.create_task(_run_turn(lesson, line))
    hub.publish(lesson["course_id"], {"type": "turn.started", "lesson_id": lesson["id"]})


def _require_idle(lesson_id: int) -> None:
    if lesson_id in _turns:
        raise HTTPException(409, "the tutor is still answering")


def _require_unplaced(course: dict) -> None:
    if course["concepts"]:
        raise HTTPException(409, "the course map already exists")
    if any(lesson["phase"] == "placement" for lesson in course["lessons"]):
        raise HTTPException(409, "the placement check already started")


@app.get("/api/meta")
def meta() -> dict:
    return {"agent": AGENT, "speech": speech.available()}


@app.get("/api/tts")
async def text_to_speech(text: str, lang: str) -> FileResponse:
    if not 0 < len(text) <= 600:
        raise HTTPException(422, "one sentence or paragraph at a time, up to 600 characters")
    try:
        return FileResponse(await speech.tts(text.strip(), lang), media_type="audio/wav")
    except RuntimeError as e:
        log.warning("tts failed: %s", e)
        raise HTTPException(503, str(e)) from None


@app.get("/api/audio/podcasts/{name}")
async def podcast_audio(name: str) -> FileResponse:
    path = speech.AUDIO / "podcasts" / name
    if not (name.endswith(".opus") and name[:-5].isdigit() and path.exists()):
        raise HTTPException(404, "no such cast")
    return FileResponse(path, media_type="audio/ogg")


@app.post("/api/stt")
async def speech_to_text(audio: UploadFile, lang: str | None = None) -> dict:
    data = await audio.read(CLIP_LIMIT + 1)
    if len(data) > CLIP_LIMIT:
        raise HTTPException(413, "recordings are limited to 25 MB")
    clip = speech.AUDIO / "stt" / f"{uuid.uuid4()}.webm"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(data)
    try:
        return await speech.stt(clip, lang)
    except RuntimeError as e:
        log.warning("stt failed: %s", e)
        raise HTTPException(503, str(e)) from None
    finally:
        clip.unlink(missing_ok=True)


def _profile(profile_id: int) -> dict:
    profile = db.profile(profile_id)
    if not profile:
        raise HTTPException(404, "no such profile")
    return profile


def _save_profile(sql: str, *args) -> int:
    try:
        return db.conn.execute(sql, args).lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "a profile with that name already exists") from None


@app.get("/api/profiles")
def list_profiles() -> list[dict]:
    return db.profiles()


@app.post("/api/profiles")
def create_profile(body: Name) -> dict:
    return db.profile(_save_profile("INSERT INTO profiles (name) VALUES (?)", body.name.strip()))


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int) -> dict:
    return {**_profile(profile_id), "facts": db.learner_facts(profile_id)}


@app.post("/api/profiles/{profile_id}")
def rename_profile(profile_id: int, body: Name) -> dict:
    _profile(profile_id)
    _save_profile("UPDATE profiles SET name = ? WHERE id = ?", body.name.strip(), profile_id)
    return db.profile(profile_id)


@app.post("/api/facts/{fact_id}/forget", status_code=204)
def forget_fact(fact_id: int) -> None:
    db.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))


@app.get("/api/courses")
def list_courses(profile: int) -> list[dict]:
    return db.rows(
        "SELECT id, topic, slug, mechanism, level, archived FROM courses WHERE profile_id = ? ORDER BY id DESC",
        profile,
    )


@app.post("/api/courses/{course_id}/archive")
def archive_course(course_id: int, body: Archive) -> dict:
    if not db.course(course_id):
        raise HTTPException(404, "no such course")
    db.conn.execute("UPDATE courses SET archived = ? WHERE id = ?", (int(body.archived), course_id))
    return {"archived": body.archived}


@app.post("/api/courses/{course_id}/delete", status_code=204)
def delete_course(course_id: int) -> None:
    course = db.course(course_id)
    if not course:
        raise HTTPException(404, "no such course")
    if any(lesson["id"] in _turns for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course_id)):
        raise HTTPException(409, "the tutor is still answering in this course")
    db.delete_course(course_id)
    shutil.rmtree(db.workspace(course["slug"]), ignore_errors=True)


@app.post("/api/courses")
async def create_course(body: NewCourse) -> dict:
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(422, "topic is empty")
    course = db.create_course(topic, _profile(body.profile_id)["id"])
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])
    _start_turn(db.lesson(interview["id"]), "[event] The learner just created this course. Begin the interview.")
    return course


@app.get("/api/courses/{course_id}")
def get_course(course_id: int) -> dict:
    return _course(course_id)


@app.get("/api/courses/{course_id}/events", response_class=EventSourceResponse)
async def events(course_id: int):
    async for event in hub.subscribe(course_id):
        yield ServerSentEvent(data=event)


@app.post("/api/courses/{course_id}/mechanism")
async def choose_mechanism(course_id: int, body: Choice) -> dict:
    course = _course(course_id)
    if body.mechanism not in [r["mechanism"] for r in course["ranking"]]:
        raise HTTPException(422, "that approach is not in the plan")
    db.conn.execute("UPDATE courses SET mechanism = ? WHERE id = ?", (body.mechanism, course_id))
    hub.publish(course_id, {"type": "plan.chosen", "mechanism": body.mechanism})
    return {"mechanism": body.mechanism}


@app.post("/api/lessons/{lesson_id}/turns", status_code=202)
async def post_turn(lesson_id: int, body: Turn) -> dict:
    lesson = _lesson(lesson_id)
    _require_idle(lesson_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "message is empty")
    message = db.add_message(lesson_id, "learner", text)
    _start_turn(lesson, f"[learner] {text}")
    return message


@app.post("/api/blocks/{block_id}/answer", status_code=202)
async def answer_question(block_id: int, body: Answer) -> dict:
    block = db.block(block_id)
    if not block or block["kind"] != "question":
        raise HTTPException(404, "no such question")
    _require_idle(block["lesson_id"])
    answer = body.answer.strip()
    if not answer:
        raise HTTPException(422, "answer is empty")
    if block["data"]["answer"] is not None:
        raise HTTPException(409, "already answered")
    lesson = _lesson(block["lesson_id"])
    block = db.set_block_data(block_id, {**block["data"], "answer": answer})
    hub.publish(lesson["course_id"], {"type": "block.updated", "lesson_id": lesson["id"], "block": block})
    _start_turn(lesson, f"[learner answered] question: {block['markdown']!r} answer: {answer!r}")
    return block


@app.post("/api/courses/{course_id}/plan/accept", status_code=202)
async def accept_plan(course_id: int) -> None:
    course = _course(course_id)
    if not course["mechanism"]:
        raise HTTPException(409, "there is no plan yet")
    _require_unplaced(course)
    interview = _lesson(course["lessons"][0]["id"])
    _require_idle(interview["id"])
    _start_turn(
        interview,
        f"[event] The learner accepted the plan with mechanism {course['mechanism']} and skipped the placement check. "
        "Build the course map.",
    )


@app.post("/api/courses/{course_id}/placement")
async def start_placement(course_id: int) -> dict:
    course = _course(course_id)
    if not course["mechanism"]:
        raise HTTPException(409, "there is no plan yet")
    _require_unplaced(course)
    lesson_id = db.create_lesson(course_id, "Placement", "placement")
    view = _lesson_view(lesson_id)
    hub.publish(course_id, {"type": "lesson.created", "lesson": view})
    _start_turn(
        _lesson(lesson_id),
        f"[event] The learner accepted the plan with mechanism {course['mechanism']}. The placement check begins.",
    )
    return view


@app.post("/api/concepts/{concept_id}/lesson")
async def open_concept(concept_id: int) -> dict:
    concept = db.row("SELECT * FROM concepts WHERE id = ?", concept_id)
    if not concept:
        raise HTTPException(404, "no such concept")
    existing = db.row("SELECT id FROM lessons WHERE concept_id = ?", concept_id)
    if existing:
        return _lesson_view(existing["id"])
    lesson_id = db.create_lesson(concept["course_id"], concept["title"], "lesson", concept_id)
    view = _lesson_view(lesson_id)
    hub.publish(concept["course_id"], {"type": "lesson.created", "lesson": view})
    outline = _map_outline(concept["course_id"], concept_id)
    lesson = _lesson(lesson_id)
    strands = ""
    if lesson["mechanism"] == "leveled-course":
        counts = db.strand_counts(concept["course_id"])
        strands = "\nActivities per strand in the last 7 days: " + ", ".join(f"{k} {v}" for k, v in counts.items())
        strands += "\nSpeaking tasks: " + ("available" if speech.available() else "off on this install, use writing instead")
        if lesson["lang"]:
            strands += "\n" + tutor.vocab_brief(lesson, lesson["lang"])
    if speech.PODCASTS and speech.available():
        strands += "\nCasts (experimental): make_podcast is available when a recap or quiz-cast would serve this lesson"
    earlier = history.digest([
        _lesson_view(row["id"])
        for row in db.rows(
            "SELECT id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL AND id != ? ORDER BY id",
            concept["course_id"], lesson_id,
        )
    ])
    if earlier:
        earlier = f"\nEarlier lessons, with what the learner did in each:\n{earlier}"
    _start_turn(lesson, f"[event] The lesson begins. Course map:\n{outline}{strands}{earlier}")
    return view


@app.post("/api/blocks/{block_id}/attempt", status_code=202)
async def attempt(block_id: int, body: Answer) -> None:
    block = _challenge_block(block_id)
    answer = body.answer.strip()
    if not answer:
        raise HTTPException(422, "answer is empty")
    lesson, block = _update_block(block, {"attempts": [*block["data"]["attempts"], answer], "marks": []})
    _start_turn(lesson, f"[learner attempt] {_challenge_state(block)}\n{answer}")


@app.post("/api/blocks/{block_id}/vocabulary")
async def add_vocabulary(block_id: int, body: Word) -> dict:
    block = db.block(block_id)
    if not block or block["kind"] != "reading":
        raise HTTPException(404, "no such reading")
    gloss = next((g for g in block["data"]["glossary"] if g["word"] == body.word), None)
    if not gloss:
        raise HTTPException(404, "that word is not in the glossary")
    if body.word in block["data"]["added"]:
        raise HTTPException(409, "already in your vocabulary")
    lesson = _lesson(block["lesson_id"])
    lang = block["data"]["lang"].split("-")[0].lower()
    lemma = simplemma.lemmatize(gloss["word"], lang=lang).lower()
    card = db.add_card(
        lesson["course_id"], lesson["concept_id"], f"What does **{gloss['word']}** mean?", "open", [],
        gloss["meaning"], f"From the text “{block['data']['title']}”.", scheduled=True, vocab_due=_now(),
    )
    db.conn.execute("UPDATE cards SET lemma = ?, lang = ? WHERE id = ?", (lemma, lang, card))
    db.set_vocab(lesson["profile_id"], lang, lemma, "learning", "glossary")
    _, block = _update_block(block, {"added": [*block["data"]["added"], body.word]})
    return block


@app.post("/api/blocks/{block_id}/known")
async def know_word(block_id: int, body: Word) -> dict:
    block = db.block(block_id)
    if not block or block["kind"] != "reading":
        raise HTTPException(404, "no such reading")
    lesson = _lesson(block["lesson_id"])
    lang = block["data"]["lang"].split("-")[0].lower()
    db.set_vocab(lesson["profile_id"], lang, simplemma.lemmatize(body.word, lang=lang), "known", "learner")
    tutor.advance_tier(lesson["profile_id"], lang, db.vocab_tier(lesson["profile_id"], lang, vocab.starting_tier(lesson["level"], lang)))
    known = block["data"].get("known", [])
    _, block = _update_block(block, {"known": known if body.word in known else [*known, body.word]})
    return block


@app.post("/api/blocks/{block_id}/speak")
async def speak(block_id: int, audio: UploadFile) -> dict:
    block = _challenge_block(block_id)
    if block["kind"] != "speaking":
        raise HTTPException(404, "no such speaking task")
    data = await audio.read(CLIP_LIMIT + 1)
    if len(data) > CLIP_LIMIT:
        raise HTTPException(413, "recordings are limited to 25 MB")
    clip = speech.AUDIO / "speaking" / f"{block_id}-{len(block['data']['attempts']) + 1}.webm"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(data)
    text = block["markdown"]
    try:
        words = await speech.align(clip, text)
        heard = None
        if sum(w["score"] < WEAK_WORD for w in words) >= MISMATCH_SHARE * len(words):
            heard = (await speech.stt(clip, block["data"]["lang"]))["text"]
            words = speech.word_match(text, heard)
    except RuntimeError as e:
        log.warning("alignment failed: %s", e)
        raise HTTPException(503, str(e)) from None
    attempt = {"words": words, "heard": heard, "score": round(sum(w["score"] for w in words) / len(words), 2)}
    lesson, block = _update_block(
        block, {"attempts": [*block["data"]["attempts"], text], "scores": [*block["data"]["scores"], attempt], "marks": []}
    )
    weak = [f"{w['word']} ({w['score']:.2f})" for w in words if w["score"] < WEAK_WORD]
    _start_turn(
        lesson,
        f"[learner attempt] {_challenge_state(block)}; spoken, overall {attempt['score']:.2f}; "
        f"weak words: {', '.join(weak) or 'none'}" + (f"; the recogniser heard: {heard!r}" if heard else "")
        + f"\n{text}",
    )
    return block


@app.post("/api/blocks/{block_id}/vocab")
async def vocab_check(block_id: int, body: Known) -> dict:
    block = db.block(block_id)
    if not block or block["kind"] != "vocab":
        raise HTTPException(404, "no such vocabulary check")
    if not block["data"]["current"]:
        raise HTTPException(409, "this check is finished")
    lesson = _lesson(block["lesson_id"])
    _require_idle(lesson["id"])
    data, event = tutor.vocab_round(lesson, block["data"], body.known)
    _, block = _update_block(block, data)
    if event:
        _start_turn(lesson, event)
    return block


@app.post("/api/blocks/{block_id}/hint", status_code=202)
async def request_hint(block_id: int) -> None:
    block = _challenge_block(block_id)
    if problem := challenge.hint_blocker(block["data"]):
        raise HTTPException(409, problem)
    _start_turn(_lesson(block["lesson_id"]), f"[event] The learner asked for a hint. {_challenge_state(block)}")


@app.post("/api/blocks/{block_id}/give-up", status_code=202)
async def give_up(block_id: int) -> None:
    lesson, block = _update_block(_challenge_block(block_id), {"gave_up": True})
    _start_turn(lesson, f"[event] The learner gave up. {_challenge_state(block)}")


def _exercise(block_id: int) -> tuple[dict, Path]:
    block = db.block(block_id)
    if not block or block["kind"] != "exercise":
        raise HTTPException(404, "no such exercise")
    return block, db.workspace(_lesson(block["lesson_id"])["slug"])


def _read_files(block: dict, workspace: Path) -> list[dict]:
    files = []
    for path in block["data"]["files"]:
        target = workspace / path
        content = target.read_text(errors="replace") if target.is_file() else None
        files.append({"path": path, "absolute": str(target), "content": content})
    return files


@app.get("/api/blocks/{block_id}/files")
def exercise_files(block_id: int) -> list[dict]:
    return _read_files(*_exercise(block_id))


@app.post("/api/blocks/{block_id}/run")
async def run_exercise(block_id: int) -> dict:
    block, workspace = _exercise(block_id)
    proc = await asyncio.create_subprocess_shell(
        block["data"]["run"],
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), RUN_TIMEOUT)
        text, exit_code = output.decode(errors="replace"), proc.returncode
    except TimeoutError:
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        text, exit_code = f"stopped: still running after {RUN_TIMEOUT} s", None
    last_run = {"exit_code": exit_code, "output": text[-OUTPUT_LIMIT:]}
    _update_block(db.block(block_id), {"last_run": last_run})
    return last_run


@app.post("/api/blocks/{block_id}/check", status_code=202)
async def check_exercise(block_id: int) -> None:
    block = _challenge_block(block_id)
    _, workspace = _exercise(block_id)
    run = block["data"]["last_run"]
    summary = f"checked; last run exit code {run['exit_code']}" if run else "checked without running"
    lesson, block = _update_block(block, {"attempts": [*block["data"]["attempts"], summary]})
    files = "\n".join(
        f"--- {f['path']} ---\n{(f['content'] or '(file is missing)')[:8000]}" for f in _read_files(block, workspace)
    )
    output = f"exit code {run['exit_code']}\n{run['output'][-4000:]}" if run else "(the learner has not run it)"
    _start_turn(lesson, f"[learner attempt] exercise {_challenge_state(block)}\n{files}\n--- last run ---\n{output}")


@app.post("/api/blocks/{block_id}/quiz", status_code=202)
async def answer_quiz(block_id: int, body: QuizAnswer) -> None:
    block = db.block(block_id)
    if not block or block["kind"] != "quiz":
        raise HTTPException(404, "no such quiz")
    _require_idle(block["lesson_id"])
    if block["data"]["answer"] is not None:
        raise HTTPException(409, "already answered")
    card = db.card(block["data"]["card_id"])
    answer_id = quiz.submit(card, body.answer, body.confidence)
    given = {"answer": body.answer, "confidence": body.confidence, "answer_id": answer_id}
    said = f"question: {card['question']!r}\nlearner answer: {body.answer!r}\nconfidence: {body.confidence:.0%}"
    correct = quiz.auto_correct(card, body.answer)
    if correct is None:
        lesson, block = _update_block(block, given)
        _start_turn(lesson, f"[learner quiz answer] quiz {block_id}\n{said}\nGrade it with grade_quiz.")
        return
    result = quiz.grade(answer_id, correct)
    lesson, block = _update_block(block, {**given, **result})
    verdict = "correct" if correct else f"wrong, the right answer is {card['answer_key']!r}"
    if result["confident_miss"] and lesson["phase"] != "placement":
        verdict += "; a confident miss: re-teach it now"
    _start_turn(lesson, f"[event] Quiz {block_id} result: {verdict}\n{said}")


@app.get("/api/reviews")
def reviews(profile: int) -> list[dict]:
    return [quiz.public(c) for c in db.due_cards(profile, _now())]


@app.post("/api/cards/{card_id}/review")
def review_card(card_id: int, body: QuizAnswer) -> dict:
    card = db.card(card_id)
    if not card:
        raise HTTPException(404, "no such card")
    answer_id = quiz.submit(card, body.answer, body.confidence)
    correct = quiz.auto_correct(card, body.answer)
    if correct is None:
        # ponytail: open answers are self-graded in reviews; route them to a tutor turn if self-grading proves too lenient
        return {"answer_id": answer_id, "answer_key": card["answer_key"], "explanation": card["explanation"]}
    return {"answer_id": answer_id, **quiz.grade(answer_id, correct)}


@app.post("/api/answers/{answer_id}/grade")
def self_grade(answer_id: int, body: SelfGrade) -> dict:
    answer = db.row("SELECT correct FROM answers WHERE id = ?", answer_id)
    if not answer:
        raise HTTPException(404, "no such answer")
    if answer["correct"] is not None:
        raise HTTPException(409, "already graded")
    return quiz.grade(answer_id, body.correct)


@app.get("/api/calibration")
def calibration(profile: int) -> dict:
    return review.calibration([(a["confidence"], bool(a["correct"])) for a in db.graded_answers(profile)])


@app.post("/api/lessons/{lesson_id}/stop", status_code=204)
async def stop_turn(lesson_id: int) -> None:
    if task := _turns.get(lesson_id):
        task.cancel()


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True))
