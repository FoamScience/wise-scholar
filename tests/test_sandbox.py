import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import course_files, db, sandbox, tutor  # noqa: E402

needs_bwrap = pytest.mark.skipif(not sandbox.available(), reason="bubblewrap is not usable on this machine")


def run(command: str, workspace: Path) -> dict:
    return asyncio.run(sandbox.run(command, workspace))


@pytest.fixture
def place(monkeypatch):
    """A database, two course workspaces and a home directory, all under the real home: where a real install keeps
    them, and outside /tmp, which the sandbox replaces anyway."""
    base = Path(tempfile.mkdtemp(dir=Path.home(), prefix=".wise-scholar-test-"))
    for folder in ("data", "courses/mine", "courses/other", "bin", "home/.cargo/bin", "home/.nvm", "home/.local/bin",
                   "home/.local/share/uv/credentials", "home/.local/share/opencode", "home/.atuin/bin", "home/.ssh", "home/.cache"):
        (base / folder).mkdir(parents=True)
    (base / "data/test.db").write_text("database marker")
    (base / "courses/other/notes.txt").write_text("another course")
    (base / "home/.cargo/bin/tool").write_text("a toolchain program")
    for secret in (".cargo/credentials.toml", ".nvm/.npmrc", ".local/share/uv/credentials/pypi", ".local/share/opencode/auth.json",
                   ".ssh/id_ed25519", ".bash_history"):
        (base / "home" / secret).write_text("secret marker")
    monkeypatch.setattr(db, "DB_PATH", base / "data/test.db")
    monkeypatch.setattr(db, "WORKSPACE", base / "courses")
    monkeypatch.setenv("HOME", str(base / "home"))
    home = base / "home"
    # A bin folder beside the app's data (direnv's PATH_add bin), one that does not exist, and a private one.
    path = [base / "bin", base / "courses/bin", home / ".cargo/bin", home / ".nvm/bin", home / ".local/bin", home / ".atuin/bin"]
    monkeypatch.setenv("PATH", os.pathsep.join([*map(str, path), "/usr/bin", "/bin"]))
    yield base
    shutil.rmtree(base)


@needs_bwrap
def test_a_command_writes_inside_its_workspace_and_sees_no_data_of_the_app(place):
    mine = place / "courses/mine"
    inside = run("echo hello > out.txt && cat out.txt", mine)
    assert inside == {"exit_code": 0, "output": "hello\n"} and (mine / "out.txt").read_text() == "hello\n"

    probe = run(
        f"touch {place}/data/x {place}/courses/other/x {place}/bin/x /usr/x /x /dev/x 2>&1 | grep -c -e Read-only -e 'No such'; "
        f"cat {place}/data/test.db {place}/courses/other/notes.txt 2>/dev/null; ls {place}/courses; echo done",
        mine,
    )
    assert probe["output"] == "6\nmine\ndone\n"
    assert not (place / "data/x").exists() and not (place / "bin/x").exists() and not Path("/x").exists()


@needs_bwrap
def test_a_command_sees_only_toolchains_of_the_home_directory_and_no_secrets(place, monkeypatch):
    home = place / "home"
    assert sandbox._toolchains(home) == [home / ".cargo", home / ".local/bin"]
    monkeypatch.setenv("SOME_API_KEY", "hunter2")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("WISE_SCHOLAR_SANDBOX_PATHS", os.pathsep.join(map(str, [home, place, Path.home().parent, "/"])))
    assert sandbox._toolchains(home) == [home / ".cargo", home / ".local/bin"]

    # /proc/net/dev: one line per interface; /run and /var hold the machine's sockets (docker, D-Bus, agents).
    probe = run(
        "echo key=$SOME_API_KEY bus=$DBUS_SESSION_BUS_ADDRESS; grep -c : /proc/net/dev; ls /run /var 2>/dev/null | wc -l; "
        "ls -A ~ | tr '\\n' ' '; echo; cat ~/.cargo/bin/tool; echo; "
        "cat ~/.cargo/credentials.toml ~/.nvm/.npmrc ~/.local/share/uv/credentials/pypi ~/.local/share/opencode/auth.json "
        "~/.ssh/id_ed25519 ~/.bash_history 2>/dev/null | wc -c",
        place / "courses/mine",
    )
    assert probe["output"].split("\n")[:6] == ["key= bus=", "1", "0", ".cache .cargo .local ", "a toolchain program", "0"]


@needs_bwrap
def test_a_command_is_capped_in_time_output_and_scratch_space_and_keeps_its_own_cache(place, monkeypatch):
    one, two = place / "courses/mine", place / "courses/other"
    flood = run("yes 0123456789abcdef | head -c 200000000", one)
    assert flood["exit_code"] == 0 and len(flood["output"]) == sandbox.OUTPUT_LIMIT

    full = run("for d in /tmp /dev/shm ~; do dd if=/dev/zero of=$d/big bs=1M count=400 2>&1 | grep -c 'No space'; done", one)
    assert full["output"] == "1\n1\n1\n"

    run("echo mine > ~/.cache/left-behind", one)
    assert run("ls ~/.cache", two)["output"] == "" and run("cat ~/.cache/left-behind", one)["output"] == "mine\n"

    monkeypatch.setattr(sandbox, "TIMEOUT", 1)
    assert run("setsid sleep 6173 & sleep 6173", one) == {"exit_code": None, "output": "stopped: still running after 1 s"}
    # The kernel ends the sandbox's processes when its first one dies, a moment after the kill.
    for _ in range(40):
        if subprocess.run(["pgrep", "-x", "-f", "sleep 6173"], capture_output=True).returncode == 1:
            break
        time.sleep(0.1)
    else:
        pytest.fail("a process of the command outlived its time limit")


