import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from wise_scholar import app, challenge, cleanup, course_files, db, recap
from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes, sharing as sharing_routes
from wise_scholar.tools import course_plan, language as language_tools, lesson_flow

NOW = "2026-11-25T12:00:00+00:00"


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module, name in ((db, "WORKSPACE"), (app, "SOURCES"), (app, "VERSIONS")):
        monkeypatch.setattr(module, name, tmp_path / name.lower())
    monkeypatch.setattr(app, "_start_turn", lambda *a, **k: None)
    monkeypatch.setattr(sharing_routes, "_start_recap", lambda course: None)
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]
    yield TestClient(app.app, base_url="http://127.0.0.1:8321")
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    for table in ("vocab_knowledge", "vocab_tiers"):
        db.conn.execute(f"DELETE FROM {table} WHERE profile_id > ?", (last,))
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _profile(who: str) -> int:
    return db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Replay finish {who} {uuid4()}",)).lastrowid


def _written(course: int, title: str, concept: int) -> None:
    lesson = db.create_lesson(course, title, "lesson", concept)
    card = db.add_card(course, concept, f"Which {title}?", "choice", ["a", "b"], "a", "As written.", True)
    db.add_block(lesson, "prose", f"On {title}.")
    db.add_block(lesson, "quiz", f"Which {title}?", {"card_id": card, "kind": "choice", "options": ["a", "b"], "answer": None, "pretest": False})
    db.add_block(lesson, "challenge", f"Try {title}.", challenge.new())
    db.add_block(lesson, "done", "", {})


def _worked_through(course: int, concept: int) -> None:
    """The cards a reader works on besides checks: an outline, a word check, a reading and an exercise, as their author
    left them."""
    lesson = _lesson(concept)
    steps = ["Belt length", "Wrap angle"]
    db.add_block(lesson, "outline", db.outline_text(steps, 2), {"steps": steps, "at": 2, "added": None, "cards": 6})
    asyncio.run(language_tools.pose_vocab_check(lesson, "de"))
    db.add_block(lesson, "reading", "Der Riemen.", {"title": "Riemen", "lang": "de-DE", "added": [], "targets": [], "known": [],
                                                     "glossary": [{"word": "Riemen", "meaning": "belt"}]})
    course_files.write_text(db.workspace(db.course(course)["slug"]), "belt/length.py", "# the belt's length")
    db.add_block(lesson, "exercise", "Work out the belt's length.", {"files": ["belt/length.py"], "run": "python belt/length.py", **challenge.new()})


def _replay(client, *units: str, worked: str | None = None) -> tuple[int, dict[str, int]]:
    """A replay imported by a reader, and its units by title; the author wrote every unit but one called Later, and
    worked through the cards of the one called worked."""
    author, reader = _profile("author"), _profile("reader")
    course = db.create_course("Belts", author)["id"]
    for n, title in enumerate(units, start=1):
        db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Drives', ?, ?)", (course, title, n))
    for c in db.concepts(course):
        if c["title"] != "Later":
            _written(course, c["title"], c["id"])
        if c["title"] == worked:
            _worked_through(course, c["id"])
    version = client.post(f"/api/courses/{course}/versions", json={}).json()["hash"]
    bundle = client.get(f"/api/versions/{version}/bundle").content
    mine = client.post(f"/api/import?profile={reader}", files={"file": ("belts.zip", bundle)}).json()["id"]
    return mine, {c["title"]: c["id"] for c in db.concepts(mine)}


def _know(course: int, *titles: str) -> None:
    asyncio.run(course_plan.set_known(course, list(titles), []))


def _lesson(concept: int) -> int:
    return db.row("SELECT id FROM lessons WHERE concept_id = ?", concept)["id"]


def _block(concept: int, kind: str) -> dict:
    return next(b for b in db.blocks(_lesson(concept)) if b["kind"] == kind)


def _finish(concept: int, at: str) -> None:
    db.conn.execute("INSERT INTO blocks (lesson_id, kind, markdown, data, created) VALUES (?, 'done', '', '{}', ?)", (_lesson(concept), at))


def _recap(client, course: int) -> dict | None:
    return client.get(f"/api/courses/{course}").json()["recap"]


def test_a_replay_whose_units_are_all_marked_known_is_finished(client):
    course, units = _replay(client, "Pulleys", "Later")
    _know(course, "Pulleys")
    assert _recap(client, course) is None
    _know(course, "Later")
    assert learner_routes._today_units(db.course(course)["profile_id"]) == []

    first = _recap(client, course)
    assert first["finished"]
    assert first["seen"] is False
    db.conn.execute("UPDATE recaps SET finished = '2026-11-01 10:00:00' WHERE course_id = ?", (course,))
    assert _recap(client, course) == {"finished": "2026-11-01 10:00:00", "seen": False}

    story = client.get(f"/api/courses/{course}/recap").json()
    assert [u["title"] for u in story["before"]] == ["Pulleys", "Later"]
    assert (story["steps"], story["stats"]["units_done"], story["stats"]["units"]) == ([], 2, 2)


def test_a_replay_finishes_when_its_last_unit_not_known_was_finished(client):
    course, units = _replay(client, "Pulleys", "Tension", "Wear")
    _finish(units["Pulleys"], "2026-10-05 10:00:00")
    _finish(units["Tension"], "2026-10-12 10:00:00")
    assert _recap(client, course) is None
    _know(course, "Wear")
    assert db.course_finished(course) == "2026-10-12 10:00:00"
    assert _recap(client, course) == {"finished": "2026-10-12 10:00:00", "seen": False}
    story = recap.story(course, NOW)
    assert [s["title"] for s in story["steps"]] == ["Pulleys", "Tension"]
    assert [u["title"] for u in story["before"]] == ["Wear"]
    assert story["stats"]["units_done"] == 3


