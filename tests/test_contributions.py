import asyncio
import base64
import os
import tempfile
from uuid import uuid4

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from wise_scholar import app, db, github  # noqa: E402
from wise_scholar.routes import contributions as contribution_routes  # noqa: E402
from wise_scholar.tools import contributions as contribution_tools  # noqa: E402

PUMPS = [{"title": "Impeller", "concepts": ["Slip", "Eye"], "known": []}]
REPO = {
    "full_name": "Pumps/impy", "stargazers_count": 40, "language": "Python", "pushed_at": "2026-10-01T00:00:00Z",
    "license": {"spdx_id": "MIT"}, "open_issues_count": 3, "description": "Pump  sizing\nin Python", "default_branch": "main",
    "owner": {"login": "pumps"},
}
SOURCE = "import math\n\n\ndef specific_speed(Q, H, n):\n    return n * Q**0.5 / H**0.75\n\n\nclass Impeller:\n    pass\n"
GITHUB = {
    "/search/repositories": {"items": [REPO]},
    "/repos/Pumps/impy": REPO,
    "/repos/Pumps/impy/git/trees/main": {"tree": [
        {"type": "blob", "path": "impy/pump.py"}, {"type": "blob", "path": "README.md"},
        {"type": "blob", "path": "CONTRIBUTING.md"}, {"type": "tree", "path": "impy"},
    ]},
    "/repos/Pumps/impy/issues": [
        {"number": 7, "title": "Add a slip factor", "labels": [{"name": "good first issue"}], "updated_at": "2026-09-01T00:00:00Z", "comments": 2},
        {"number": 8, "title": "A pull request", "labels": [], "updated_at": "2026-09-01T00:00:00Z", "comments": 0, "pull_request": {}},
    ],
    "/repos/Pumps/impy/pulls": [
        {"merged_at": "2026-09-01", "user": {"login": "pumps"}}, {"merged_at": "2026-09-02", "user": {"login": "ada"}},
        {"merged_at": None, "user": {"login": "ben"}},
    ],
    "/repos/Pumps/impy/contents/impy/pump.py": {"type": "file", "encoding": "base64", "content": base64.b64encode(SOURCE.encode()).decode()},
}


@pytest.fixture
def fake_github(monkeypatch):
    asked = []

    async def get(path, params=None, text_match=False):
        asked.append(path)
        if path not in GITHUB:
            raise github.GitHubError("not found on GitHub")
        return GITHUB[path]

    monkeypatch.setattr(github, "_get", get)
    return asked


def _finished_course() -> int:
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Contributor {uuid4()}",)).lastrowid
    course = db.create_course("Pump design", who)["id"]
    db.set_concepts(course, PUMPS)
    db.create_lesson(course, "Interview", "interview")
    for concept in db.concepts(course):
        lesson = db.create_lesson(course, concept["title"], "lesson", concept["id"])
        db.conn.execute("INSERT INTO blocks (lesson_id, kind, markdown, data) VALUES (?, 'done', 'done', '{}')", (lesson,))
    return course


def _entry(**changes) -> contribution_tools.Contribution:
    fields = {"repo": "Pumps/impy", "title": "Add Wiesner's slip factor", "size": "small", "gap": "No slip correction.",
              "uses": "Blade count and slip", "first_step": "Comment on issue 7.", "issue": "https://github.com/Pumps/impy/issues/7"}
    return contribution_tools.Contribution(**{**fields, **changes})


def test_github_answers_are_trimmed_to_summaries(fake_github, monkeypatch):
    found = asyncio.run(github.find_repos("pump design"))
    assert found == "Pumps/impy ★40, Python, pushed 2026-10-01, MIT, 3 open issues and PRs — Pump sizing in Python"
    name, overview = asyncio.run(github.repo_overview("https://github.com/Pumps/impy/"))
    assert name == "Pumps/impy"
    assert "2 of its last 3 closed PRs merged, by 1 people besides the owner" in overview
    assert "contributing guide: CONTRIBUTING.md" in overview
    assert "Pumps/impy#7 [good first issue]" in overview and "A pull request" not in overview
    assert overview.endswith("[source files] 1\nimpy/pump.py")
    outline = asyncio.run(github.file_outline("Pumps/impy", "impy/pump.py"))
    assert outline == "impy/pump.py, 9 lines\n4: def specific_speed(Q, H, n):\n8: class Impeller:"
    assert asyncio.run(github.read_lines("Pumps/impy", "impy/pump.py", 4)).startswith("4: def specific_speed")
    with pytest.raises(github.GitHubError, match="owner/name"):
        asyncio.run(github.repo_overview("not a repo"))
    monkeypatch.setattr(github, "TOKEN", "")
    with pytest.raises(github.GitHubError, match="needs WISE_SCHOLAR_GITHUB_TOKEN"):
        asyncio.run(github.search_code("Pumps/impy", "slip"))


