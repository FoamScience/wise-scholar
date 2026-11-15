"""GitHub's REST API for the turn that suggests open-source contributions: short, trimmed answers cached for a day, so
a turn reads summaries of repositories and never a codebase. Without WISE_SCHOLAR_GITHUB_TOKEN the API allows a few
searches a minute and no code search."""
import base64
import os
import re
import time
from urllib.parse import quote

import httpx

API = "https://api.github.com"
TOKEN = os.environ.get("WISE_SCHOLAR_GITHUB_TOKEN", "")
TIMEOUT = 15
CACHE_SECONDS = 24 * 3600
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
REPOS_SHOWN = 8
ISSUES_SHOWN = 10
PATHS_SHOWN = 120
OUTLINE_LINES = 150
READ_LINES = 80
SOURCE = re.compile(r"\.(py|pyx|ipynb|c|cc|cpp|cxx|h|hpp|f|f90|jl|m|r|rs|go|java|kt|scala|js|mjs|ts|tsx|cs|rb|php|swift|zig|lua|sh)$", re.I)
DEFINITION = re.compile(r"^\s*(async def|def|class|function|export (default )?(async )?function|export (const|class|type|interface)|pub (fn|struct|enum|trait)|fn|struct|impl|interface|type|module|subroutine|program|template)\b")
_cache: dict[str, tuple[float, object]] = {}


class GitHubError(Exception):
    pass


def _headers(text_match: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.text-match+json" if text_match else "application/vnd.github+json",
        "User-Agent": "wise-scholar",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def _failure(res: httpx.Response) -> GitHubError:
    if res.status_code in (403, 429) and (res.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in res.text.lower()):
        return GitHubError("GitHub's rate limit is reached; suggest from what you found so far")
    if res.status_code == 404:
        return GitHubError("not found on GitHub")
    if res.status_code == 422:
        return GitHubError("GitHub refused the query; make it simpler")
    if res.status_code == 401:
        return GitHubError("GitHub refused the token in WISE_SCHOLAR_GITHUB_TOKEN")
    return GitHubError(f"GitHub answered {res.status_code}")


async def _get(path: str, params: dict | None = None, text_match: bool = False):
    key = f"{path}?{sorted((params or {}).items())}"
    if (hit := _cache.get(key)) and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, headers=_headers(text_match)) as client:
            res = await client.get(API + path, params=params)
    except httpx.HTTPError as e:
        raise GitHubError(f"GitHub could not be reached: {type(e).__name__}") from None
    if res.status_code != 200:
        raise _failure(res)
    data = res.json()
    _cache[key] = (time.monotonic(), data)
    return data


def _repo(name: str) -> str:
    name = name.strip().removeprefix("https://github.com/").strip("/")
    if not REPO.match(name):
        raise GitHubError("name the repository as owner/name")
    return name


