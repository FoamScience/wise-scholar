"""An exercise's solution files: written by the tutor at reveal or by a course's author, locked away from a learner
until the solution is shown to them, then offered for their files to be compared with."""
import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from wise_scholar import app, bundle, challenge, course_files, db, hub
from wise_scholar.routes import blocks as blocks_routes
from wise_scholar.tools import practice

PATH, STARTER = "loft/blade.py", "def loft():\n    pass\n"
SOLVED = "def loft():\n    return 'SOLFILE lofted'\n"


@pytest.fixture
def places(tmp_path, monkeypatch):
    """Files land in the test's folder, no turn starts, and the profiles and courses made here leave the database."""
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    monkeypatch.setattr(hub, "publish", lambda course_id, event: None)
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]
    yield {"source_dir": tmp_path / "sources", "store": tmp_path / "versions"}
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _profile(name: str) -> int:
    return db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"{name} {uuid.uuid4().hex[:6]}",)).lastrowid


def _exercise(course: int) -> int:
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(course, "Loft", "lesson", db.concepts(course)[0]["id"])
    files = [practice.ExerciseFile(path=PATH, content=STARTER), practice.ExerciseFile(path="loft/notes.md", content="")]
    assert asyncio.run(practice.pose_exercise(lesson, "Loft it.", files, f"python {PATH}")).startswith("shown")
    return next(b["id"] for b in db.blocks(lesson) if b["kind"] == "exercise")


def test_the_tutors_solution_files_reach_the_card_only_once_the_solution_is_shown(places):
    exercise = _exercise(db.create_course("Solution lofting", _profile("Solution tutor"))["id"])
    tutors = [practice.ExerciseFile(path=PATH, content=SOLVED)]
    stray = [practice.ExerciseFile(path="elsewhere.py", content="x")]
    assert asyncio.run(practice.reveal(exercise, "Return it.", tutors)).startswith("refused")
    assert asyncio.run(practice.reveal(exercise, "Return it.", stray)).startswith("refused")
    assert "solution_files" not in db.block(exercise)["data"]

    asyncio.run(blocks_routes.give_up(exercise))
    assert asyncio.run(practice.reveal(exercise, "Return it.", stray)).startswith("error")
    assert db.block(exercise)["data"]["solution"] is None
    assert asyncio.run(practice.reveal(exercise, "Return it.", tutors)) == "shown"
    data = db.block(exercise)["data"]
    assert (data["solution"], data["solution_files"]) == ("Return it.", {PATH: SOLVED})


def test_an_exercise_revealed_without_files_holds_none(places):
    exercise = _exercise(db.create_course("Solution prose", _profile("Solution tutor"))["id"])
    asyncio.run(blocks_routes.give_up(exercise))
    asyncio.run(practice.reveal(exercise, "Return it."))
    assert "solution_files" not in db.block(exercise)["data"]


