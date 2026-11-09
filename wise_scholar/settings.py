"""The server's WISE_SCHOLAR_* settings as the settings page sees them: where each value comes from, and changes to
the safe ones written to `.env`, the file `make` reads. Every module reads its settings once at start, so a change
takes effect when the server starts again."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
LINE = re.compile(r"^\s*(?:export\s+)?(WISE_SCHOLAR_[A-Z_]+)\s*[?:]?=\s*(.*?)\s*$")
BACKENDS = ("claude", "opencode", "agy")


@dataclass(frozen=True)
class Setting:
    name: str
    default: str
    kind: str  # "int", "bool", "text" or "agent"
    editable: bool
    minimum: int = 0
    secret: bool = False


# Editable: limits and features whose worst value costs time or money. Read-only: what decides who reaches the
# server, what commands may touch, and where data lives; those stay in .env or the shell.
CATALOG = (
    Setting("WISE_SCHOLAR_AGENT", "claude", "agent", True),
    Setting("WISE_SCHOLAR_COMMANDS", "1", "bool", True),
    Setting("WISE_SCHOLAR_TURNS", "2", "int", True, 1),
    Setting("WISE_SCHOLAR_TURNS_PER_HOUR", "200", "int", True, 1),
    Setting("WISE_SCHOLAR_TOOL_CALLS", "80", "int", True, 1),
    Setting("WISE_SCHOLAR_MCP_CALLS", "600", "int", True, 1),
    Setting("WISE_SCHOLAR_WORKSPACE_MB", "4096", "int", True, 1),
    Setting("WISE_SCHOLAR_KEEP_DAYS", "", "int", True, 1),
    Setting("WISE_SCHOLAR_PODCASTS", "0", "bool", True),
    Setting("WISE_SCHOLAR_RECAP_PREVIEW", "0", "bool", True),
    Setting("WISE_SCHOLAR_SEARCH_MODEL", "minishlab/potion-multilingual-128M", "text", True),
    Setting("WISE_SCHOLAR_OPENCODE_PORT", "8322", "int", True, 1024),
    Setting("WISE_SCHOLAR_PORT", "8321", "int", False),
    Setting("WISE_SCHOLAR_HOSTS", "127.0.0.1,localhost,::1", "text", False),
    Setting("WISE_SCHOLAR_LISTEN", "", "text", False),
    Setting("WISE_SCHOLAR_DB", "data/wise-scholar.db", "text", False),
    Setting("WISE_SCHOLAR_WORKSPACE", "workspace/", "text", False),
    Setting("WISE_SCHOLAR_VAULT", "", "text", False),
    Setting("WISE_SCHOLAR_SANDBOX", "1", "bool", False),
    Setting("WISE_SCHOLAR_SANDBOX_PATHS", "", "text", False),
    Setting("WISE_SCHOLAR_AGENT_ENV", "", "text", False),
    Setting("WISE_SCHOLAR_MCP_SECRET", "", "text", False, secret=True),
)
BY_NAME = {s.name: s for s in CATALOG}


def read_file(path: Path | None = None) -> dict[str, str]:
    """The WISE_SCHOLAR_* values in .env; other lines are not ours."""
    path = path or ENV_FILE
    if not path.exists():
        return {}
    return {m[1]: m[2] for line in path.read_text().splitlines() if (m := LINE.match(line))}


# What the server started with: a running value equal to the file's is the file's; any other was set in the shell,
# where it beats the file (`?=`), so the page cannot change it.
STARTED = {s.name: os.environ.get(s.name) for s in CATALOG}
FILE_AT_START = read_file()


def source(name: str) -> str:
    running = STARTED[name]
    if running is None:
        return "default"
    return "file" if FILE_AT_START.get(name) == running else "shell"


def view() -> list[dict]:
    saved = read_file()
    out = []
    for s in CATALOG:
        running, origin = STARTED[s.name], source(s.name)
        # A value in .env that the server did not start with waits for a restart; a shell value is never replaced.
        waiting = origin != "shell" and saved.get(s.name) != (running if origin == "file" else None)
        out.append({
            "name": s.name,
            "kind": s.kind,
            "minimum": s.minimum,
            "default": s.default,
            "value": ("set" if running else None) if s.secret else running,
            "saved": ("set" if saved.get(s.name) else None) if s.secret else saved.get(s.name),
            "source": origin,
            "changeable": s.editable,
            "editable": s.editable and origin != "shell",
            "pending": waiting,
        })
    return out


def check(name: str, value: str | None) -> str | None:
    """Why a value is refused for a setting; None when it is fine. None as a value means back to the default."""
    s = BY_NAME.get(name)
    if not s or not s.editable:
        return "this setting cannot be changed here"
    if source(name) == "shell":
        return "this setting is set in the shell, which overrides .env"
    if value is None:
        return None
    # make reads .env: a newline, # or $ would end or expand the value.
    if not value or re.search(r"[\n\r#$\\]", value) or value != value.strip():
        return "that value cannot be written to .env"
    if s.kind == "bool" and value not in ("0", "1"):
        return "that value cannot be written to .env"
    if s.kind == "int" and not (value.isdigit() and int(value) >= s.minimum):
        return "that number is too small or not a whole number"
    if s.kind == "agent" and value.partition("/")[0] not in BACKENDS:
        return "the agent must start with claude, opencode or agy"
    return None


def write(changes: dict[str, str | None]) -> None:
    """Set or remove lines in .env, keeping every other line and the order of the file."""
    path = ENV_FILE
    lines = path.read_text().splitlines() if path.exists() else []
    done = set()
    kept = []
    for line in lines:
        m = LINE.match(line)
        if m and m[1] in changes:
            done.add(m[1])
            if changes[m[1]] is not None:
                kept.append(f"export {m[1]} ?= {changes[m[1]]}")
            continue
        kept.append(line)
    kept += [f"export {name} ?= {value}" for name, value in changes.items() if name not in done and value is not None]
    path.write_text("".join(f"{line}\n" for line in kept))


def environment_for_restart() -> dict[str, str]:
    """The environment of the next server: the shell's values as they were, the file's as it is now."""
    env = dict(os.environ)
    saved = read_file()
    for s in CATALOG:
        if source(s.name) == "shell":
            continue
        if s.name in saved:
            env[s.name] = saved[s.name]
        else:
            env.pop(s.name, None)
    return env


# Set by `python -m wise_scholar.serve`: stops the server, which then starts itself again. Under `uvicorn --reload`
# (make dev) there is no such hook and the page asks for a restart by hand.
restarter: Callable[[], None] | None = None
