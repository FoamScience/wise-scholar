"""What db.copy_course writes: the columns a copy takes along, and no id of the original in its block data."""
import asyncio
import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, db, quiz, recap  # noqa: E402
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


def _copied_lesson(copy: int, phase: str) -> dict:
    return db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = ?", copy, phase)["id"])


def test_a_copied_revisit_check_puts_no_mistake_of_the_original_right():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Revisit copier')").lastrowid
    course = db.create_course("Gears revisited", who)["id"]
    db.set_concepts(course, [{"title": "Gears", "concepts": ["Ratios"], "known": []}])
    card = db.add_card(course, db.concepts(course)[0]["id"], "Which ratio?", "choice", ["a", "b"], "a", "", scheduled=True)
    error = db.add_error(who, course, "quiz", "Which ratio?", "b", "a", "", card_id=card)
    claim = db.conn.execute("INSERT INTO claims (profile_id, text) VALUES (?, 'A ratio is teeth over teeth.')", (who,)).lastrowid
    revisit = db.create_lesson(course, "Revisit 1", "revisit")
    items = [{"kind": "mistake", "id": error, "prompt": "Which ratio?"}, {"kind": "shaky", "id": claim, "text": "A ratio is teeth over teeth."}]
    db.add_block(revisit, "outline", "", recap.revisit_outline(items))
    for item, question in enumerate(("Which ratio now?", "Teeth over teeth?"), 1):
        assert asyncio.run(quiz_tools.pose_quiz(revisit, question, "choice", "a", "", ["a", "b"], item=item)).startswith("shown as quiz")
    assert [b["data"].get("revisit_error") or b["data"].get("revisit_claim") for b in db.blocks(revisit)[1:]] == [error, claim]

    copy = db.copy_course(course, "Gears revisited (2)")["id"]
    checks = [b for b in db.blocks(_copied_lesson(copy, "revisit")["id"]) if b["kind"] == "quiz"]
    for check in checks:
        quiz.grade(quiz.submit(db.card(check["data"]["card_id"]), "a", 0.9), True)
    assert db.row("SELECT resolved FROM errors WHERE id = ?", error)["resolved"] == 0
    assert not [k for b in checks for k in b["data"] if k.startswith("revisit_")]
    original = db.blocks(revisit)[1]
    quiz.grade(quiz.submit(db.card(original["data"]["card_id"]), "a", 0.9), True)
    assert db.row("SELECT resolved FROM errors WHERE id = ?", error)["resolved"] == 1


def test_a_copied_placement_from_cards_marks_the_copys_own_units():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Placement copier')").lastrowid
    course = db.create_course("Gears placed", who)["id"]
    db.set_concepts(course, [{"title": "Gears", "concepts": ["Ratios", "Trains"], "known": []}])
    db.conn.execute("UPDATE courses SET mode = 'replay' WHERE id = ?", (course,))
    units = [c["id"] for c in db.concepts(course) if c["kind"] == "concept"]
    placement = db.create_lesson(course, "Placement", "placement")
    for unit in units:
        card = db.add_card(course, unit, f"Unit {unit}?", "choice", ["a", "b"], "a", "", scheduled=True)
        courses_routes._add_placement_quiz(placement, {"id": card, "kind": "choice", "options": '["a", "b"]', "answer_key": "a", "question": "?", "concept_id": unit})
    gone = db.blocks(placement)[1]
    db.set_block_data(gone["id"], {**gone["data"], "unit": 10**9})

    copy = db.copy_course(course, "Gears placed (2)")["id"]
    own = [c["id"] for c in db.concepts(copy) if c["kind"] == "concept"]
    lesson = _copied_lesson(copy, "placement")
    for b in db.blocks(lesson["id"]):
        db.set_block_data(b["id"], {**b["data"], "correct": True})
    app._placed_from_cards(lesson, db.blocks(lesson["id"]))
    known = {r["id"] for r in db.rows("SELECT id FROM concepts WHERE known = 1")}
    assert [u in known for u in units + own] == [False, False, True, False]
    assert [b["data"].get("unit") for b in db.blocks(lesson["id"])] == [own[0], None]
