import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal

from .. import app as core
from .. import book, challenge, db, handout, obsidian, tutor
from ..tools import lesson_flow as flow_tools
from .courses import warmup
from ..app import QuizAnswer, _lesson, _record_answer, _turns, _unanswered_quiz, _untrusted, app, log


class Turn(BaseModel):
    text: str


class BatchAnswer(QuizAnswer):
    block_id: int
    self_correct: bool | None = None


class Batch(BaseModel):
    answers: list[BatchAnswer] = Field(max_length=40)


TEST_OUT = {
    "step": (
        "[event] The learner tests out of the current outline step ({step}). Before teaching it, pose its checks: two "
        "or three pose_quiz cards, choice where it fits, one per turn, covering what the step teaches. If every "
        "answer is right at 70% confidence or more, call step_done, say in one sentence that the step is skipped, "
        "and go on with the next step. At the first miss, teach the step starting from what that miss shows."
    ),
    "unit": (
        "[event] The learner tests out of the whole unit. Before teaching more, pose checks across what the unit "
        "covers: three to five pose_quiz cards, choice where it fits, one per turn, each on a different idea. If "
        "every answer is right at 70% confidence or more, call finish_lesson saying the unit was tested out. At the "
        "first miss, teach from the step that miss belongs to and go on with the unit from there."
    ),
}


class TestOut(BaseModel):
    scope: Literal["step", "unit"]


@app.post("/api/lessons/{lesson_id}/testout", status_code=202)
async def test_out(lesson_id: int, body: TestOut) -> None:
    """In speed mode, a learner who thinks they know a step or the whole unit answers its checks before its teaching."""
    lesson = _lesson(lesson_id)
    if lesson["pace"] != "speed" or lesson["mode"] == "teacher" or lesson["phase"] != "lesson" or lesson["concept_id"] is None:
        raise HTTPException(409, "testing out is for a unit of a course in speed mode")
    if any(b["kind"] == "done" for b in db.blocks(lesson_id)):
        raise HTTPException(409, "this lesson is finished")
    if tutor.pretest_blocker(lesson):
        raise HTTPException(409, "try the unit's opening first")
    core._require_idle(lesson_id)
    outline = flow_tools._outline(lesson_id)
    step = ""
    if body.scope == "step":
        if not outline or outline["data"]["at"] >= len(outline["data"]["steps"]):
            raise HTTPException(409, "this unit has no step left to test out of")
        step = f"step {outline['data']['at'] + 1}: {outline['data']['steps'][outline['data']['at']]!r}"
    core._start_turn(lesson, TEST_OUT[body.scope].format(step=step))


@app.post("/api/lessons/{lesson_id}/turns", status_code=202)
async def post_turn(lesson_id: int, body: Turn) -> dict:
    lesson = _lesson(lesson_id)
    core._require_idle(lesson_id)
    if not lesson["started"]:
        raise HTTPException(409, "start the interview first")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "message is empty")
    message = db.add_message(lesson_id, "learner", text)
    line = f"[learner] {_untrusted(text)}"
    if lesson["phase"] == "placement" and (held := core._held_answers(lesson_id))[0]:
        # a batch whose turn failed reaches the tutor with the learner's next message
        core._start_turn(lesson, f"{held[0]}\n\n{line}", then=held[1])
    else:
        core._start_turn(lesson, line)
    return message


BATCH_PREPARE = (
    "[batch] The learner takes this unit offline: they read and answer it without you, and the answers come back "
    "together as one [batch results] event. In this turn, write the rest of the unit in lesson order, following its "
    "outline (set one first if it has none), without "
    "waiting for answers: the opening (pose_quiz with pretest set) when the lesson has none yet, then the "
    "explanations and worked examples with add_block, figures and readings where they help, and the quick checks "
    "with pose_quiz or pose_sort, each after the part it checks. Use no other card: challenges, exercises, "
    "questions and the rest need you present. Every check carries its key and an explanation that teaches the "
    "point, because the learner sees them right after answering; a choice explanation says why each wrong option "
    "is wrong. Do not call finish_lesson. End with one chat sentence saying the unit is ready to take offline."
)
BATCH_RESULTS = (
    "Grade every open answer above with grade_quiz: the learner saw the model answer and graded themselves; keep "
    "their grade when the substance holds and overrule it when it does not, saying why in the feedback. Then "
    "re-teach what the misses show in one short add_block, mark with step_done the outline steps the answers "
    "completed, and the lesson goes on as usual. Checks left unanswered "
    "stay where they are and the learner answers them online; do not pose them again. Finish the lesson once its "
    "checks are answered."
)


