import asyncio
import http.server
import json
import runpy
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from wise_scholar import app, cli, course_files, db, sandbox
from wise_scholar.tools import practice as practice_tools


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """The app on a free port of this machine, with no lifespan; each test brings its own rows and workspace."""
    running = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=free_port(), lifespan="off", log_level="warning"))
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    while not running.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{running.config.port}"
    running.should_exit = True
    thread.join(5)


@pytest.fixture
def exercise(tmp_path, monkeypatch, server):
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(sandbox, "COMMANDS", True)
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    monkeypatch.delenv("WS_SERVER", raising=False)
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, *a, **k: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Local {tmp_path.name}",)).lastrowid
    course = db.create_course(f"Local {tmp_path.name}", who)
    db.set_concepts(course["id"], [{"title": "M", "concepts": ["loops"], "known": []}])
    lesson = db.create_lesson(course["id"], "loops", "lesson", db.concepts(course["id"])[0]["id"])
    reply = asyncio.run(practice_tools.pose_exercise(
        lesson, "Count to three.\n\nUse a loop.", [practice_tools.ExerciseFile(path="loops/main.py", content="n = 1\n")], "echo ran",
    ))
    assert reply.startswith("shown"), reply
    block = db.blocks(lesson)[-1]
    yield {
        "course": course["id"], "lesson": lesson, "block": block, "id": str(block["id"]), "server": server, "turns": turns,
        "workspace": db.workspace(db.lesson(lesson)["slug"]), "folder": tmp_path / "mine",
        "client": TestClient(app.app, base_url="http://127.0.0.1", raise_server_exceptions=False),
    }
    db.delete_course(course["id"])
    db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


def pulled(ex) -> None:
    assert cli.main(["--server", ex["server"], "pull", ex["id"], str(ex["folder"])]) == 0


def state(ex) -> dict:
    return json.loads((ex["folder"] / cli.STATE).read_text())


def sync(ex, memory=None) -> bool:
    return cli.sync(ex["server"], ex["folder"], state(ex), memory or cli.Memory(wait_steady=False))


def watch(ex, monkeypatch, *steps) -> list[float]:
    """Runs watch; each step runs at one of its pauses, and the pause after the last step stops it. Returns the
    pauses' lengths."""
    pauses, steps = [], list(steps)

    def pause(seconds):
        pauses.append(seconds)
        if not steps:
            raise KeyboardInterrupt
        steps.pop(0)()

    monkeypatch.setattr(cli.time, "sleep", pause)
    with pytest.raises(KeyboardInterrupt):
        cli.watch(ex["folder"], state(ex))
    return pauses


def local(ex) -> Path:
    return ex["folder"] / "loops/main.py"


def disk(ex) -> Path:
    return ex["workspace"] / "loops/main.py"


def test_a_course_lists_its_exercises_with_their_files_and_never_a_server_path(exercise, tmp_path):
    listed = exercise["client"].get(f"/api/courses/{exercise['course']}/exercises")
    assert listed.json() == [{
        "id": exercise["block"]["id"], "lesson_id": exercise["lesson"], "unit": "loops", "summary": "Count to three.",
        "files": ["loops/main.py"], "run": "echo ran", "open": True,
    }]
    assert str(tmp_path) not in listed.text
    db.set_block_data(exercise["block"]["id"], {**exercise["block"]["data"], "solved": True})
    assert exercise["client"].get(f"/api/courses/{exercise['course']}/exercises").json()[0]["open"] is False
    assert exercise["client"].get("/api/courses/999999/exercises").status_code == 404


def test_a_malformed_exercise_is_left_out_of_the_listing(exercise):
    db.add_block(exercise["lesson"], "exercise", "Broken.", {"files": 3})
    db.add_block(exercise["lesson"], "exercise", "Broken too.", {"files": ["a.py"]})
    listed = exercise["client"].get(f"/api/courses/{exercise['course']}/exercises")
    assert listed.status_code == 200 and [e["id"] for e in listed.json()] == [exercise["block"]["id"]]


def test_a_replayed_unit_lists_no_exercise_past_its_first_open_check_and_a_prepared_course_none_open(exercise):
    later = asyncio.run(practice_tools.pose_exercise(
        exercise["lesson"], "Count to four.", [practice_tools.ExerciseFile(path="loops/four.py", content="")], "echo four",
    ))
    assert later.startswith("shown")

    def listed():
        return [(e["summary"], e["open"]) for e in exercise["client"].get(f"/api/courses/{exercise['course']}/exercises").json()]

    assert listed() == [("Count to three.", True), ("Count to four.", True)]
    db.conn.execute("UPDATE courses SET mode = 'replay' WHERE id = ?", (exercise["course"],))
    assert listed() == [("Count to three.", True)]
    db.set_block_data(exercise["block"]["id"], {**exercise["block"]["data"], "solved": True})
    assert listed() == [("Count to three.", False), ("Count to four.", True)]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (exercise["course"],))
    assert listed() == [("Count to three.", False), ("Count to four.", False)]


