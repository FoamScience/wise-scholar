"""A replay's placement from its cards leaves out a teach-back's hidden card, so its key points stay hidden."""
import asyncio
import json
import uuid

import pytest
from replays import import_version as _import, publish as _publish, shelf, who as _who  # noqa: F401

from wise_scholar import app, db
from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes
from wise_scholar.tools import practice, quizzes

POINTS = "PLACEKEY a surface needs two ends"


def _authored(*quizzed: str) -> int:
    """A course whose finished unit poses a teach-back, then a quiz of each kind given."""
    course = db.create_course(f"Sweeps {uuid.uuid4().hex[:6]}", _who())["id"]
    db.set_concepts(course, [{"title": "Sweeps", "concepts": ["Rails", "Caps"], "known": []}])
    lesson = db.create_lesson(course, "Rails", "lesson", db.concepts(course)[0]["id"])
    assert asyncio.run(practice.pose_teachback(lesson, "Explain why a sweep needs a rail.", POINTS)).startswith("shown")
    for kind in quizzed:
        options = ["A rail", "A cap"] if kind == "choice" else []
        assert asyncio.run(quizzes.pose_quiz(lesson, f"What guides a sweep ({kind})?", kind, "A rail", "The rail guides it.",
                                             options=options)).startswith("shown")
    db.add_block(lesson, "done", "You can sweep.", {})
    return course


def _replay(course: int) -> int:
    return _import(_publish(course), _who())["id"]


def _as_installed_before(course: int) -> None:
    """The teach-back as an install left it before it got its card: the card's key in the data, and no card."""
    [block] = [b for b in db.blocks(db.row("SELECT id FROM lessons WHERE course_id = ? AND title = 'Rails'", course)["id"])
               if b["data"].get("teachback")]
    data = {k: v for k, v in block["data"].items() if k != "card_id"}
    db.set_block_data(block["id"], {**data, "card": db.row("SELECT key FROM cards WHERE id = ?", block["data"]["card_id"])["key"]})


@pytest.mark.parametrize("before", [False, True])
def test_a_unit_whose_only_card_is_its_teachbacks_has_no_placement_question(shelf, before):
    replay = _replay(_authored())
    if before:
        _as_installed_before(replay)
    with pytest.raises(app.HTTPException, match="cards left"):
        courses_routes.card_placement(replay)


@pytest.mark.parametrize("kind", ["open", "choice"])
@pytest.mark.parametrize("before", [False, True])
def test_a_unit_is_placed_with_its_quiz_and_its_key_points_stay_hidden(shelf, kind, before):
    replay = _replay(_authored(kind))
    if before:
        _as_installed_before(replay)
    placement = courses_routes.card_placement(replay)
    [quiz] = placement["blocks"]
    asyncio.run(blocks_routes.answer_quiz(quiz["id"], app.QuizAnswer(answer="A rail", confidence=0.8)))
    assert POINTS not in json.dumps(app._lesson_view(placement["id"]), default=str)
    assert quiz["markdown"] == f"What guides a sweep ({kind})?"