RECAP_GAP = timedelta(days=3)
RECAP = (
    "[event] The learner is back after {days} days away from this unit. Before going on, add one short add_block "
    "headed 'Where you were': what the unit has covered so far, the last thing the learner worked out, and the "
    "outline step that comes next. Then pose one recall check with pose_quiz, a choice where it fits, on the main idea of the last "
    "sitting, and end the turn; after its result pose a second one on another idea from before the break, then go "
    "on with the unit where it stopped. The two checks count toward the lesson's quick checks."
)


def _not_resumable(lesson: dict, last: dict | None) -> bool:
    return bool(
        not last or lesson["phase"] != "lesson" or lesson["concept_id"] is None or lesson["mode"] == "teacher"
        or lesson["batch"] or lesson["id"] in _turns
        # the learner's last message never got its answer (a failed turn); answering it comes first
        or last["role"] == "learner"
        # nothing worked out yet to recall, and the server holds explanations until the opening is tried
        or tutor.pretest_blocker(lesson)
    )


def _card_pending(blocks: list[dict]) -> bool:
    return (
        any(b["kind"] == "done" for b in blocks)
        # an open card is where the learner picks up; a recap on top of it would leave two things waiting
        or any(b["kind"] == "quiz" and b["data"]["answer"] is None for b in blocks)
        or any(b["kind"] in challenge.KINDS and challenge.is_open(b["data"]) for b in blocks)
    )


@app.post("/api/lessons/{lesson_id}/resume")
async def resume_lesson(lesson_id: int) -> dict:
    """A learner back at an unfinished unit after RECAP_GAP or more gets a recap and two recall checks first."""
    lesson = _lesson(lesson_id)
    last = db.row("SELECT created, role FROM messages WHERE lesson_id = ? ORDER BY id DESC LIMIT 1", lesson_id)
    blocks = db.blocks(lesson_id)
    if _not_resumable(lesson, last) or _card_pending(blocks):
        return {"recap": False}
    away = datetime.now(timezone.utc) - datetime.fromisoformat(last["created"]).replace(tzinfo=timezone.utc)
    # the sitting's warm-up comes first; the recap starts when the learner is back from it
    if away < RECAP_GAP or warmup(lesson["course_id"])["due"]:
        return {"recap": False}
    core._start_turn(lesson, RECAP.format(days=away.days))
    return {"recap": True}


