#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ws: work on a Wise Scholar exercise in your own editor. pull copies its files into a folder, watch keeps them and the
server's in step, submit runs the exercise's command and sends the work to the tutor. Needs only Python: the server
hands this file out at /api/ws.py."""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.exit("ws.py needs Python 3.10 or later")

import argparse
import hashlib
import json
import os
import stat
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SERVER = "http://127.0.0.1:8321"
STATE = ".ws.json"
CONFLICT = ".conflict"
POLL = 2.0
BACKOFF = 30.0
# The server's course_files.READ_LIMIT: it saves no larger file. Repeated here, as this script runs without the app.
READ_LIMIT = 2_000_000


class Failed(Exception):
    pass


class Unreachable(Failed):
    pass


@dataclass
class Memory:
    """What carries over between rounds: the last error per file, so none repeats, and the size and time of each edited
    file, so watch sends one only once it stopped changing."""

    wait_steady: bool
    said: dict[str, str] = field(default_factory=dict)
    stats: dict[str, tuple[int, int]] = field(default_factory=dict)

    def error(self, path: str, message: str) -> None:
        if self.said.get(path) != message:
            self.said[path] = message
            print(message, file=sys.stderr)

    def forget(self, path: str) -> None:
        self.said.pop(path, None)


def _call(server: str, method: str, path: str, body: dict | None = None, timeout: float | None = 30):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(server + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw)["detail"]
        except (ValueError, KeyError, TypeError):
            detail = raw.decode(errors="replace") or e.reason
        raise Failed(str(detail)) from None
    except OSError as e:
        raise Unreachable(f"cannot reach {server}: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        raise Failed(f"{server} did not answer as Wise Scholar does; check the address") from None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _local(folder: Path, path: str) -> Path:
    """Where an exercise file goes in the pulled folder; never outside it, also through a link."""
    root = folder.resolve()
    resolved = (root / path).resolve()
    if Path(path).is_absolute() or not resolved.is_relative_to(root) or resolved in (root, root / STATE):
        raise Failed(f"{path!r} is not a path inside the exercise folder")
    return root / path


def _read(target: Path) -> bytes | None:
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None


def _write(target: Path, content: str) -> None:
    """Written whole or not at all, through a temporary file beside it; never through a link, wherever it points."""
    if target.is_symlink():
        raise Failed(f"{target.name} is a link; ws writes no file through a link")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o666 & ~_umask()
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        os.unlink(temporary)
        raise


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _load(folder: Path) -> dict:
    damaged = Failed(f"{folder / STATE} is damaged; pull the exercise again into a new folder")
    try:
        state = json.loads((folder / STATE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Failed(f"{folder} holds no pulled exercise; run ws pull first") from None
    except (OSError, ValueError):
        raise damaged from None
    if not (isinstance(state, dict) and isinstance(state.get("exercise"), int) and isinstance(state.get("server"), str)
            and isinstance(files := state.get("files"), dict)
            and all(isinstance(f, dict) and isinstance(f.get("base"), str) and isinstance(f.get("editable"), bool) for f in files.values())):
        raise damaged
    return state


def _save(folder: Path, state: dict) -> None:
    _write(folder / STATE, json.dumps(state, ensure_ascii=False))


def list_exercises(server: str, course: int) -> None:
    for e in _call(server, "GET", f"/api/courses/{course}/exercises"):
        unit = f"{e['unit']}: " if e["unit"] else ""
        print(f"{e['id']:>6}  {'open  ' if e['open'] else 'closed'}  {unit}{e['summary']}")


def pull(server: str, exercise: int, folder: Path) -> None:
    """A file already in the folder that an earlier pull did not write stays as it is; the server's text goes beside it
    as a conflict to merge."""
    known: dict[str, dict] = {}
    if (folder / STATE).exists():
        old = _load(folder)
        if old["exercise"] != exercise:
            raise Failed(f"{folder} holds exercise {old['exercise']}")
        known = old["files"]
        edited = [p for p, f in known.items() if "conflict" in f or _read(_local(folder, p)) not in (None, f["base"].encode())]
        if edited:
            raise Failed(f"changes not sent yet: {', '.join(edited)}; run ws watch or ws submit")
    files = _call(server, "GET", f"/api/blocks/{exercise}/files")
    targets = {f["path"]: _local(folder, f["path"]) for f in files}
    state = {"server": server, "exercise": exercise, "files": {p: e for p, e in known.items() if p in targets}}
    folder.mkdir(parents=True, exist_ok=True)
    _save(folder, state)
    for f in files:
        path, text = f["path"], f["content"]
        if text is None:
            print(f"missing on the server: {path}", file=sys.stderr)
        elif not (f["editable"] or f["kept"]):
            print(f"skipped: {path} is binary or larger than {READ_LIMIT // 1_000_000} MB; it stays on the server", file=sys.stderr)
        elif path not in known and _read(targets[path]) not in (None, text.encode()):
            _write(_local(folder, path + CONFLICT), text)
            state["files"][path] = {"base": text, "editable": f["editable"], "conflict": text}
            print(_conflict(path), file=sys.stderr)
        else:
            _write(targets[path], text)
            state["files"][path] = {"base": text, "editable": f["editable"]}
        _save(folder, state)
    print(f"pulled exercise {exercise} into {folder}")


def _stamp(target: Path) -> tuple[int, int]:
    found = target.stat()
    return found.st_size, found.st_mtime_ns


def _conflict(path: str) -> str:
    return f"conflict: {path} changed on the server too; merge {path}{CONFLICT} into it, then delete {path}{CONFLICT}"


def sync(server: str, folder: Path, state: dict, memory: Memory) -> bool:
    """One round: local edits go to the server, the server's own changes come back to files not edited here. Returns
    whether every local edit is on the server. The poll compares hashes; a file's text comes only once it changed."""
    exercise = state["exercise"]
    listed = {f["path"]: f for f in _call(server, "GET", f"/api/blocks/{exercise}/files?hashes=1")}
    texts: dict[str, dict] = {}

    def theirs(path: str) -> dict:
        if not texts:
            texts.update({f["path"]: f for f in _call(server, "GET", f"/api/blocks/{exercise}/files")})
        return texts[path]

    def keep(path: str, base: str) -> None:
        state["files"][path]["base"] = base
        _save(folder, state)
        memory.forget(path)

    def conflicted(path: str, text: str) -> bool:
        _write(_local(folder, path + CONFLICT), text)
        state["files"][path]["conflict"] = text
        _save(folder, state)
        memory.error(path, _conflict(path))
        return False

    def restore(path: str, info: dict, base: str) -> bool:
        text = base if info["sha256"] == _sha(base) else theirs(path)["content"]
        if text is not None:
            _write(_local(folder, path), text)
            keep(path, text)
            print(f"restored: {path}")
        return True

    def update(path: str, info: dict, base: str, target: Path, mine: bytes) -> bool:
        memory.stats.pop(path, None)
        memory.forget(path)
        if info["sha256"] in (None, _sha(base)):
            return True
        server_file = theirs(path)
        if not (server_file["editable"] or server_file["kept"]):
            memory.error(f"{path} on the server", f"not updated: {path} on the server is now binary or larger than {READ_LIMIT // 1_000_000} MB")
            return True
        if _read(target) != mine:
            return conflicted(path, server_file["content"])
        _write(target, server_file["content"])
        keep(path, server_file["content"])
        print(f"updated from the server: {path}")
        return True

    def send(path: str, info: dict, entry: dict, mine: bytes) -> bool:
        if len(mine) > READ_LIMIT:
            memory.error(path, f"not sent: {path} is larger than {READ_LIMIT // 1_000_000} MB")
            return False
        try:
            text = mine.decode()
        except UnicodeDecodeError:
            memory.error(path, f"not sent: {path} is not UTF-8 text")
            return False
        if not entry["editable"]:
            memory.error(path, f"not sent: {path} cannot be edited on the server")
            return False
        if info["sha256"] == _sha(text):
            keep(path, text)
            return True
        reply = _call(server, "POST", f"/api/blocks/{exercise}/files", {"path": path, "content": text, "base": entry["base"]})
        if reply["saved"] or reply["content"] == text:
            keep(path, text)
            print(f"sent: {path}")
            return True
        return conflicted(path, reply["content"])

    def one(path: str, entry: dict) -> bool:
        if "conflict" in entry:
            if os.path.lexists(_local(folder, path + CONFLICT)):
                memory.error(path, _conflict(path))
                return False
            keep(path, entry.pop("conflict"))
        info = listed.get(path)
        if info is None:
            return True
        target = _local(folder, path)
        base = entry["base"]
        try:
            before = _stamp(target)
        except FileNotFoundError:
            return restore(path, info, base)
        mine = _read(target)
        try:
            after = _stamp(target)
        except FileNotFoundError:
            after = None
        if mine is None or after is None:
            return False
        if mine == base.encode():
            return update(path, info, base, target, mine)
        if before != after or (memory.wait_steady and memory.stats.get(path) != after):
            memory.stats[path] = after
            return False
        return send(path, info, entry, mine)

    synced = True
    for path, entry in state["files"].items():
        try:
            synced &= one(path, entry)
        except Unreachable:
            raise
        except (Failed, OSError) as e:
            memory.error(path, f"not sent: {path}: {e}")
            synced = False
    return synced


