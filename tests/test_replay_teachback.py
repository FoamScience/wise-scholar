"""A teach-back's grade counts toward mastery in a replay, a fork and a copy as it does in its author's course."""
import asyncio
import io
import json
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from replays import import_version as _import, publish as _publish, shelf, who as _who  # noqa: F401

from wise_scholar import app, bundle, db
from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes, sharing as sharing_routes
from wise_scholar.tools import practice, quizzes

PROMPT = "Explain in your own words why a loft needs two wires."
POINTS = "KEYPOINT a surface needs two ends"


def _authored(mode: str = "learner") -> int:
    """A course of one finished unit with a teach-back and a quiz, posed with the tools its tutor has."""
    course = db.create_course(f"Lofts {uuid.uuid4().hex[:6]}", _who(mode))["id"]
    db.conn.execute("UPDATE courses SET mode = ? WHERE id = ?", (mode, course))
    db.set_concepts(course, [{"title": "Lofts", "concepts": ["Wires", "Faces"], "known": []}])
    lesson = db.create_lesson(course, "Wires", "lesson", db.concepts(course)[0]["id"])
    assert asyncio.run(practice.pose_teachback(lesson, PROMPT, POINTS)).startswith("shown")
    db.add_block(lesson, "done", "You can loft.", {})
    return course


def _replay(course: int) -> int:
    return _import(_publish(course), _who())["id"]


def _teachback(course: int) -> dict:
    [found] = db.rows(
        "SELECT b.id FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND json_extract(b.data, '$.teachback')", course,
    )
    return db.block(found["id"])


def _try(course: int, text: str = "A surface runs from one wire to the other.") -> int:
    block = _teachback(course)["id"]
    asyncio.run(blocks_routes.attempt(block, blocks_routes.Answer(answer=text)))
    return block


def _solve(course: int) -> None:
    assert asyncio.run(practice.mark_solved(_try(course))) == "marked"


def _finish(course: int) -> None:
    """The reader solves the teach-back, and the turn that marks it ends."""
    _solve(course)
    app._replay_progress(db.lesson(_teachback(course)["lesson_id"]))


def _fail(course: int) -> None:
    _try(course, "No idea.")
    assert asyncio.run(practice.reveal(_try(course, "Still no idea."), "A model explanation.")).startswith("shown")


def _mastery(course: int) -> list:
    return [c["mastery"] for c in db.concept_view(course)]


def _as_installed_before(course: int) -> None:
    """The teach-back as an install left it before it got its card: the card's key in the data, and no card."""
    block = _teachback(course)
    data = {k: v for k, v in block["data"].items() if k != "card_id"}
    db.set_block_data(block["id"], {**data, "card": db.row("SELECT key FROM cards WHERE course_id = ? AND question = ?", course, PROMPT)["key"]})


@pytest.mark.parametrize("outcome, mastery", [(_solve, 1.0), (_fail, 0.0)])
@pytest.mark.parametrize("mode", ["learner", "teacher"])
def test_a_readers_teachback_counts_toward_mastery_as_its_authors(shelf, mode, outcome, mastery):
    course = _authored(mode)
    replay = _replay(course)
    assert _mastery(replay) == [None, None]
    outcome(replay)
    assert _mastery(replay) == [mastery, None]
    if mode == "learner":
        outcome(course)
        assert _mastery(course) == _mastery(replay)


def test_the_grade_lands_on_the_replays_own_hidden_card(shelf):
    course = _authored()
    replay = _replay(course)
    _solve(replay)
    card = db.card(_teachback(replay)["data"]["card_id"])
    assert (card["course_id"], card["answer_key"], card["scheduled"], card["due"]) == (replay, POINTS, 0, None)
    [answer] = db.rows("SELECT * FROM answers WHERE card_id = ?", card["id"])
    assert (answer["correct"], answer["answer"]) == (1, "A surface runs from one wire to the other.")
    assert "card" not in _teachback(replay)["data"]
    assert _mastery(course) == [None, None]


def test_the_key_points_do_not_reach_the_reader(shelf):
    from wise_scholar import obsidian
    from wise_scholar.routes import learner

    replay = _replay(_authored())
    profile = db.course(replay)["profile_id"]
    lesson = _teachback(replay)["lesson_id"]
    seen = lambda: json.dumps([app._lesson_view(lesson), app._course(replay), learner.reviews(profile), learner.today(profile)], default=str)  # noqa: E731
    assert PROMPT in seen() and POINTS not in seen()
    _try(replay)
    assert POINTS not in seen()
    _solve(replay)
    assert POINTS not in seen()
    with zipfile.ZipFile(io.BytesIO(obsidian.export(replay))) as notes:
        assert all(POINTS.encode() not in notes.read(n) for n in notes.namelist())


