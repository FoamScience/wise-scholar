"""Old courses lose their files on disk, never their record: the workspace, the command cache and the agent sessions
go; lessons, cards, chat, mistakes and the command log stay, and an exercise keeps a text copy of its files."""

import argparse
import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import course_files, db, sandbox

# WISE_SCHOLAR_KEEP_DAYS: a course untouched for this long has its files cleaned up.
KEEP_DAYS = int(os.environ.get("WISE_SCHOLAR_KEEP_DAYS", "90"))
EVERY = 6 * 3600
STAMP = "%Y-%m-%d %H:%M:%S"

log = logging.getLogger(__name__)


def folders(course: dict) -> list[Path]:
    slug = course["slug"]
    return [db.WORKSPACE / slug, db.DB_PATH.parent / "sandbox-cache" / slug, db.DB_PATH.parent / "agents" / slug]


def last_activity(course_id: int) -> str | None:
    """The newest block, message or command of the course, as 'YYYY-MM-DD HH:MM:SS' in UTC."""
    row = db.row(
        "SELECT MAX(stamp) AS last FROM ("
        "SELECT substr(replace(b.created, 'T', ' '), 1, 19) AS stamp FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? "
        "UNION ALL SELECT substr(replace(m.created, 'T', ' '), 1, 19) FROM messages m JOIN lessons l ON l.id = m.lesson_id WHERE l.course_id = ? "
        "UNION ALL SELECT substr(replace(started, 'T', ' '), 1, 19) FROM commands WHERE course_id = ?)",
        course_id, course_id, course_id,
    )
    return row["last"] if row else None


def stale(now: datetime | None = None) -> list[dict]:
    """Courses whose files are due for cleanup: untouched for KEEP_DAYS, not yet cleaned since their last activity,
    and with something on disk."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime(STAMP)
    out = []
    for course in db.rows("SELECT * FROM courses ORDER BY id"):
        last = last_activity(course["id"])
        if not last or last >= cutoff:
            continue
        if course["cleaned"] and course["cleaned"] >= last:
            continue
        if any(f.exists() for f in folders(course)):
            out.append(course)
    return out


def keep_exercise_files(course: dict) -> None:
    """A text copy of each exercise's files goes into its block, so the record still shows what was written."""
    workspace = db.WORKSPACE / course["slug"]
    for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course["id"]):
        for block in db.blocks(lesson["id"]):
            if block["kind"] != "exercise":
                continue
            kept = {}
            for path in block["data"].get("files", []):
                content = course_files.read_text(workspace, path) if workspace.exists() else None
                if content is not None:
                    kept[path] = content
            if kept:
                db.set_block_data(block["id"], {**block["data"], "files_kept": kept})


def clean(course: dict, busy=lambda course_id: False, dry_run: bool = False) -> int:
    """Remove the course's folders; returns the bytes they held, or 0 when the course was busy or had nothing.
    A folder that will not go leaves the course unstamped, so the next pass tries again."""
    workspace = db.WORKSPACE / course["slug"]
    if busy(course["id"]) or sandbox.online(workspace):
        return 0
    present = [f for f in folders(course) if f.exists()]
    size = sum(sandbox.usage(f) for f in present)
    if dry_run:
        return size
    keep_exercise_files(course)
    try:
        for folder in present:
            shutil.rmtree(folder)
    except OSError as e:
        log.warning("cleanup of %s stopped: %s", course["topic"], e)
        return 0
    db.conn.execute("UPDATE courses SET cleaned = ? WHERE id = ?", (datetime.now(timezone.utc).strftime(STAMP), course["id"]))
    return size


def run(busy=lambda course_id: False, dry_run: bool = False) -> list[tuple[dict, int]]:
    """One pass over the stale courses, without the server's per-course locks: for the command line, with the server stopped."""
    done = []
    for course in stale():
        size = clean(course, busy, dry_run)
        if size:
            done.append((course, size))
            log.info("%s %s: %d MB of files", "would clean" if dry_run else "cleaned", course["topic"], size // (1024 * 1024))
    return done


async def sweep(busy) -> None:
    """One pass inside the server: each course is cleaned under its command lock, so no Run writes into a folder
    that is being removed."""
    for course in await asyncio.to_thread(stale):
        workspace = (db.WORKSPACE / course["slug"]).resolve()
        async with sandbox._course[workspace]:
            await asyncio.to_thread(clean, course, busy)


async def forever(busy) -> None:
    """Runs at startup and then every EVERY seconds, in the server's own loop."""
    while True:
        try:
            await sweep(busy)
        except Exception:
            log.exception("cleanup failed")
        await asyncio.sleep(EVERY)


def main() -> None:
    parser = argparse.ArgumentParser(description="clean up the files of courses untouched for WISE_SCHOLAR_KEEP_DAYS days; prints what would go unless --delete is given. Run it with the server stopped.")
    parser.add_argument("--delete", action="store_true", help="remove the files instead of only listing them")
    args = parser.parse_args()
    for course, size in run(dry_run=not args.delete):
        print(f"{'cleaned' if args.delete else 'would clean'}: {course['topic']} ({size / (1024 * 1024):.1f} MB)")


if __name__ == "__main__":
    main()