def test_the_server_hands_out_ws_py_and_hashes_files_for_its_poll(exercise):
    script = exercise["client"].get("/api/ws.py")
    assert script.status_code == 200 and script.content == Path(cli.__file__).read_bytes()
    assert "ws.py" in script.headers["content-disposition"]
    [hashed] = exercise["client"].get(f"/api/blocks/{exercise['id']}/files?hashes=1").json()
    assert "content" not in hashed and hashed["sha256"] == cli._sha("n = 1\n")


def test_ws_py_needs_nothing_but_the_standard_library():
    code = Path(cli.__file__).read_text().split('"""', 2)[2]
    assert "# /// script" in Path(cli.__file__).read_text()
    assert "wise_scholar" not in code and "httpx" not in code and "from ." not in code


def test_ws_list_prints_each_exercise(exercise, capsys):
    assert cli.main(["--server", exercise["server"], "list", str(exercise["course"])]) == 0
    assert capsys.readouterr().out.split() == [exercise["id"], "open", "loops:", "Count", "to", "three."]


def test_pull_copies_the_files_and_remembers_the_server_and_the_text_they_started_from(exercise, monkeypatch):
    monkeypatch.chdir(exercise["folder"].parent)
    monkeypatch.setenv("WS_SERVER", exercise["server"] + "/")
    assert cli.main(["pull", exercise["id"]]) == 0
    folder = exercise["folder"].parent / f"exercise-{exercise['id']}"
    assert (folder / "loops/main.py").read_text() == "n = 1\n"
    assert json.loads((folder / cli.STATE).read_text()) == {
        "server": exercise["server"], "exercise": exercise["block"]["id"], "files": {"loops/main.py": {"base": "n = 1\n", "editable": True}},
    }


def test_pull_never_writes_outside_its_folder(exercise, tmp_path):
    db.set_block_data(exercise["block"]["id"], {**exercise["block"]["data"], "files": ["loops/main.py", "../../escape.py"]})
    assert cli.main(["--server", exercise["server"], "pull", exercise["id"], str(exercise["folder"])]) == 1
    assert not (tmp_path / "escape.py").exists() and not exercise["folder"].exists()
    with pytest.raises(cli.Failed):
        cli._local(tmp_path, "/etc/passwd")
    with pytest.raises(cli.Failed):
        cli._local(tmp_path, cli.STATE)


def test_pull_skips_a_binary_or_oversize_file_instead_of_writing_it_mangled(exercise, monkeypatch, capsys):
    monkeypatch.setattr(course_files, "READ_LIMIT", 50)
    (exercise["workspace"] / "loops/data.bin").write_bytes(b"\xff\xfe\x00binary")
    (exercise["workspace"] / "loops/big.txt").write_text("x" * 100)
    db.set_block_data(exercise["block"]["id"], {**exercise["block"]["data"], "files": ["loops/main.py", "loops/data.bin", "loops/big.txt"]})
    pulled(exercise)
    assert local(exercise).read_text() == "n = 1\n"
    assert not (exercise["folder"] / "loops/data.bin").exists() and not (exercise["folder"] / "loops/big.txt").exists()
    assert capsys.readouterr().err.count("skipped:") == 2
    assert list(state(exercise)["files"]) == ["loops/main.py"]


def test_pull_again_keeps_edits_not_yet_sent(exercise):
    pulled(exercise)
    local(exercise).write_text("mine\n")
    assert cli.main(["pull", exercise["id"], str(exercise["folder"])]) == 1
    assert local(exercise).read_text() == "mine\n"


def test_watch_sends_a_file_once_it_stopped_changing_and_confirms_every_send(exercise, monkeypatch, capsys):
    pulled(exercise)
    local(exercise).write_text("first\n")
    seen = []
    watch(
        exercise, monkeypatch,
        lambda: seen.append(disk(exercise).read_text()),
        lambda: (seen.append(disk(exercise).read_text()), local(exercise).write_text("second, longer\n")),
        lambda: seen.append(disk(exercise).read_text()),
    )
    assert seen == ["n = 1\n", "first\n", "first\n"]
    assert disk(exercise).read_text() == "second, longer\n"
    assert capsys.readouterr().out.count("sent: loops/main.py") == 2
    assert state(exercise)["files"]["loops/main.py"]["base"] == "second, longer\n"


def test_watch_brings_in_the_servers_own_change(exercise, monkeypatch):
    pulled(exercise)
    disk(exercise).write_text("# the tutor's note\n")
    watch(exercise, monkeypatch)
    assert local(exercise).read_text() == "# the tutor's note\n"