def test_a_contribute_turn_suggests_only_repositories_it_looked_at_within_its_budget(fake_github, monkeypatch):
    course = _finished_course()
    job = {"finished": "2026-10-10 10:00:00", "seen": set(), "calls": 0, "done": False}
    monkeypatch.setitem(contribution_tools.contribution_jobs, course, job)
    suggest = lambda entries: asyncio.run(contribution_tools.suggest_contributions(course, entries))  # noqa: E731

    assert suggest([_entry()]).startswith("error: Pumps/impy was not looked at")
    assert "Pumps/impy ★40" in asyncio.run(contribution_tools.look_at_repo(course, "Pumps/impy"))
    assert "issue must be the address of an issue of Pumps/impy" in suggest([_entry(issue="https://github.com/Other/repo/issues/7")])
    assert suggest([_entry(), _entry()]) == "error: two contributions have the same title"
    assert suggest([_entry(title=f"Change {n}") for n in range(6)]) == "error: give 0 to 5 contributions"
    assert suggest([_entry(), _entry(repo="pumps/IMPY", title="An NPSHr estimate", size="project", issue="")]) == "recorded"
    assert job["done"]
    assert [(c["title"], c["size"], c["issue"]) for c in db.contributions(course)] == [
        ("Add Wiesner's slip factor", "small", "https://github.com/Pumps/impy/issues/7"), ("An NPSHr estimate", "project", None),
    ]
    assert db.course(course)["contributions_for"] == "2026-10-10 10:00:00"

    job["calls"] = contribution_tools.GITHUB_CALLS
    assert asyncio.run(contribution_tools.find_repos(course, "pumps")).startswith("error: over 30 GitHub calls")
    assert asyncio.run(contribution_tools.find_repos(course + 1000, "pumps")).startswith("error: no contributions are being suggested")


async def _open(course: int) -> dict:
    state = await contribution_routes.list_contributions(course)
    if task := contribution_routes._contributing.get(course):
        await task
    return state


def test_a_finished_courses_recap_looks_for_contributions_once_and_one_taken_up_opens_a_guided_lesson(fake_github, monkeypatch):
    turns, started = [], []

    async def turn(lesson, prompt, kind, what):
        assert kind == "contribute"
        turns.append(prompt)
        await contribution_tools.look_at_repo(lesson["course_id"], "Pumps/impy")
        await contribution_tools.suggest_contributions(lesson["course_id"], [_entry()])
        return True

    monkeypatch.setattr(app, "_background_turn", turn)
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: started.append((lesson["phase"], line)))
    monkeypatch.setattr(app.hub, "publish", lambda course, event: None)
    unfinished = db.create_course("Unfinished", db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid)["id"]
    with pytest.raises(HTTPException) as refused:
        asyncio.run(_open(unfinished))
    assert refused.value.status_code == 409

    course = _finished_course()
    asyncio.run(_open(course))
    assert len(turns) == 1
    assert "[course] Pump design" in turns[0] and "[units] Slip: not started; Eye: not started" in turns[0]
    state = asyncio.run(_open(course))
    assert len(turns) == 1 and not state["running"]
    [offered] = state["contributions"]

    view = asyncio.run(contribution_routes.start_contribution(offered["id"]))
    assert view["phase"] == "contribution" and view["title"] == "Add Wiesner's slip factor"
    phase, line = started[0]
    assert phase == "contribution" and line.startswith("[event] The learner takes on an open-source contribution to https://github.com/Pumps/impy")
    assert "Issue: https://github.com/Pumps/impy/issues/7" in line
    assert asyncio.run(contribution_routes.start_contribution(offered["id"]))["id"] == view["id"] and len(started) == 1
    assert db.contribution(offered["id"])["status"] == "started"

    async def again() -> None:
        await contribution_routes.find_contributions(course)
        await contribution_routes._contributing[course]

    asyncio.run(again())
    assert len(turns) == 2
    assert [c["status"] for c in db.contributions(course)] == ["started", "open"]
    db.delete_course(course)
    assert db.rows("SELECT id FROM contributions WHERE course_id = ?", course) == []


def test_a_dismissed_contribution_leaves_the_recap(fake_github):
    course = _finished_course()
    job = {"finished": "x", "seen": {"pumps/impy"}, "calls": 0, "done": False}
    contribution_tools.contribution_jobs[course] = job
    try:
        asyncio.run(contribution_tools.suggest_contributions(course, [_entry(), _entry(title="Another")]))
    finally:
        contribution_tools.contribution_jobs.pop(course)
    first = db.contributions(course)[0]["id"]
    left = contribution_routes.dismiss_contribution(first)["contributions"]
    assert [c["title"] for c in left] == ["Another"]
