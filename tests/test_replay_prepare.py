"""A unit of a replay, worked through as its author wrote it, is not taken offline: that would send its keys first."""
import asyncio
import json
import uuid

import pytest
from fastapi import HTTPException
from replays import import_version, publish, shelf, who  # noqa: F401

from wise_scholar import app, db
from wise_scholar.routes import lessons as lessons_routes
from wise_scholar.tools import quizzes

SECRET = "SECRET"


def _replay() -> int:
    """An imported course of a written unit with a check of each kind, and one its author did not write yet."""
    course = db.create_course(f"Bonds {uuid.uuid4().hex[:6]}", who("teacher"))["id"]
    db.set_concepts(course, [{"title": "Bonds", "concepts": ["Ionic", "Covalent"], "known": []}])
    lesson = db.create_lesson(course, "Ionic", "lesson", db.concepts(course)[0]["id"])
    items = [quizzes.SortItem(text=f"item {n}", category=("SECRET even", "SECRET odd")[n % 2]) for n in range(6)]
    replies = [
        asyncio.run(quizzes.pose_quiz(lesson, "Which loses electrons?", "choice", "Na", "SECRET metals.", ["Na", "Cl"], misconceptions={"Cl": "SECRET belief"})),
        asyncio.run(quizzes.pose_quiz(lesson, "Why does it conduct?", "open", "SECRET ions.", "SECRET charge.")),
        asyncio.run(quizzes.pose_sort(lesson, "Sort them.", ["SECRET even", "SECRET odd"], items, "SECRET parity.")),
    ]
    assert not [r for r in replies if r.startswith(("error", "refused"))]
    db.add_block(lesson, "done", "Done.", {})
    return import_version(publish(course), who())["id"]


def _lesson(course: int) -> int:
    return db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]


def _as_installed_before(lesson: int) -> None:
    """The quizzes as an install left them before it kept their keys apart: in the data, and nothing locked."""
    for r in db.rows("SELECT id FROM blocks WHERE lesson_id = ? AND kind = 'quiz'", lesson):
        db.set_block_data(r["id"], {**db.block(r["id"])["data"], **db.locked(r["id"])})
        db.conn.execute("UPDATE blocks SET locked = NULL WHERE id = ?", (r["id"],))


def _sent(lesson: int, unanswered: int = 3) -> str:
    """What the lesson view says of its unanswered checks, the categories of a sort aside, which are shown with it."""
    checks = [b["data"] for b in app._lesson_view(lesson)["blocks"] if b["kind"] == "quiz" and b["data"]["answer"] is None]
    assert len(checks) == unanswered
    return json.dumps([{k: v for k, v in d.items() if k != "categories"} for d in checks])


def _prepare(lesson: int) -> tuple[int, str]:
    try:
        asyncio.run(lessons_routes.prepare_offline(lesson))
    except HTTPException as e:
        return e.status_code, e.detail
    return 202, ""


@pytest.mark.parametrize("before", [False, True])
def test_a_replayed_unit_is_not_prepared_for_offline_and_keeps_its_keys(shelf, before):
    lesson = _lesson(_replay())
    if before:
        _as_installed_before(lesson)
    assert SECRET not in _sent(lesson)
    status, detail = _prepare(lesson)
    assert SECRET not in _sent(lesson)
    assert status == 409 and "imported unit" in detail
    assert db.row("SELECT batch, prepared_offline FROM lessons WHERE id = ?", lesson) == {"batch": 0, "prepared_offline": 0}
    assert shelf == []


def test_a_unit_its_author_did_not_write_is_taught_live_and_still_prepared(shelf):
    course = _replay()
    lesson = db.create_lesson(course, "Covalent", "lesson", db.concepts(course)[1]["id"])
    assert not app._lesson_view(lesson)["replay"]
    assert _prepare(lesson) == (202, "")
    assert app._lesson_view(lesson)["batch"] == 1 and shelf[0].startswith("[batch]")


def test_a_replayed_unit_prepared_before_leaves_offline_with_its_answers_graded_as_online(shelf):
    """Sending the batch is the one way out of offline mode the web gives, so it stays open to a unit prepared before
    the refusal; its answers are graded as an online answer would be, and the keys stop once it is sent."""
    lesson = _lesson(_replay())
    _as_installed_before(lesson)
    db.conn.execute("UPDATE lessons SET batch = 1 WHERE id = ?", (lesson,))
    assert SECRET in _sent(lesson)
    choice = next(b for b in db.blocks(lesson) if b["kind"] == "quiz" and b["data"]["kind"] == "choice")
    given = lessons_routes.BatchAnswer(block_id=choice["id"], answer="Cl", confidence=0.9)
    asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given])))
    assert db.lesson(lesson)["batch"] == 0 and SECRET not in _sent(lesson, unanswered=2)
    graded = db.block(choice["id"])["data"]
    assert (graded["answer"], graded["correct"]) == ("Cl", False)
