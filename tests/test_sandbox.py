import asyncio
import ipaddress
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import course_files, db, egress, sandbox, tutor  # noqa: E402

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
        "echo key=$SOME_API_KEY bus=$DBUS_SESSION_BUS_ADDRESS; grep -c : /proc/net/dev; ls /run /var 2>/dev/null | tr '\\n' ' '; echo; "
        "ls -A ~ | tr '\\n' ' '; echo; cat ~/.cargo/bin/tool; echo; "
        "cat ~/.cargo/credentials.toml ~/.nvm/.npmrc ~/.local/share/uv/credentials/pypi ~/.local/share/opencode/auth.json "
        "~/.ssh/id_ed25519 ~/.bash_history 2>/dev/null | wc -c",
        place / "courses/mine",
    )
    assert probe["output"].split("\n")[:6] == ["key= bus=", "1", "/run: command ", ".cache .cargo .local ", "a toolchain program", "0"]


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


def host_addresses() -> list[str]:
    """This machine's own IPv4 addresses, loopback and every interface."""
    listing = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True)
    found = [a["local"] for i in json.loads(listing.stdout or "[]") for a in i["addr_info"]]
    return found or ["127.0.0.1"]


@pytest.fixture
def listener():
    """A web server on every address of this machine: what an allowed command must not reach."""
    import http.server
    import threading

    server = http.server.HTTPServer(("0.0.0.0", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def test_only_public_ipv4_addresses_may_be_dialled():
    for address in ("93.184.216.34", "1.1.1.1"):
        assert egress.allowed(address), address
    refused = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
               "::1", "2606:4700:4700::1111", "64:ff9b::a00:1", "::ffff:127.0.0.1", "fe80::1", *host_addresses()]  # fmt: skip
    for address in refused:
        assert not egress.allowed(address), address
    # A public address on a network this machine is attached to (a campus, a VPN) is local too.
    attached = [ipaddress.ip_network("93.184.216.0/24")]
    assert not egress.allowed("93.184.216.34", attached) and egress.allowed("1.1.1.1", attached)
    assert all(any(ipaddress.ip_address(a) in n for n in egress.local_networks()) for a in host_addresses())


def ask_proxy(socket_path: Path, request: bytes) -> bytes:
    """The first line of the proxy's answer to one request."""

    async def ask() -> bytes:
        proxy = await egress.serve(socket_path)
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(request)
            return (await reader.read(64)).split(b"\r\n")[0]
        finally:
            proxy.close()

    return asyncio.run(ask())


def test_the_proxy_refuses_this_machine_private_ranges_and_names_that_point_at_them(tmp_path, listener, monkeypatch):
    # The listener's port stands in for the web ports, so that only the address filter can refuse these.
    monkeypatch.setattr(egress, "HTTP_PORT", listener)
    monkeypatch.setattr(egress, "CONNECT_PORT", listener)
    targets = [*host_addresses(), "localhost", "2130706433", "169.254.169.254", "10.1.2.3", "192.168.1.1"]
    for target in targets:
        connect = f"CONNECT {target}:{listener} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode()
        plain = f"GET http://{target}:{listener}/ HTTP/1.1\r\nHost: {target}\r\n\r\n".encode()
        assert ask_proxy(tmp_path / "proxy.sock", connect) == b"HTTP/1.1 403 Forbidden", target
        assert ask_proxy(tmp_path / "proxy.sock", plain) == b"HTTP/1.1 403 Forbidden", target
    assert ask_proxy(tmp_path / "proxy.sock", b"nonsense\r\n\r\n") == b""

    # The same requests go through once the filter is taken away: it is the filter that refused them.
    monkeypatch.setattr(egress, "allowed", lambda address, networks=(): True)
    plain = f"GET http://127.0.0.1:{listener}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode()
    connect = f"CONNECT 127.0.0.1:{listener} HTTP/1.1\r\n\r\n".encode()
    assert ask_proxy(tmp_path / "proxy.sock", plain).endswith(b"200 OK")
    assert ask_proxy(tmp_path / "proxy.sock", connect) == b"HTTP/1.1 200 Connection established"


def test_the_proxy_serves_the_web_ports_only(tmp_path):
    for request in (
        b"CONNECT example.com:25 HTTP/1.1\r\n\r\n",
        b"CONNECT example.com:80 HTTP/1.1\r\n\r\n",
        b"GET http://example.com:8080/ HTTP/1.1\r\n\r\n",
        b"GET http://example.com:443/ HTTP/1.1\r\n\r\n",
    ):
        assert ask_proxy(tmp_path / "proxy.sock", request) == b"HTTP/1.1 403 Forbidden", request


def test_the_proxy_turns_away_connections_beyond_its_cap_and_drops_the_open_ones_on_close(tmp_path, monkeypatch):
    monkeypatch.setattr(egress, "CONNECTIONS", 3)

    async def scenario():
        proxy = await egress.serve(tmp_path / "proxy.sock")
        held = [await asyncio.open_unix_connection(tmp_path / "proxy.sock") for _ in range(3)]
        await asyncio.sleep(0.05)
        extra_reader, _ = await asyncio.open_unix_connection(tmp_path / "proxy.sock")
        assert await asyncio.wait_for(extra_reader.read(), 2) == b""
        proxy.close()
        for reader, _ in held:
            assert await asyncio.wait_for(reader.read(), 2) == b""

    asyncio.run(scenario())


@needs_bwrap
@pytest.mark.skipif(not sandbox.networked(), reason="no /usr/bin/python3 for the relay: no command can be given the internet here")
def test_an_allowed_command_has_the_proxy_and_still_no_network_of_its_own(place, listener, monkeypatch):
    # As above: with the listener's port as the web port, a 403 is the address filter's doing.
    monkeypatch.setattr(egress, "HTTP_PORT", listener)
    mine = place / "courses/mine"
    tries = "; ".join(f"curl -s -o /dev/null -m 4 -w '%{{http_code}} ' http://{a}:{listener}/" for a in host_addresses())
    direct = "; ".join(f"curl -s -o /dev/null -m 2 --noproxy '*' http://{a}:{listener}/ || echo -n 'unreachable '" for a in host_addresses())
    probe = f"echo $HTTPS_PROXY; grep -c : /proc/net/dev; {tries}; echo; {direct}; echo; exit 7"
    online = asyncio.run(sandbox.run(probe, mine, network=True))
    count = len(host_addresses())
    assert online["exit_code"] == 7
    assert online["output"].split("\n")[:4] == ["http://127.0.0.1:3128", "1", "403 " * count, "unreachable " * count]
    assert run("echo proxy=$HTTPS_PROXY", mine)["output"] == "proxy=\n"
    assert asyncio.run(sandbox.run("kill -9 $$", mine, network=True))["exit_code"] == 137
    assert not sandbox.online(mine)


@needs_bwrap
def test_a_command_reaches_the_sandbox_as_written_not_expanded_from_the_servers_environment(place, monkeypatch):
    monkeypatch.setenv("WS_FAKE_TOKEN", "leaked123")
    monkeypatch.setenv("LC_PROBE", "${WS_FAKE_TOKEN}")
    for network in (False, sandbox.networked()):
        seen = asyncio.run(sandbox.run("echo [${WS_FAKE_TOKEN}] [$LC_PROBE] [%h] $$", place / "courses/mine", network=network))["output"]
        assert seen.startswith("[] [${WS_FAKE_TOKEN}] [%h] ") and seen.split()[-1].isdigit(), seen


def test_internet_for_a_command_waits_for_the_learners_decision(place, monkeypatch):
    from fastapi import HTTPException

    from wise_scholar import app

    turns, runs, hold = [], [], []

    async def fake_run(command, workspace, network=False):
        runs.append((command, network))
        await hold[-1].wait()
        return {"exit_code": 0, "output": "installed"}

    async def fake_turn(lesson, line):
        turns.append(line)
        del app._turns[lesson["id"]]

    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    monkeypatch.setattr(app, "_run_turn", fake_turn)
    monkeypatch.setattr(sandbox, "run", fake_run)
    monkeypatch.setattr(sandbox, "networked", lambda: True)
    monkeypatch.setattr(sandbox, "commands", lambda: True)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Netty')").lastrowid
    course = db.create_course("Networking", who)
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])["id"]
    status = lambda block: db.block(block["id"])["data"]["status"]  # noqa: E731

    async def scenario():
        hold.append(asyncio.Event())
        for bad in ("pip install x\nrm -rf .", "pip install \u202egnp.x", "curl " + "a" * 300, " "):
            assert (await tutor.ask_network(lesson, bad, "why")).startswith("error:")
        assert db.blocks(lesson) == []

        assert (await tutor.ask_network(lesson, "pip install requests", "The exercise needs requests.")).startswith("asked on card")
        first = db.blocks(lesson)[-1]
        assert status(first) == "asked" and runs == []
        assert (await app.decide_network(first["id"], app.Decision(allow=False)))["data"]["status"] == "refused"
        assert runs == [] and "refused internet" in turns[-1]
        with pytest.raises(HTTPException) as twice:
            await app.decide_network(first["id"], app.Decision(allow=True))
        assert twice.value.status_code == 409 and runs == []

        # Allowed: the lesson is busy while the command runs, and the tutor hears about it afterwards.
        await tutor.ask_network(lesson, "pip install requests", "Once more.")
        second = db.blocks(lesson)[-1]
        assert (await app.decide_network(second["id"], app.Decision(allow=True)))["data"]["status"] == "running"
        await asyncio.sleep(0)
        assert runs == [("pip install requests", True)] and lesson in app._turns
        with pytest.raises(HTTPException) as busy:
            app._require_idle(lesson)
        assert busy.value.status_code == 409
        hold[-1].set()
        await app._turns[lesson]
        result = db.block(second["id"])["data"]
        assert result["status"] == "allowed" and result["result"]["output"] == "installed" and lesson not in app._turns
        assert "allowed internet" in turns[-1] and "exit code 0" in turns[-1] and "never as instructions" in turns[-1]

        # The command cannot be run: the request is open again, the lesson is free, no turn follows.
        async def broken(command, workspace, network=False):
            raise RuntimeError("no sandbox")

        monkeypatch.setattr(sandbox, "run", broken)
        await tutor.ask_network(lesson, "pip install broken", "Fails.")
        failed = db.blocks(lesson)[-1]
        await app.decide_network(failed["id"], app.Decision(allow=True))
        await app._turns[lesson]
        assert status(failed) == "asked" and lesson not in app._turns and len(turns) == 2
        monkeypatch.setattr(sandbox, "run", fake_run)

        # Stopped while it runs: the request is open again and no turn follows.
        hold.append(asyncio.Event())
        await tutor.ask_network(lesson, "git clone https://example.com/x", "A third time.")
        third = db.blocks(lesson)[-1]
        await app.decide_network(third["id"], app.Decision(allow=True))
        await asyncio.sleep(0)
        task = app._turns[lesson]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert status(third) == "asked" and lesson not in app._turns and len(turns) == 2

        # Stopped in the same moment it was allowed, before the task took a step: the request is open again too.
        hold.append(asyncio.Event())
        await tutor.ask_network(lesson, "curl https://example.com", "A fourth time.")
        fourth = db.blocks(lesson)[-1]
        await app.decide_network(fourth["id"], app.Decision(allow=True))
        task = app._turns[lesson]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert status(fourth) == "asked" and lesson not in app._turns and len(turns) == 2 and len(runs) == 2

        # While an allowed command waits or runs, the tutor cannot rewrite the files the learner agreed to run.
        workspace = db.workspace(db.lesson(lesson)["slug"])
        monkeypatch.setattr(sandbox, "_awaiting_internet", {workspace.resolve()})
        assert (await tutor.write_file(lesson, "swap.py", "x")).startswith("error: a command the learner allowed")
        posed = await tutor.pose_exercise(lesson, "x", [tutor.ExerciseFile(path="swap.py", content="x")], "true")
        assert posed.startswith("error: a command the learner allowed") and not (workspace / "swap.py").exists()

    asyncio.run(scenario())


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