def _prepared(places, files: bool = True) -> tuple[int, int]:
    """A prepared course whose exercise's author wrote its solution, and its files with a path that is not one of its
    files unless files is False."""
    course = db.create_course("Solution authored", _profile("Solution author"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    exercise = _exercise(course)
    edited = blocks_routes.edit_block(exercise, blocks_routes.BlockEdit(
        solution="SOLKEY return it.", solution_files={PATH: SOLVED, "stray.py": "SOLFILE stray"} if files else None,
    ))
    assert edited["data"].get("solution_files") == ({PATH: SOLVED} if files else None)
    db.add_block(db.block(exercise)["lesson_id"], "done", "You can loft.", {})
    return course, exercise


def _client() -> TestClient:
    return TestClient(app.app, base_url="http://127.0.0.1", raise_server_exceptions=False)


def _held(value, keys: set, texts: set) -> None:
    if isinstance(value, dict):
        keys.update(value)
        for v in value.values():
            _held(v, keys, texts)
    elif isinstance(value, list):
        for v in value:
            _held(v, keys, texts)
    elif isinstance(value, str):
        texts.add(value)


def _served(course: int, lesson: int, exercise: int) -> tuple[set, set]:
    """The keys and texts the browser gets over HTTP: the course with its lessons, the lesson and the exercise's files."""
    client, keys, texts = _client(), set(), set()
    for url in (f"/api/courses/{course}", f"/api/lessons/{lesson}", f"/api/blocks/{exercise}/files"):
        got = client.get(url)
        assert got.status_code == 200, (url, got.text)
        _held(got.json(), keys, texts)
    return keys, texts


def _leaks(course: int, lesson: int, exercise: int) -> bool:
    keys, texts = _served(course, lesson, exercise)
    return "solution_files" in keys or SOLVED in texts


def _played(course: int, places) -> tuple[int, int]:
    v = bundle.publish(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    version_hash, manifest, assets = bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())
    mine = bundle.install(_profile("Solution reader"), version_hash, manifest, assets, places["source_dir"])["id"]
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", mine)["id"]
    return mine, next(b["id"] for b in db.blocks(lesson) if b["kind"] == "exercise")


def _reachable(course: int, lesson: int) -> str:
    """The lesson as the browser gets it, the tutor's prompt and record of it, the vault and the next version."""
    from wise_scholar import obsidian

    view = app._lesson_view(lesson)
    vault = obsidian.Vault(course).lesson_text({**db.lesson(lesson), "blocks": view["blocks"], "messages": []}, chat=True)
    manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=None)
    return json.dumps([
        view, [db.block(b["id"]) for b in view["blocks"]], app._turn_prompt(db.lesson(lesson), "[learner] help"),
        app._lesson_record(lesson), manifest, vault,
    ], default=str, ensure_ascii=False)


def test_an_authors_solution_files_stay_locked_for_a_reader_until_their_solution_is_shown(places):
    course, _ = _prepared(places)
    mine, exercise = _played(course, places)
    lesson = db.block(exercise)["lesson_id"]
    assert "SOLFILE" not in _reachable(mine, lesson)
    assert not _leaks(mine, lesson, exercise)
    assert db.locked(exercise)["solution_files"] == {PATH: SOLVED}
    assert asyncio.run(practice.reveal(exercise, "", [])).startswith("refused")
    assert "SOLFILE" not in _reachable(mine, lesson)
    assert not _leaks(mine, lesson, exercise)

    asyncio.run(blocks_routes.give_up(exercise))
    asyncio.run(practice.reveal(exercise, "", [practice.ExerciseFile(path=PATH, content="the tutor's own")]))
    assert db.block(exercise)["data"]["solution_files"] == {PATH: SOLVED}
    assert _leaks(mine, lesson, exercise)
    # a fork ships neither what was shown nor what is still locked
    manifest, _, _ = bundle.build(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert "SOLFILE" not in json.dumps(manifest)


def test_a_copy_of_a_learners_course_leaves_their_shown_solution_files_out(places):
    exercise = _exercise(db.create_course("Solution copied", _profile("Solution learner"))["id"])
    db.set_block_data(exercise, {**db.block(exercise)["data"], "solution": "x", "solution_files": {PATH: SOLVED}})
    assert "solution_files" not in db._fresh(db.block(exercise)["data"])
    assert db._fresh(db.block(exercise)["data"], authored=True)["solution_files"] == {PATH: SOLVED}


def test_only_an_exercises_own_files_are_kept_as_its_solution():
    data = {"files": [PATH]}
    assert challenge.solution_files(data, {PATH: SOLVED, "x.py": "", PATH + "/": "y"}) == {PATH: SOLVED}
    assert challenge.solution_files(data, {PATH: 3}) == {}
    assert challenge.solution_files({}, {PATH: SOLVED}) == {}
    assert challenge.solution_files(data, None) == {}


def test_a_teachers_solution_files_on_a_challenge_are_ignored(places):
    course = db.create_course("Solution challenge", _profile("Solution teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(course, "Loft", "lesson", db.concepts(course)[0]["id"])
    task = db.add_block(lesson, "challenge", "Reason.", challenge.new())
    edited = blocks_routes.edit_block(task["id"], blocks_routes.BlockEdit(solution_files={PATH: SOLVED}))
    assert "solution_files" not in edited["data"]


def test_an_authors_solution_without_files_is_shown_without_the_tutors(places):
    course, _ = _prepared(places, files=False)
    _, exercise = _played(course, places)
    asyncio.run(blocks_routes.give_up(exercise))
    told = asyncio.run(practice.reveal(exercise, "", [practice.ExerciseFile(path=PATH, content=SOLVED)]))
    assert "SOLKEY return it." in told
    data = db.block(exercise)["data"]
    assert (data["solution"], "solution_files" in data) == ("SOLKEY return it.", False)


def test_a_teacher_cannot_give_solution_files_without_a_written_solution(places):
    course = db.create_course("Solution unwritten", _profile("Solution teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    exercise = _exercise(course)
    lesson = db.block(exercise)["lesson_id"]
    client = _client()
    refused = client.post(f"/api/blocks/{exercise}/edit", json={"solution_files": {PATH: SOLVED}})
    assert (refused.status_code, refused.json()["detail"]) == (422, "solution files need a written solution")
    assert not _leaks(course, lesson, exercise)

    assert client.post(f"/api/blocks/{exercise}/edit", json={"solution": "Return it.", "solution_files": {PATH: SOLVED}}).status_code == 200
    assert client.post(f"/api/blocks/{exercise}/edit", json={"solution": ""}).status_code == 422
    assert client.post(f"/api/blocks/{exercise}/edit", json={"solution": "", "solution_files": {}}).status_code == 200
    data = db.block(exercise)["data"]
    assert (data["solution"], "solution_files" in data) == (None, False)


def test_a_solution_file_is_no_longer_than_a_file_the_editor_saves(places):
    course = db.create_course("Solution long", _profile("Solution teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    exercise = _exercise(course)
    too_long = {"solution": "x", "solution_files": {PATH: "x" * (course_files.READ_LIMIT + 1)}}
    assert _client().post(f"/api/blocks/{exercise}/edit", json=too_long).status_code == 422
    assert "solution_files" not in db.block(exercise)["data"]
