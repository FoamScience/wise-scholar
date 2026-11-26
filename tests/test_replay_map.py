"""The map's units say whether they are placed out as the server counts a course finished, so a known unit of a replay
whose imported lesson its reader never touched shows done."""
from test_replay_finish import _answer, _finish, _know, _profile, _replay, client  # noqa: F401

from wise_scholar import db


def _placed(client, course: int) -> dict[str, bool]:
    return {c["title"]: c["placed_out"] for c in client.get(f"/api/courses/{course}").json()["concepts"]}


def test_a_known_unit_of_a_replay_its_reader_never_touched_is_placed_out(client):
    course, units = _replay(client, "Pulleys", "Tension", "Wear", "Later")
    _answer(client, units["Tension"])
    _know(course, "Pulleys", "Tension", "Later")
    assert _placed(client, course) == {"Pulleys": True, "Tension": False, "Wear": False, "Later": True}
    _finish(units["Tension"], "2026-10-12 10:00:00")
    _finish(units["Wear"], "2026-10-13 10:00:00")
    assert client.get(f"/api/courses/{course}").json()["recap"]["finished"] == "2026-10-13 10:00:00"


def test_a_known_unit_of_an_ordinary_course_is_placed_out_until_it_is_opened(client):
    course = db.create_course("Belts", _profile("map learner"))["id"]
    db.set_concepts(course, [{"title": "Drives", "concepts": ["Pulleys", "Tension", "Wear"], "known": ["Pulleys", "Tension"]}])
    opened = db.concepts(course)[0]["id"]
    db.add_block(db.create_lesson(course, "Pulleys", "lesson", opened), "prose", "On pulleys.", {"imported": True})
    assert _placed(client, course) == {"Pulleys": False, "Tension": True, "Wear": False}
