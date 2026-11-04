import asyncio
import os
import tempfile

import pytest
from fastapi import HTTPException

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, bundle, course_files, db, sandbox, tutor  # noqa: E402


@pytest.fixture
def exercise(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "WORKSPACE", tmp_path)
    monkeypatch.setattr(sandbox, "COMMANDS", True)
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Editor {tmp_path.name}",)).lastrowid
    course = db.create_course(f"Editing {tmp_path.name}", who)
    db.set_concepts(course["id"], [{"title": "M", "concepts": ["c"], "known": []}])
    lesson = db.create_lesson(course["id"], "c", "lesson", db.concepts(course["id"])[0]["id"])
    reply = asyncio.run(tutor.pose_exercise(
        lesson, "Write it.", [tutor.ExerciseFile(path="c/main.py", content="a = 1\n")], "uv run c/main.py",
        completions=[course_files.Completion(label="math.sqrt", signature="sqrt(x)", doc="Square root.")],
    ))
    assert reply.startswith("shown"), reply
    block = db.blocks(lesson)[-1]
    yield block, db.workspace(db.lesson(lesson)["slug"])
    db.delete_course(course["id"])
    db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


def save(block, content, base, path="c/main.py"):
    return asyncio.run(app.save_exercise_file(block["id"], app.SavedFile(path=path, content=content, base=base)))


def refused(block, content, base, path="c/main.py"):
    with pytest.raises(HTTPException) as e:
        save(block, content, base, path)
    return e.value.status_code


def test_the_editor_saves_to_the_file_the_learner_can_also_open(exercise):
    block, workspace = exercise
    assert save(block, "a = 2\n", "a = 1\n") == {"saved": True}
    assert (workspace / "c/main.py").read_text() == "a = 2\n"
    file = app.exercise_files(block["id"])[0]
    assert file["content"] == "a = 2\n" and file["editable"] and file["location"].endswith("c/main.py")


def test_a_change_on_disk_is_never_overwritten_by_older_text(exercise):
    block, workspace = exercise
    (workspace / "c/main.py").write_text("from my editor\n")
    assert save(block, "a = 2\n", "a = 1\n") == {"saved": False, "content": "from my editor\n"}
    assert (workspace / "c/main.py").read_text() == "from my editor\n"


def test_only_the_exercises_own_files_can_be_saved(exercise):
    block, workspace = exercise
    assert refused(block, "x", "", "../../outside.py") == 404
    assert refused(block, "x", "", "c/other.py") == 404
    assert not (workspace / "c/other.py").exists()


def test_a_closed_exercise_or_a_running_online_command_keeps_the_file(exercise, monkeypatch):
    block, workspace = exercise
    with monkeypatch.context() as online:
        online.setattr(sandbox, "online", lambda _: True)
        assert refused(block, "x", "a = 1\n") == 409
        assert app.exercise_files(block["id"])[0]["online"]
    db.set_block_data(block["id"], {**block["data"], "solved": True})
    assert refused(block, "x", "a = 1\n") == 409
    assert (workspace / "c/main.py").read_text() == "a = 1\n"


def test_a_file_that_would_not_survive_being_saved_whole_is_not_editable(exercise):
    block, workspace = exercise
    target = workspace / "c/main.py"
    target.write_bytes(b"\xff\xfe binary")
    assert not app.exercise_files(block["id"])[0]["editable"]
    assert refused(block, "x", "anything") == 409
    assert target.read_bytes() == b"\xff\xfe binary"
    target.write_text("x" * (course_files.READ_LIMIT + 1))
    assert not app.exercise_files(block["id"])[0]["editable"]
    assert refused(block, "x", "x" * course_files.READ_LIMIT) == 409
    assert target.stat().st_size == course_files.READ_LIMIT + 1


def test_text_that_cannot_be_written_leaves_the_file_as_it_was(exercise):
    block, workspace = exercise
    assert refused(block, "bad \ud800", "a = 1\n") == 422
    assert refused(block, "x" * (course_files.READ_LIMIT + 1), "a = 1\n") == 413
    assert (workspace / "c/main.py").read_text() == "a = 1\n"


def test_completions_reach_the_card_and_come_cleaned_from_a_bundle(exercise):
    block, _ = exercise
    assert block["data"]["completions"] == [{"label": "math.sqrt", "signature": "sqrt(x)", "doc": "Square root."}]
    dirty = bundle.Block(key="a" * 32, kind="exercise", markdown="x", data={
        "completions": [{"label": "ok.name"}, {"label": "<img src=x>"}, "junk", {"label": "a", "doc": "d" * 900}],
    })
    assert [c["label"] for c in bundle._clean_block(dirty, {})["completions"]] == ["ok.name"]
    plain = bundle.Block(key="b" * 32, kind="exercise", markdown="x", data={"completions": "junk"})
    assert bundle._clean_block(plain, {})["completions"] == []