@app.post("/api/lessons/{lesson_id}/prepare", status_code=202)
async def prepare_offline(lesson_id: int) -> None:
    """The tutor writes the rest of a unit at once, its cards carrying their keys, for answering offline."""
    lesson = _lesson(lesson_id)
    if lesson["mode"] == "teacher" or lesson["phase"] != "lesson" or lesson["concept_id"] is None:
        raise HTTPException(409, "only a unit of a learner's course is taken offline")
    if lesson["batch"]:
        raise HTTPException(409, "this lesson is already prepared for offline")
    if any(b["kind"] == "done" for b in db.blocks(lesson_id)):
        raise HTTPException(409, "this lesson is finished")
    core._require_idle(lesson_id)
    db.conn.execute("UPDATE lessons SET batch = 1 WHERE id = ?", (lesson_id,))
    core._start_turn(db.lesson(lesson_id), BATCH_PREPARE,
                     then=lambda: db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE id = ?", (lesson_id,)))


def _checked_batch(lesson_id: int, body: Batch) -> list[tuple[dict, dict, BatchAnswer]]:
    if len({g.block_id for g in body.answers}) != len(body.answers):
        raise HTTPException(422, "a quiz is answered once")
    # Every answer is checked before any is stored, so a refused batch leaves nothing half-recorded.
    checked = []
    for given in body.answers:
        block, card = _unanswered_quiz(given.block_id)
        if block["lesson_id"] != lesson_id:
            raise HTTPException(404, "no such quiz in this lesson")
        if card["kind"] == "open" and given.self_correct is None:
            raise HTTPException(422, "an open answer carries the learner's own grade")
        checked.append((block, card, given))
    return checked


def _record_batch(lesson_id: int, checked: list[tuple[dict, dict, BatchAnswer]]) -> list[str]:
    lines = []
    db.conn.execute("BEGIN")
    try:
        for block, card, given in checked:
            if card["kind"] == "open":
                _, _, said = _record_answer(block, card, given.answer, given.confidence, {"self_correct": given.self_correct})
                lines.append(f"quiz {block['id']}, open, self-graded {'right' if given.self_correct else 'wrong'}\n{said}")
            else:
                _, verdict, said = _record_answer(block, card, given.answer, given.confidence)
                lines.append(f"quiz {block['id']}: {verdict}\n{said}")
        db.conn.execute("UPDATE lessons SET batch = 0 WHERE id = ?", (lesson_id,))
        db.conn.execute("COMMIT")
    except BaseException:
        db.conn.execute("ROLLBACK")
        raise
    return lines


@app.post("/api/lessons/{lesson_id}/batch", status_code=202)
async def send_batch(lesson_id: int, body: Batch) -> None:
    """The answers given offline, in the order given: the server grades what it can, open answers keep the learner's
    own grade until the tutor confirms it, and one tutor turn takes them all."""
    lesson = _lesson(lesson_id)
    if not lesson["batch"]:
        raise HTTPException(409, "this lesson is not prepared for offline")
    core._require_idle(lesson_id)
    checked = _checked_batch(lesson_id, body)
    lines = _record_batch(lesson_id, checked)
    left = [b["id"] for b in db.blocks(lesson_id) if b["kind"] == "quiz" and b["data"]["answer"] is None]
    if left:
        lines.append("left unanswered: " + ", ".join(f"quiz {i}" for i in left))
    core._start_turn(db.lesson(lesson_id), "[batch results]\n" + "\n\n".join(lines or ["no answers"]) + "\n\n" + BATCH_RESULTS)


Version = Literal["student", "teacher"]


@app.get("/api/lessons/{lesson_id}")
def get_lesson(lesson_id: int) -> dict:
    """The lesson's heading only; its content comes with the course."""
    lesson = _lesson(lesson_id)
    return {k: lesson[k] for k in ("id", "title", "phase", "concept_id", "course_id", "topic", "mode")}


@app.get("/api/lessons/{lesson_id}/handout.md")
async def lesson_handout(lesson_id: int, version: Version = "student") -> Response:
    """A unit's lesson plan as Markdown: the teacher's copy, or the students' copy without solutions."""
    lesson = _lesson(lesson_id)
    if lesson["mode"] != "teacher" or lesson["concept_id"] is None:
        raise HTTPException(409, "hand-outs come from a unit of a prepared course")
    boards = await obsidian.board_pages(obsidian.board_blocks(lesson["course_id"], lesson_id))
    text = await asyncio.to_thread(handout.markdown, lesson_id, solutions=version == "teacher", boards=boards)
    name = f"{lesson['slug']}-{lesson_id}-{version}.md"
    return Response(text, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/lessons/{lesson_id}/handout.pdf")
async def lesson_handout_pdf(lesson_id: int, version: Version = "student", theme: Literal["light", "dark"] = "light") -> Response:
    lesson = _lesson(lesson_id)
    if lesson["mode"] != "teacher" or lesson["concept_id"] is None:
        raise HTTPException(409, "hand-outs come from a unit of a prepared course")
    if not book.available():
        raise HTTPException(503, "PDF export is not installed; run make pdf")
    try:
        pdf = await book.render(lesson["course_id"], lesson["profile_id"], theme, path=f"#/lesson/{lesson_id}/handout/{version}")
    except book.NoBrowser:
        raise HTTPException(503, "PDF export has no browser to print with; run make pdf") from None
    except TimeoutError as e:
        log.warning("hand-out export timed out: %s", e)
        raise HTTPException(504, "the book did not finish drawing") from None
    name = f"{lesson['slug']}-{lesson_id}-{version}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/lessons/{lesson_id}/stop", status_code=204)
async def stop_turn(lesson_id: int) -> None:
    if task := _turns.get(lesson_id):
        task.cancel()
