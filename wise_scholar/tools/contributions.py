from typing import Literal

from pydantic import BaseModel

from .. import db, github
from ..tutor import mcp

GITHUB_CALLS = 30
CONTRIBUTIONS = (0, 5)
TITLE_CHARS = 90
GAP_CHARS = 400
USES_CHARS = 240
STEP_CHARS = 300
contribution_jobs: dict[int, dict] = {}  # course id -> {"finished", "seen", "calls", "done"}


async def _ask(course_id: int, call) -> str:
    """One GitHub call of the running contribute turn, within its budget; GitHub's refusals come back as text."""
    job = contribution_jobs.get(course_id)
    if job is None:
        return f"error: no contributions are being suggested for course {course_id}"
    job["calls"] += 1
    if job["calls"] > GITHUB_CALLS:
        return f"error: over {GITHUB_CALLS} GitHub calls; call suggest_contributions with what you found"
    try:
        return await call(job)
    except github.GitHubError as e:
        return f"error: {e}"


@mcp.tool()
async def find_repos(course_id: int, query: str, language: str = "") -> str:
    """Search GitHub's repositories, most starred first: name, stars, language, last push, licence and description.

    query: a few words of the field, as in a GitHub search box; language: a programming language to keep to, or empty.
    """
    return await _ask(course_id, lambda job: github.find_repos(query, language))


@mcp.tool()
async def find_issues(course_id: int, query: str) -> str:
    """Search GitHub's open, unassigned issues, most recently updated first. Add qualifiers to the words, e.g.
    `label:"good first issue"`, `label:"help wanted"`, `language:python` or `repo:owner/name`."""
    return await _ask(course_id, lambda job: github.find_issues(query))


@mcp.tool()
async def look_at_repo(course_id: int, repo: str) -> str:
    """One repository: its activity, how many outside contributions it merged lately, its contributing guide, its
    open issues and its source file paths. A repository must be looked at before it is suggested."""

    async def look(job: dict) -> str:
        name, text = await github.repo_overview(repo)
        job["seen"].add(name.lower())
        return text

    return await _ask(course_id, look)


@mcp.tool()
async def outline_repo_file(course_id: int, repo: str, path: str) -> str:
    """The definitions in one file of a repository (functions, classes, types) with their line numbers: what the
    file already has, without reading its bodies."""
    return await _ask(course_id, lambda job: github.file_outline(repo, path))


@mcp.tool()
async def read_repo_lines(course_id: int, repo: str, path: str, start: int = 1) -> str:
    """80 lines of one file of a repository from line `start`; read only what an outline or a search pointed to."""
    return await _ask(course_id, lambda job: github.read_lines(repo, path, start))


@mcp.tool()
async def search_repo_code(course_id: int, repo: str, query: str) -> str:
    """Search the code of one repository for words: the files they appear in, each with a fragment. Use it to check
    that something you would suggest is not there already under another name."""
    return await _ask(course_id, lambda job: github.search_code(repo, query))


class Contribution(BaseModel):
    repo: str
    title: str
    size: Literal["small", "project"]
    gap: str
    uses: str
    first_step: str
    issue: str = ""


def _contribution_error(entry: dict, seen: set[str]) -> str | None:
    if entry["repo"].lower() not in seen:
        return f"error: {entry['repo']} was not looked at; call look_at_repo on it first, or drop it"
    if not (0 < len(entry["title"]) <= TITLE_CHARS and 0 < len(entry["gap"]) <= GAP_CHARS):
        return f"error: {entry['title']!r}: keep the title under {TITLE_CHARS} and the gap under {GAP_CHARS} characters"
    if not (0 < len(entry["uses"]) <= USES_CHARS and 0 < len(entry["first_step"]) <= STEP_CHARS):
        return f"error: {entry['title']!r}: keep uses under {USES_CHARS} and the first step under {STEP_CHARS} characters"
    if entry["issue"] and not entry["issue"].lower().startswith(f"https://github.com/{entry['repo'].lower()}/issues/"):
        return f"error: {entry['title']!r}: issue must be the address of an issue of {entry['repo']}, or empty"
    return None


@mcp.tool()
async def suggest_contributions(course_id: int, contributions: list[Contribution]) -> str:
    """Offer the learner open-source contributions that put the finished course to work; these replace the ones on offer.

    0 to 5, none when nothing fits. repo: owner/name, a repository you looked at. title: under 90 characters, the
    change as a contributor would name it. size: small for an afternoon's change (a function, a fix, a test), project
    for a few weeks' work. gap: under 400 characters, what the project lacks or what its issue asks, as you checked it.
    uses: under 240 characters, which units of the course it puts to work. first_step: under 300 characters, what the
    learner does first; for anything without an issue, that is opening one to ask the maintainers. issue: the
    address of the issue it answers, or empty. Plain text with inline Markdown.
    """
    job = contribution_jobs.get(course_id)
    if job is None:
        return f"error: no contributions are being suggested for course {course_id}"
    entries = [{k: " ".join(v.split()) for k, v in c.model_dump().items()} for c in contributions]
    for entry in entries:
        entry["repo"] = entry["repo"].removeprefix("https://github.com/").strip("/")
    if not CONTRIBUTIONS[0] <= len(entries) <= CONTRIBUTIONS[1]:
        return f"error: give {CONTRIBUTIONS[0]} to {CONTRIBUTIONS[1]} contributions"
    if len({e["title"].casefold() for e in entries}) != len(entries):
        return "error: two contributions have the same title"
    if problem := next(filter(None, (_contribution_error(e, job["seen"]) for e in entries)), None):
        return problem
    db.set_contributions(course_id, entries, job["finished"])
    job["done"] = True
    return "recorded"