def watch(folder: Path, state: dict) -> None:
    print(f"watching {folder}; Ctrl+C stops")
    memory, delay, away = Memory(wait_steady=True), POLL, False
    while True:
        try:
            sync(state["server"], folder, state, memory)
            if away:
                print("reached the server again")
            delay, away = POLL, False
        except Unreachable as e:
            if not away:
                print(f"{e}; trying again, at least every {BACKOFF:.0f} s", file=sys.stderr)
            delay, away = min(delay * 2, BACKOFF), True
        except Failed as e:
            memory.error("", str(e))
        time.sleep(delay)


def submit(folder: Path, state: dict, answer: str) -> None:
    server, exercise = state["server"], state["exercise"]
    if not sync(server, folder, state, Memory(wait_steady=False)):
        raise Failed("not submitted: some changes are not on the server")
    try:
        run = _call(server, "POST", f"/api/blocks/{exercise}/run", timeout=None)
    except Failed as e:
        raise Failed(f"not run, so not sent to the tutor: {e}") from None
    print(run["output"], end="" if run["output"].endswith("\n") else "\n")
    print("stopped at the time limit" if run["exit_code"] is None else f"exit code {run['exit_code']}")
    reply = _call(server, "POST", f"/api/blocks/{exercise}/check", {"answer": answer})
    print(json.dumps(reply, ensure_ascii=False) if reply else "sent to the tutor; their reply comes in the lesson")


