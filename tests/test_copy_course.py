"""What db.copy_course writes: the columns a copy takes along, and no id of the original in its block data."""
import asyncio
import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, db  # noqa: E402
from wise_scholar.routes import courses as courses_routes  # noqa: E402
from wise_scholar.tools import quizzes as quiz_tools  # noqa: E402


def _prepared(name: str, topic: str) -> tuple[int, int]:
    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, 'teacher')", (name,)).lastrowid
    course = db.create_course(topic, who)["id"]
    db.set_concepts(course, [{"title": "Gears", "concepts": ["Ratios", "Trains"], "known": []}])
    return course, db.create_lesson(course, "Ratios", "lesson", db.concepts(course)[0]["id"])


def _duplicate(course: int, tmp_path, monkeypatch) -> int:
    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources")
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    return courses_routes.duplicate_course(course)["id"]


def test_a_duplicated_prepared_course_keeps_its_unwritten_units(tmp_path, monkeypatch):
    course, _ = _prepared("Unwritten copier", "Gears unwritten")
    later = db.concepts(course)[1]["id"]
    db.conn.execute("UPDATE concepts SET unwritten = 1 WHERE id = ?", (later,))
    copy = _duplicate(course, tmp_path, monkeypatch)
    assert [c["unwritten"] for c in db.concepts(copy)] == [0, 1]


def test_a_copied_replay_teaches_its_unwritten_unit_live():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Unwritten reader')").lastrowid
    course = db.create_course("Gears replayed", who)["id"]
    db.set_concepts(course, [{"title": "Gears", "concepts": ["Ratios", "Trains"], "known": []}])
    db.conn.execute("UPDATE courses SET mode = 'replay' WHERE id = ?", (course,))
    ratios, trains = db.concepts(course)[:2]
    db.conn.execute("UPDATE concepts SET unwritten = 1 WHERE id = ?", (trains["id"],))
    for c in (ratios, trains):
        db.create_lesson(course, c["title"], "lesson", c["id"])
    copy = db.copy_course(course, "Gears replayed (2)")["id"]

    def replayed(course_id: int) -> dict[str, bool]:
        return {r["title"]: app._replayed(db.lesson(r["id"])) for r in db.rows("SELECT id, title FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL", course_id)}

    assert replayed(course) == {"Ratios": True, "Trains": False}
    assert replayed(copy) == replayed(course)


def test_a_duplicated_quiz_card_keeps_the_beliefs_behind_its_wrong_options(tmp_path, monkeypatch):
    course, lesson = _prepared("Belief copier", "Gears believed")
    asyncio.run(quiz_tools.pose_quiz(
        lesson, "Driver 10 teeth, driven 20: ratio?", "choice", "2", "Teeth over teeth.", options=["2", "0.5"],
        misconceptions={"0.5": "the driver goes on top"},
    ))
    copy = _duplicate(course, tmp_path, monkeypatch)
    card = db.row("SELECT id FROM cards WHERE course_id = ?", copy)["id"]
    assert db.card(card)["misconceptions"] == {"0.5": "the driver goes on top"}
