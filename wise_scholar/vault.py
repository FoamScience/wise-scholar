"""An Obsidian vault folder on disk that the server keeps current: each course's notes are rewritten a few seconds
after the course changes, and files the course no longer produces are removed through a manifest. Set with
WISE_SCHOLAR_VAULT; nothing happens without it. The notes it writes are its own: a learner's edit to one is
overwritten at the next change, a learner's own files are never touched."""

import asyncio
import collections
import json
import logging
import os
import threading
from pathlib import Path

from . import db, hub, obsidian

VAULT = Path(os.environ["WISE_SCHOLAR_VAULT"]).expanduser() if os.environ.get("WISE_SCHOLAR_VAULT") else None
# Seconds of quiet after the last change before a course is written.
SETTLE = 5
MANIFEST = ".wise-scholar.json"
# Which folder each course was last written to, so a renamed course leaves no folder behind.
ROOTS = f"{obsidian.FOLDER}/{MANIFEST}"

log = logging.getLogger(__name__)
_pending: dict[int, asyncio.TimerHandle] = {}
_locks: dict[int, threading.Lock] = collections.defaultdict(threading.Lock)
_loop: asyncio.AbstractEventLoop | None = None


def enabled() -> bool:
    return VAULT is not None


def _inside(vault: Path, path: str) -> Path | None:
    """A manifest entry as a path, or None when it would reach outside the vault."""
    target = vault / path
    return target if ".." not in Path(path).parts and not Path(path).is_absolute() else None


def _write_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes(content)
    tmp.replace(target)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write(course_id: int, vault: Path | None = None) -> Path | None:
    """Write the course's notes into the vault; returns the course folder, or None for a course that is gone."""
    vault = vault or VAULT
    with _locks[course_id]:
        if not db.course(course_id):
            return None
        built = obsidian.Vault(course_id)
        files = built.build()
        roots = _read_json(vault / ROOTS, {})
        previous = roots.get(str(course_id))
        if previous and previous != built.root:
            _remove_root(vault, previous)
        folder = vault / built.root
        before = set(_read_json(folder / MANIFEST, []))
        for path, content in files.items():
            target = vault / path
            if not target.exists() or target.read_bytes() != content:
                _write_atomic(target, content)
        _write_atomic(folder / MANIFEST, json.dumps(sorted(files), ensure_ascii=False, indent=0).encode())
        _write_atomic(vault / ROOTS, json.dumps({**roots, str(course_id): built.root}, ensure_ascii=False, indent=0).encode())
        # Only files this server wrote before are removed: a file of the learner's own is never ours.
        for stale in before - set(files):
            if (target := _inside(vault, stale)) and target.is_relative_to(folder):
                target.unlink(missing_ok=True)
        return folder


def _remove_root(vault: Path, root: str) -> None:
    folder = vault / root
    paths = [p for p in _read_json(folder / MANIFEST, []) if (t := _inside(vault, p)) and t.is_relative_to(folder)]
    for path in paths:
        (vault / path).unlink(missing_ok=True)
    (folder / MANIFEST).unlink(missing_ok=True)
    parents = {folder}
    for path in paths:
        parent = (vault / path).parent
        while parent != folder and parent.is_relative_to(folder):
            parents.add(parent)
            parent = parent.parent
    for parent in sorted(parents, key=lambda f: -len(f.parts)):
        try:
            parent.rmdir()
        except OSError:
            pass


def remove(course_id: int, vault: Path | None = None) -> None:
    """Remove what this server wrote for a deleted course, leaving any other file in its folder."""
    vault = vault or VAULT
    if timer := _pending.pop(course_id, None):
        timer.cancel()
    with _locks[course_id]:
        roots = _read_json(vault / ROOTS, {})
        if root := roots.pop(str(course_id), None):
            _remove_root(vault, root)
            _write_atomic(vault / ROOTS, json.dumps(roots, ensure_ascii=False, indent=0).encode())


def _schedule(course_id: int, event: dict) -> None:
    """Debounced: one write per course once it has been quiet for SETTLE seconds. Safe from any thread."""
    if _loop is None:
        return
    _loop.call_soon_threadsafe(_arm, course_id)


def _arm(course_id: int) -> None:
    if timer := _pending.pop(course_id, None):
        timer.cancel()
    _pending[course_id] = _loop.call_later(SETTLE, lambda: _pending.pop(course_id, None) and None or _loop.create_task(_write_later(course_id)))


async def _write_later(course_id: int) -> None:
    try:
        await asyncio.to_thread(write, course_id)
    except Exception:
        log.exception("vault write failed for course %s", course_id)


async def _write_all() -> None:
    for course in db.rows("SELECT id FROM courses ORDER BY id"):
        await _write_later(course["id"])


async def start() -> None:
    """Follow changes from now on, and write every course once in the background."""
    global _loop
    if not enabled():
        return
    try:
        VAULT.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error("WISE_SCHOLAR_VAULT %s cannot be used: %s", VAULT, e)
        return
    _loop = asyncio.get_running_loop()
    hub.listen(_schedule)
    _loop.create_task(_write_all())


async def stop() -> None:
    """Write what is still pending, so the vault holds the last changes."""
    due = list(_pending)
    for timer in _pending.values():
        timer.cancel()
    _pending.clear()
    for course_id in due:
        await _write_later(course_id)