@needs_bwrap
@pytest.mark.skipif(not sandbox.capped(), reason="no user systemd: sandboxed commands run without the memory limit here")
def test_a_command_cannot_take_more_memory_than_its_limit(place):
    hog = run("python3 -c 'x = bytearray(3 * 1024**3); print(len(x))'", place / "courses/mine")
    assert hog["exit_code"] != 0 and "3221225472" not in hog["output"]


def test_a_deleted_course_leaves_no_cache_for_the_next_one_with_its_name(place):
    from wise_scholar import app

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Cachy')").lastrowid
    course = db.create_course("Cache leftovers", who)
    for leftover in ("sandbox-cache", "agents"):
        (place / "data" / leftover / course["slug"]).mkdir(parents=True)
    app.delete_course(course["id"])
    assert not (place / "data/sandbox-cache" / course["slug"]).exists() and not (place / "data/agents" / course["slug"]).exists()


def test_the_server_reads_a_bounded_part_of_a_file_however_large(tmp_path):
    with open(tmp_path / "huge.csv", "wb") as f:
        f.truncate(300 * 1024 * 1024)
    assert len(course_files.read_text(tmp_path, "huge.csv")) == course_files.READ_LIMIT


def test_file_tools_stay_inside_the_course_workspace(tmp_path, monkeypatch):
    from wise_scholar import app

    monkeypatch.setattr(db, "WORKSPACE", tmp_path)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Sandy')").lastrowid
    course = db.create_course("Sandboxing", who)
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])["id"]
    workspace = db.workspace(course["slug"])
    (tmp_path / "secret.txt").write_text("not yours")
    (tmp_path / "elsewhere").mkdir()
    (workspace / "link").symlink_to(tmp_path / "secret.txt")
    (workspace / "folder").symlink_to(tmp_path / "elsewhere")
    os.mkfifo(workspace / "pipe")

    assert asyncio.run(tutor.write_file(lesson, "unit1/main.py", "print(1)")) == "written"
    assert asyncio.run(tutor.read_file(lesson, "unit1/main.py")) == "print(1)"
    for path in ("../secret.txt", "link", "folder/new.txt", "/etc/passwd", ".", "unit1", "pipe"):
        assert asyncio.run(tutor.read_file(lesson, path)).startswith("error:"), path
        assert asyncio.run(tutor.write_file(lesson, path, "x")).startswith("error:"), path
    assert (tmp_path / "secret.txt").read_text() == "not yours" and not (tmp_path / "elsewhere" / "new.txt").exists()

    # The exercise card and the check read the listed files outside the sandbox: a planted link reads as missing.
    block = {"data": {"files": ["link", "folder/new.txt", "unit1/main.py"]}}
    assert [f["content"] for f in app._read_files(block, workspace)] == [None, None, "print(1)"]
    posed = asyncio.run(tutor.pose_exercise(lesson, "x", [tutor.ExerciseFile(path="folder/a.py", content="x")], "true"))
    assert posed.startswith("error:") and not (tmp_path / "elsewhere" / "a.py").exists()


def test_a_server_without_commands_offers_no_workspace_tools_and_tells_the_tutor():
    import sys

    listing = "import asyncio; from wise_scholar import tutor; print(' '.join(t.name for t in asyncio.run(tutor.mcp.list_tools())))"
    names = {
        flag: set(subprocess.run([sys.executable, "-c", listing], env={**os.environ, "WISE_SCHOLAR_COMMANDS": flag, "WISE_SCHOLAR_SANDBOX": "0"},
                                 capture_output=True, text=True, check=True).stdout.split())
        for flag in ("0", "1")
    }
    assert names["1"] - names["0"] == {"run_command", "write_file", "read_file", "pose_exercise"}


def test_run_is_refused_and_the_lesson_prompt_says_so_when_commands_are_off(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from wise_scholar import app

    monkeypatch.setattr(db, "WORKSPACE", tmp_path)
    monkeypatch.setattr(sandbox, "COMMANDS", False)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Offline')").lastrowid
    course = db.create_course("No commands", who)
    db.set_concepts(course["id"], [{"title": "M", "concepts": ["c"], "known": []}])
    concept = db.concepts(course["id"])[0]["id"]
    lesson = db.create_lesson(course["id"], "c", "lesson", concept)
    block = db.add_block(lesson, "exercise", "x", {**app.challenge.new(), "files": [], "run": "true", "last_run": None})

    assert app.meta()["commands"] is False
    with pytest.raises(HTTPException) as refused:
        asyncio.run(app.run_exercise(block["id"]))
    assert refused.value.status_code == 409
    assert "[tools] This server runs no code" in app._turn_prompt(db.lesson(lesson), "[event] x")
    monkeypatch.setattr(sandbox, "COMMANDS", True)
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    assert "[tools]" not in app._turn_prompt(db.lesson(lesson), "[event] x")
