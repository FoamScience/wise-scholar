import asyncio

from fastapi import HTTPException

from .. import app as core
from .. import db, hub
from ..tools import contributions as contribution_tools
from ..app import LOCALE_NAMES, _lesson, _lesson_view, _untrusted, app, log
from .sharing import RECAP_PREVIEW, _recap_course

# --- Open-source contributions: work on real projects that puts a finished course to use, found once by a turn of its
# own when the recap opens, and taken up in a lesson where the tutor guides and reviews.
_contributing: dict[int, asyncio.Task] = {}
_contribute_failed: set[int] = set()  # tried in this process and failed: only the learner's asking tries again before a restart


def _contribute_prompt(course: dict, locale: str) -> str:
    units = db.concept_view(course["id"])
    return "\n".join([
        f"[state] course_id={course['id']}",
        f"[language] Write in {LOCALE_NAMES[locale]}; repository names, code and identifiers stay as they are.",
        f"[course] {course['topic']} | level at the start: {course['level'] or 'unknown'} | wanted: {_untrusted(course['details'] or '') or 'not said'}",
        "[units] " + "; ".join(f"{u['title']}: " + ("not started" if u["mastery"] is None else f"{u['mastery']:.0%}") for u in units),
        *(f"[project] {k['title']}: {_untrusted(k['brief'])}" for k in db.capstones(course["id"])),
    ])


async def _find(course: dict, finished: str) -> None:
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? ORDER BY id LIMIT 1", course["id"])["id"])
    job = {"finished": finished, "seen": set(), "calls": 0, "done": False}
    contribution_tools.contribution_jobs[course["id"]] = job
    try:
        prompt = await asyncio.to_thread(_contribute_prompt, course, lesson["locale"])
        ok = await core._background_turn(lesson, prompt, "contribute", "open-source contributions")
    finally:
        contribution_tools.contribution_jobs.pop(course["id"], None)
    if not ok or not job["done"]:
        _contribute_failed.add(course["id"])


def _start_finding(course: dict, finished: str) -> None:
    course_id = course["id"]

    async def run() -> None:
        try:
            await _find(course, finished)
        except Exception:
            log.exception("contributions of course %s", course_id)
            _contribute_failed.add(course_id)
        finally:
            _contributing.pop(course_id, None)
            hub.publish(course_id, {"type": "contributions.written"})

    _contributing[course_id] = asyncio.create_task(run())


def _state(course_id: int) -> dict:
    return {"contributions": db.contributions(course_id), "running": course_id in _contributing, "failed": course_id in _contribute_failed}


def _finished(course_id: int, preview: bool) -> str:
    """What the suggestions are written for: the course's finish, or a preview of a course still running."""
    state = db.sync_recap(course_id)
    if state and state["finished"]:
        return state["finished"]
    if preview and RECAP_PREVIEW:
        return "preview"
    raise HTTPException(409, "this course is not finished yet")


@app.get("/api/courses/{course_id}/contributions")
async def list_contributions(course_id: int, preview: bool = False) -> dict:
    """The recap's open-source contributions; they are looked for the first time the recap opens after the course is
    finished, and again after it is finished anew."""
    course = _recap_course(course_id)
    finished = _finished(course_id, preview)
    if course["contributions_for"] != finished and course_id not in _contributing and course_id not in _contribute_failed:
        _start_finding(course, finished)
    return _state(course_id)


@app.post("/api/courses/{course_id}/contributions/find", status_code=202)
async def find_contributions(course_id: int, preview: bool = False) -> dict:
    """The learner asked for the search again, after a failure or for other suggestions."""
    course = _recap_course(course_id)
    finished = _finished(course_id, preview)
    if course_id not in _contributing:
        _contribute_failed.discard(course_id)
        _start_finding(course, finished)
    return _state(course_id)


def _contribution(contribution_id: int) -> dict:
    found = db.contribution(contribution_id)
    if not found:
        raise HTTPException(404, "no such contribution")
    return found


@app.post("/api/contributions/{contribution_id}/dismiss")
def dismiss_contribution(contribution_id: int) -> dict:
    found = _contribution(contribution_id)
    if found["status"] == "open":
        db.conn.execute("UPDATE contributions SET status = 'dismissed' WHERE id = ?", (contribution_id,))
    return _state(found["course_id"])


def _start_line(c: dict) -> str:
    issue = f"\nIssue: {c['issue']}" if c["issue"] else "\nNo issue asks for it yet."
    return (
        f"[event] The learner takes on an open-source contribution to https://github.com/{c['repo']}: {_untrusted(c['title'])} "
        f"({'an afternoon' if c['size'] == 'small' else 'a few weeks'}).\nGap: {_untrusted(c['gap'])}\n"
        f"Uses: {_untrusted(c['uses'])}\nFirst step: {_untrusted(c['first_step'])}{issue}"
    )


@app.post("/api/contributions/{contribution_id}/start")
async def start_contribution(contribution_id: int) -> dict:
    """The lesson where the tutor guides the contribution; the same lesson once it is started."""
    found = _contribution(contribution_id)
    if found["lesson_id"]:
        return _lesson_view(found["lesson_id"])
    lesson_id = db.create_lesson(found["course_id"], found["title"], "contribution")
    db.conn.execute("UPDATE contributions SET status = 'started', lesson_id = ? WHERE id = ?", (lesson_id, contribution_id))
    view = _lesson_view(lesson_id)
    hub.publish(found["course_id"], {"type": "lesson.created", "lesson": view})
    core._start_turn(_lesson(lesson_id), _start_line(found))
    return view