def _shipped(version: str) -> dict:
    [data] = [b.data for x in bundle.stored(app.VERSIONS, version).lessons for b in x.blocks if b.kind == "challenge"]
    return data


@pytest.mark.parametrize("before", [False, True])
def test_a_fork_ships_the_teachback_as_it_came_and_its_readers_counts(shelf, before):
    first = _publish(_authored())
    fork = _import(first, _who())["id"]
    if before:
        _as_installed_before(fork)
    _finish(fork)
    second = _publish(fork)
    assert _shipped(second) == {**_shipped(first), "imported": True}
    replay = _import(second, _who())["id"]
    _solve(replay)
    assert _mastery(replay) == [1.0, None]


def test_an_upgrade_keeps_a_kept_units_grade_and_a_restarted_units_teachback_counts(shelf):
    course = _authored()
    reader = _who()
    replay = _import(_publish(course), reader)["id"]
    _solve(replay)
    card = _teachback(replay)["data"]["card_id"]

    other = db.create_lesson(course, "Faces", "lesson", db.concepts(course)[1]["id"])
    db.add_block(other, "prose", "A face.")
    db.add_block(other, "done", "Done.", {})
    second = _publish(course)
    _import(second, reader)
    assert len(sharing_routes.upgrade_course(replay, sharing_routes.Upgrade(hash=second))["upgraded"]["kept"]) == 1
    assert _mastery(replay) == [1.0, None] and _teachback(replay)["data"]["card_id"] == card

    db.add_block(db.row("SELECT id FROM lessons WHERE course_id = ? AND title = 'Wires'", course)["id"], "prose", "More on wires.")
    third = _publish(course)
    _import(third, reader)
    sharing_routes.upgrade_course(replay, sharing_routes.Upgrade(hash=third))
    assert _mastery(replay)[0] is None
    assert db.card(_teachback(replay)["data"]["card_id"])["course_id"] == replay
    _solve(replay)
    assert _mastery(replay)[0] == 1.0


@pytest.mark.parametrize("before", [False, True])
def test_a_copy_of_a_replay_counts_its_own_teachback(shelf, before):
    replay = _replay(_authored())
    if before:
        _as_installed_before(replay)
    copy = db.copy_course(replay, "A copied replay")["id"]
    _solve(copy)
    assert _mastery(copy) == [1.0, None] and _mastery(replay) == [None, None]


def test_a_duplicated_prepared_course_ships_its_own_teachback(shelf):
    copy = courses_routes.duplicate_course(_authored("teacher"))["id"]
    assert db.card(_teachback(copy)["data"]["card_id"])["course_id"] == copy
    replay = _replay(copy)
    _solve(replay)
    assert _mastery(replay) == [1.0, None]


@pytest.mark.parametrize("outcome, mastery", [(_solve, 1.0), (_fail, 0.0)])
def test_a_teachback_installed_before_it_got_its_card_counts_too(shelf, outcome, mastery):
    replay = _replay(_authored())
    _as_installed_before(replay)
    outcome(replay)
    assert _mastery(replay) == [mastery, None]


def _quizzed() -> int:
    """The authored course with a scheduled open quiz, whose card a made-up bundle may name."""
    course = _authored()
    lesson = _teachback(course)["lesson_id"]
    assert asyncio.run(quizzes.pose_quiz(lesson, "Why two wires?", "open", "Two ends.", "A surface joins them.")).startswith("shown")
    return course


@pytest.mark.parametrize("named", ["the quiz", None, "0" * 32, ["list"], 7])
def test_a_bundle_whose_teachback_names_no_hidden_card_is_refused_as_one_whose_quiz_does(shelf, named):
    manifest, assets, _ = bundle.build(_quizzed(), notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=app.SOURCES)
    quiz_key = next(c["key"] for c in manifest["cards"] if c["scheduled"])
    for b in (b for x in manifest["lessons"] for b in x["blocks"] if (b["data"] or {}).get("teachback")):
        b["data"]["card"] = quiz_key if named == "the quiz" else named
    version, data = bundle.pack(manifest, assets)
    (app.VERSIONS / f"{version}.zip").parent.mkdir(parents=True, exist_ok=True)
    (app.VERSIONS / f"{version}.zip").write_bytes(data)
    reader = _who()
    with pytest.raises(HTTPException) as refused:
        _import(version, reader)
    assert refused.value.status_code == 422
    assert not db.rows("SELECT 1 FROM courses WHERE profile_id = ?", reader)


@pytest.mark.parametrize("named", ["0" * 32, ["list"], 7])
def test_an_old_install_naming_no_hidden_card_stays_ungraded(shelf, named):
    replay = _replay(_authored())
    _as_installed_before(replay)
    block = _teachback(replay)
    db.set_block_data(block["id"], {**block["data"], "card": named})
    _solve(replay)
    assert _mastery(replay) == [None, None]