def test_an_edit_on_both_sides_leaves_a_conflict_file_until_it_is_merged(exercise, monkeypatch, capsys):
    pulled(exercise)
    local(exercise).write_text("mine\n")
    disk(exercise).write_text("theirs\n")
    conflict = exercise["folder"] / "loops/main.py.conflict"

    def merge():
        assert conflict.read_text() == "theirs\n" and disk(exercise).read_text() == "theirs\n"
        local(exercise).write_text("mine and theirs\n")
        conflict.unlink()

    watch(exercise, monkeypatch, lambda: None, lambda: None, lambda: None, merge, lambda: None)
    assert disk(exercise).read_text() == "mine and theirs\n" and not conflict.exists()
    assert capsys.readouterr().err.count("conflict:") == 1


def test_the_same_edit_on_both_sides_is_no_conflict(exercise):
    pulled(exercise)
    local(exercise).write_text("same\n")
    disk(exercise).write_text("same\n")
    assert sync(exercise)
    assert not (exercise["folder"] / "loops/main.py.conflict").exists()
    assert state(exercise)["files"]["loops/main.py"]["base"] == "same\n"


def test_a_conflict_file_linked_outside_the_folder_is_never_written(exercise, tmp_path):
    pulled(exercise)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched\n")
    (exercise["folder"] / "loops/main.py.conflict").symlink_to(outside)
    local(exercise).write_text("mine\n")
    disk(exercise).write_text("theirs\n")
    assert not sync(exercise)
    assert outside.read_text() == "untouched\n" and disk(exercise).read_text() == "theirs\n"


def test_a_damaged_state_file_gives_a_message_not_a_traceback(exercise, capsys):
    pulled(exercise)
    for damaged in ("{", '{"exercise": 1}', "[]"):
        (exercise["folder"] / cli.STATE).write_text(damaged)
        assert cli.main(["watch", str(exercise["folder"])]) == 1
        assert "is damaged" in capsys.readouterr().err


def test_nothing_is_sent_while_an_online_command_runs_or_once_the_exercise_is_closed(exercise, monkeypatch, capsys):
    pulled(exercise)
    local(exercise).write_text("mine\n")
    memory = cli.Memory(wait_steady=False)
    with monkeypatch.context() as online:
        online.setattr(sandbox, "online", lambda _: True)
        assert not sync(exercise, memory)
        assert not sync(exercise, memory)
    assert capsys.readouterr().err.count("a command you allowed to use the internet") == 1
    db.set_block_data(exercise["block"]["id"], {**exercise["block"]["data"], "solved": True})
    assert not sync(exercise, memory)
    assert "this exercise is closed" in capsys.readouterr().err
    assert disk(exercise).read_text() == "n = 1\n"


def test_a_file_the_server_refuses_as_too_large_is_reported_once(exercise, monkeypatch, capsys):
    pulled(exercise)
    monkeypatch.setattr(course_files, "READ_LIMIT", 10)
    local(exercise).write_text("a longer text than ten bytes\n")
    memory = cli.Memory(wait_steady=False)
    assert not sync(exercise, memory)
    assert not sync(exercise, memory)
    assert capsys.readouterr().err.count("this file is too large to save here") == 1
    assert disk(exercise).read_text() == "n = 1\n"


def test_a_local_file_over_the_size_limit_or_not_utf8_is_not_sent(exercise, monkeypatch):
    pulled(exercise)
    monkeypatch.setattr(cli, "READ_LIMIT", 10)
    local(exercise).write_text("é" * 6)
    assert not sync(exercise)
    local(exercise).write_bytes(b"\xff\xfe")
    assert not sync(exercise)
    assert disk(exercise).read_text() == "n = 1\n"


def test_watch_backs_off_while_the_server_is_unreachable_and_says_so_once(exercise, monkeypatch, capsys):
    pulled(exercise)
    (exercise["folder"] / cli.STATE).write_text(json.dumps({**state(exercise), "server": f"http://127.0.0.1:{free_port()}"}))
    assert watch(exercise, monkeypatch, *[lambda: None] * 5) == [4, 8, 16, 30, 30, 30]
    assert capsys.readouterr().err.count("cannot reach") == 1


def test_submit_sends_the_edit_runs_it_and_asks_the_tutor_to_check(exercise, capsys):
    pulled(exercise)
    local(exercise).write_text("print(1)\n")
    assert cli.main(["submit", str(exercise["folder"]), "--answer", "it counts"]) == 0
    out = capsys.readouterr().out
    assert "ran\n" in out and "exit code 0" in out and "sent to the tutor" in out
    [turn] = exercise["turns"]
    assert turn.startswith("[learner attempt]") and "print(1)" in turn and "it counts" in turn