def _one_line(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _repo_line(r: dict) -> str:
    licence = (r.get("license") or {}).get("spdx_id") or "no licence"
    return (
        f"{r['full_name']} ★{r['stargazers_count']}, {r.get('language') or 'no language'}, pushed {r['pushed_at'][:10]}, "
        f"{licence}, {r['open_issues_count']} open issues and PRs — {_one_line(r.get('description'), 140)}"
    )


def _issue_line(i: dict) -> str:
    repo = i["repository_url"].removeprefix(f"{API}/repos/")
    labels = ",".join(label["name"] for label in i.get("labels", []))
    return f"{repo}#{i['number']} [{labels}] updated {i['updated_at'][:10]}, {i['comments']} comments — {_one_line(i['title'], 140)}"


async def find_repos(query: str, language: str = "") -> str:
    q = f"{query} archived:false" + (f" language:{language}" if language else "")
    data = await _get("/search/repositories", {"q": q, "sort": "stars", "per_page": REPOS_SHOWN})
    return "\n".join(_repo_line(r) for r in data["items"]) or "no repositories found"


async def find_issues(query: str) -> str:
    q = f"{query} is:issue is:open no:assignee archived:false"
    data = await _get("/search/issues", {"q": q, "sort": "updated", "per_page": ISSUES_SHOWN})
    return "\n".join(_issue_line(i) for i in data["items"]) or "no open issues found"


async def _outside_merges(name: str, owner: str) -> str:
    pulls = await _get(f"/repos/{name}/pulls", {"state": "closed", "per_page": 30})
    merged = [p for p in pulls if p.get("merged_at")]
    outside = {p["user"]["login"] for p in merged if p["user"]["login"] != owner}
    return f"{len(merged)} of its last {len(pulls)} closed PRs merged, by {len(outside)} people besides the owner"


async def repo_overview(name: str) -> tuple[str, str]:
    """The repository's state, its open issues and its source files; returns (canonical name, text)."""
    name = _repo(name)
    meta = await _get(f"/repos/{name}")
    name = meta["full_name"]
    branch = meta["default_branch"]
    tree = await _get(f"/repos/{name}/git/trees/{branch}", {"recursive": "1"})
    paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob"]
    issues = [i for i in await _get(f"/repos/{name}/issues", {"state": "open", "per_page": 30}) if "pull_request" not in i]
    source = [p for p in paths if SOURCE.search(p)]
    guides = [p for p in paths if re.search(r"(^|/)(CONTRIBUTING|HACKING|DEVELOPMENT)(\.\w+)?$", p, re.I)]
    lines = [
        _repo_line(meta),
        await _outside_merges(name, meta["owner"]["login"]),
        f"contributing guide: {', '.join(guides) or 'none'}",
        f"[open issues] {len(issues)}" + ("" if issues else ": none"),
        *(_issue_line({**i, "repository_url": f"{API}/repos/{name}"}) for i in issues[:ISSUES_SHOWN]),
        f"[source files] {len(source)}" + (f", the first {PATHS_SHOWN}" if len(source) > PATHS_SHOWN else ""),
        *source[:PATHS_SHOWN],
    ]
    return name, "\n".join(lines)


async def _file_lines(name: str, path: str) -> list[str]:
    data = await _get(f"/repos/{_repo(name)}/contents/{quote(path.lstrip('/'))}")
    if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
        raise GitHubError("that path is not a file")
    return base64.b64decode(data["content"]).decode("utf-8", "replace").splitlines()


async def file_outline(name: str, path: str) -> str:
    """The file's definitions with their line numbers: what it already has, without its bodies."""
    lines = await _file_lines(name, path)
    found = [f"{n}: {line.rstrip()[:160]}" for n, line in enumerate(lines, start=1) if DEFINITION.match(line)]
    shown = found[:OUTLINE_LINES]
    more = f"\n… and {len(found) - len(shown)} more" if len(found) > len(shown) else ""
    return f"{path}, {len(lines)} lines\n" + ("\n".join(shown) or "no definitions found") + more


async def read_lines(name: str, path: str, start: int) -> str:
    lines = await _file_lines(name, path)
    start = max(1, start)
    shown = lines[start - 1 : start - 1 + READ_LINES]
    return "\n".join(f"{n}: {line[:200]}" for n, line in enumerate(shown, start=start)) or "past the end of the file"


async def search_code(name: str, query: str) -> str:
    if not TOKEN:
        raise GitHubError("code search needs WISE_SCHOLAR_GITHUB_TOKEN; read file outlines instead")
    data = await _get("/search/code", {"q": f"{query} repo:{_repo(name)}", "per_page": ISSUES_SHOWN}, text_match=True)
    lines = []
    for item in data["items"]:
        fragment = next((_one_line(m["fragment"], 160) for m in item.get("text_matches", [])), "")
        lines.append(f"{item['path']}: {fragment}")
    return "\n".join(lines) or "no matches"