def main(argv: list[str] | None = None) -> int:
    address = f"the Wise Scholar address (default: WS_SERVER, else the pulled folder's, else {DEFAULT_SERVER})"
    parser = argparse.ArgumentParser(prog="ws", description=__doc__)
    parser.add_argument("--server", help=address)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server", default=argparse.SUPPRESS, help=address)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", parents=[common], help="list a course's exercises")
    listing.add_argument("course", type=int)
    pulling = commands.add_parser("pull", parents=[common], help="copy an exercise's files into a folder")
    pulling.add_argument("exercise", type=int)
    pulling.add_argument("folder", nargs="?", type=Path, help="default: exercise-<id>")
    watching = commands.add_parser("watch", parents=[common], help="send your edits as you save them, and bring in the server's")
    watching.add_argument("folder", nargs="?", type=Path, default=Path("."))
    submitting = commands.add_parser("submit", parents=[common], help="send your edits, run the exercise and ask the tutor to check it")
    submitting.add_argument("folder", nargs="?", type=Path, default=Path("."))
    submitting.add_argument("--answer", default="", help="a written answer to send with it")
    args = parser.parse_args(argv)

    server = args.server or os.environ.get("WS_SERVER")
    try:
        if args.command == "list":
            list_exercises((server or DEFAULT_SERVER).rstrip("/"), args.course)
        elif args.command == "pull":
            pull((server or DEFAULT_SERVER).rstrip("/"), args.exercise, args.folder or Path(f"exercise-{args.exercise}"))
        else:
            state = _load(args.folder)
            if server:
                state["server"] = server.rstrip("/")
            if args.command == "watch":
                watch(args.folder, state)
            else:
                submit(args.folder, state, args.answer)
        return 0
    except (Failed, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