def test_submit_stops_when_the_exercise_cannot_run(exercise, monkeypatch, capsys):
    pulled(exercise)
    monkeypatch.setattr(sandbox, "COMMANDS", False)
    assert cli.main(["submit", str(exercise["folder"])]) == 1
    assert "not run, so not sent to the tutor: running code is turned off" in capsys.readouterr().err
    assert exercise["turns"] == []


def test_submit_waits_for_a_conflict_to_be_resolved(exercise):
    pulled(exercise)
    local(exercise).write_text("mine\n")
    disk(exercise).write_text("theirs\n")
    assert cli.main(["submit", str(exercise["folder"])]) == 1
    assert exercise["turns"] == []


def test_a_reply_that_is_not_the_api_is_a_message_not_a_traceback(exercise, capsys):
    class Portal(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>Sign in to the hotel wifi</html>")

        def log_message(self, *args):
            pass

    portal = http.server.HTTPServer(("127.0.0.1", 0), Portal)
    threading.Thread(target=portal.serve_forever, daemon=True).start()
    try:
        assert cli.main(["pull", exercise["id"], str(exercise["folder"]), "--server", f"http://127.0.0.1:{portal.server_port}"]) == 1
    finally:
        portal.shutdown()
    assert "did not answer as Wise Scholar does" in capsys.readouterr().err


def test_server_may_come_after_the_command(exercise, capsys):
    assert cli.main(["list", str(exercise["course"]), "--server", exercise["server"]]) == 0
    assert exercise["id"] in capsys.readouterr().out


def test_a_conflict_file_linked_to_another_file_of_the_folder_is_never_written(exercise):
    pulled(exercise)
    other = exercise["folder"] / "loops/notes.txt"
    other.write_text("my notes\n")
    (exercise["folder"] / "loops/main.py.conflict").symlink_to(other)
    local(exercise).write_text("mine\n")
    disk(exercise).write_text("theirs\n")
    assert not sync(exercise)
    assert other.read_text() == "my notes\n"


def test_a_file_that_vanishes_while_read_is_never_sent_empty(exercise, monkeypatch):
    pulled(exercise)
    local(exercise).write_text("mine\n")
    monkeypatch.setattr(cli, "_read", lambda target: None)
    assert not sync(exercise)
    assert disk(exercise).read_text() == "n = 1\n"


def test_a_local_edit_made_just_before_the_servers_text_comes_in_becomes_a_conflict(exercise, monkeypatch):
    pulled(exercise)
    disk(exercise).write_text("theirs\n")
    real, reads = cli._read, []

    def read(target):
        if target.name == "main.py":
            reads.append(target)
            if len(reads) == 2:
                target.write_text("edited meanwhile\n")
        return real(target)

    monkeypatch.setattr(cli, "_read", read)
    assert not sync(exercise)
    assert local(exercise).read_text() == "edited meanwhile\n"
    assert (exercise["folder"] / "loops/main.py.conflict").read_text() == "theirs\n"


def test_an_update_from_the_server_replaces_the_file_whole_and_keeps_its_mode(exercise):
    pulled(exercise)
    local(exercise).chmod(0o755)
    disk(exercise).write_text("theirs\n")
    assert sync(exercise)
    assert local(exercise).read_text() == "theirs\n" and local(exercise).stat().st_mode & 0o777 == 0o755
    assert [f.name for f in local(exercise).parent.iterdir()] == ["main.py"]


def test_pull_leaves_a_file_it_did_not_write_and_puts_the_servers_beside_it(exercise, capsys):
    local(exercise).parent.mkdir(parents=True)
    local(exercise).write_text("my own start\n")
    pulled(exercise)
    assert local(exercise).read_text() == "my own start\n"
    assert (exercise["folder"] / "loops/main.py.conflict").read_text() == "n = 1\n"
    assert state(exercise)["files"]["loops/main.py"]["conflict"] == "n = 1\n"
    assert "conflict:" in capsys.readouterr().err


def test_a_size_warning_shows_again_after_the_file_went_back_to_its_start(exercise, monkeypatch, capsys):
    pulled(exercise)
    monkeypatch.setattr(cli, "READ_LIMIT", 10)
    memory = cli.Memory(wait_steady=False)
    for text in ("a longer text\n", "n = 1\n", "a longer text\n"):
        local(exercise).write_text(text)
        sync(exercise, memory)
    assert capsys.readouterr().err.count("is larger than") == 2


def test_an_older_python_gets_a_message_not_a_syntax_error(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 9, 18))
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(cli.__file__, run_name="ws")
    assert stopped.value.code == "ws.py needs Python 3.10 or later"