def _answer(client, concept: int) -> None:
    quiz = _block(concept, "quiz")
    assert client.post(f"/api/blocks/{quiz['id']}/quiz", json={"answer": "b", "confidence": 0.5}).status_code < 300


def _attempt(client, concept: int) -> None:
    task = _block(concept, "challenge")
    assert client.post(f"/api/blocks/{task['id']}/attempt", json={"answer": "One pulley."}).status_code < 300


def _ask(client, concept: int) -> None:
    assert client.post(f"/api/lessons/{_lesson(concept)}/turns", json={"text": "Why?"}).status_code < 300


@pytest.mark.parametrize("work", [_answer, _attempt, _ask])
def test_a_known_unit_of_a_replay_its_reader_began_is_done_once_its_lesson_is(client, work):
    course, units = _replay(client, "Pulleys", "Tension")
    work(client, units["Pulleys"])
    _know(course, "Pulleys", "Tension")
    assert _recap(client, course) is None
    assert [u["title"] for u in recap.story(course, NOW)["before"]] == ["Tension"]
    _finish(units["Pulleys"], "2026-10-12 10:00:00")
    assert _recap(client, course) == {"finished": "2026-10-12 10:00:00", "seen": False}


def test_answering_a_units_card_in_the_placement_does_not_begin_the_unit(client):
    course, units = _replay(client, "Pulleys", "Tension")
    placement = client.post(f"/api/courses/{course}/placement/cards").json()
    for quiz in [b for b in placement["blocks"] if b["kind"] == "quiz"]:
        assert client.post(f"/api/blocks/{quiz['id']}/quiz", json={"answer": "a", "confidence": 0.8}).status_code < 300
    assert [c["known"] for c in db.concepts(course)] == [1, 1]
    assert _recap(client, course)["seen"] is False


def test_an_unwritten_unit_of_a_replay_begins_when_its_reader_opens_it(client):
    course, units = _replay(client, "Pulleys", "Later")
    assert client.post(f"/api/concepts/{units['Later']}/lesson").status_code == 200
    _know(course, "Pulleys", "Later")
    assert _recap(client, course) is None
    _finish(units["Later"], "2026-10-12 10:00:00")
    assert _recap(client, course) == {"finished": "2026-10-12 10:00:00", "seen": False}


def test_a_known_unit_of_an_ordinary_course_is_begun_once_it_is_opened(client):
    course = db.create_course("Belts", _profile("learner"))["id"]
    db.set_concepts(course, [{"title": "Drives", "concepts": ["Pulleys", "Tension"], "known": ["Pulleys", "Tension"]}])
    opened = db.concepts(course)[0]["id"]
    db.add_block(db.create_lesson(course, "Pulleys", "lesson", opened), "prose", "On pulleys.", {"imported": True})
    assert _recap(client, course) is None
    assert [u["title"] for u in recap.story(course, NOW)["before"]] == ["Tension"]
    _finish(opened, "2026-10-12 10:00:00")
    assert _recap(client, course) == {"finished": "2026-10-12 10:00:00", "seen": False}


def _step(client, concept: int) -> None:
    asyncio.run(lesson_flow.step_done(_lesson(concept)))


def _word_round(client, concept: int) -> None:
    check = _block(concept, "vocab")
    asyncio.run(blocks_routes.vocab_check(check["id"], blocks_routes.Known(known=check["data"]["current"]["words"][:1])))


def _known_word(client, concept: int) -> None:
    asyncio.run(blocks_routes.know_word(_block(concept, "reading")["id"], blocks_routes.Word(word="Riemen")))


def _run(client, concept: int) -> None:
    exercise = _block(concept, "exercise")
    db.set_block_data(exercise["id"], {**exercise["data"], "last_run": {"exit_code": 0, "output": "1.2 m"}})


def _saved_file(client, concept: int) -> None:
    exercise = _block(concept, "exercise")
    saved = client.post(f"/api/blocks/{exercise['id']}/files", json={"path": "belt/length.py", "content": "print(1.2)", "base": "# the belt's length"})
    assert saved.json() == {"saved": True}


def _cleaned_up(client, concept: int) -> None:
    cleanup.keep_exercise_files(db.course(db.row("SELECT course_id FROM concepts WHERE id = ?", concept)["course_id"]))
    assert _block(concept, "exercise")["data"]["files_kept"]


def _nothing(client, concept: int) -> None:
    pass


@pytest.mark.parametrize("work, begun", [
    (_nothing, False), (_saved_file, False), (_cleaned_up, False), (_step, True), (_word_round, True), (_known_word, True), (_run, True),
])
def test_what_a_reader_does_on_the_cards_of_a_known_unit_begins_it(client, work, begun):
    course, units = _replay(client, "Pulleys", "Tension", worked="Pulleys")
    work(client, units["Pulleys"])
    _know(course, "Pulleys", "Tension")
    assert db.begun_units(course) == ({units["Pulleys"]} if begun else set())
    assert (_recap(client, course) is None) == begun
    assert [u["title"] for u in recap.story(course, NOW)["before"]] == (["Tension"] if begun else ["Pulleys", "Tension"])
