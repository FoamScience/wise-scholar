import asyncio
import json
import os
import shlex
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from . import ALONE, MCP_HEADERS, MCP_URL, PORT, TURN_HEADER, environment, model_for

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "wise_scholar" / "prompts"
GATE = Path(__file__).with_name("agy_gate.py")
# agy reads its MCP servers, hooks and rules from the workspace a turn starts in, so each turn gets a folder of its
# own holding its token; a resumed conversation also reads the folder it began in, so a folder goes with its turn.
TURNS = ROOT / "data" / "agents" / "agy"
# agy's home for the tutor: conversations stay here, and the user's GEMINI.md, MCP servers, plugins and skills in
# ~/.gemini stay out. Only the login is linked in.
HOME = ROOT / "data" / "agy-home"
LOGIN = ("oauth_creds.json", "google_accounts.json")
SCHEMAS = HOME / ".gemini" / "antigravity-cli" / "mcp" / "scholar"
SETTINGS = json.dumps({"permissions": {
    "allow": ["mcp(scholar/*)"],
    "deny": ["command(*)", "write_file(*)", "read_url(*)", "execute_url(*)"],
}})


async def start() -> None:
    TURNS.mkdir(parents=True, exist_ok=True)
    for stale in TURNS.glob(f"{PORT}-*"):
        shutil.rmtree(stale)
    (HOME / ".gemini").mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in LOGIN:
        link, login = HOME / ".gemini" / name, Path.home() / ".gemini" / name
        if login.exists() and not link.is_symlink():
            link.symlink_to(login)


async def stop() -> None:
    pass


class EventParser:
    """Map `agy -p --output-format stream-json` lines to UI events."""

    def __init__(self, model: str = ""):
        self.model = model
        self.step = None
        self.tools = set()

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return []
        kind = e.get("event")
        if kind == "init":
            return [{"type": "session.started", "session_id": e["conversation_id"]}]
        if kind == "step_update":
            step = e["step_update"]
            if step.get("step_type") == "agent_response":
                events = [] if step["step_index"] == self.step else [{"type": "chat.break"}]
                self.step = step["step_index"]
                if text := step.get("text_delta"):
                    events.append({"type": "chat.delta", "text": text})
                return events
            info = step.get("tool_info") or {}
            params = info.get("parameters") or {}
            if step.get("tool_name") == "call_mcp_tool" and params.get("ServerName") == "scholar" and step["step_index"] not in self.tools:
                self.tools.add(step["step_index"])
                return [{"type": "activity", "tool": params.get("ToolName", "").lower()}]
            return []
        if kind == "result":
            result = e["result"]
            ok = result.get("status") == "SUCCESS"
            error = None if ok else str(result.get("error") or result.get("status"))
            return [{"type": "turn.done", "ok": ok, "error": error, "usage": usage(result, self.model)}]
        return []


def usage(result: dict, model: str = "") -> dict | None:
    """What a run used; agy reports tokens but no price."""
    used = result.get("usage")
    if not used:
        return None
    return {
        "model": model or "agy",
        "input": used.get("input_tokens") or 0,
        "output": (used.get("output_tokens") or 0) + (used.get("thinking_tokens") or 0),
        "cache_read": used.get("cache_read_tokens") or 0,
        "cache_write": 0,
        "cost": None,
    }


def _private(path: Path, text: str) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
        out.write(text)


def workspace(token: str, phase: str) -> Path:
    """The folder of one turn: the tutor's MCP server with the server's secret and the turn's token, the hook that
    denies every built-in tool, and the phase's prompts as always-on rules (agy has no system prompt flag)."""
    folder = TURNS / f"{PORT}-{token}"
    agents = folder / ".agents"
    (agents / "rules").mkdir(parents=True, mode=0o700)
    # Marks the folder as its own repository root, so agy looks for rules no higher up.
    (folder / ".git").mkdir()
    server = {"serverUrl": MCP_URL, "headers": {**MCP_HEADERS, TURN_HEADER: token}}
    _private(agents / "mcp_config.json", json.dumps({"mcpServers": {"scholar": server}}))
    gate = f"{shlex.quote(sys.executable)} -I {shlex.quote(str(GATE))} {shlex.quote(str(SCHEMAS))}"
    _private(agents / "hooks.json", json.dumps({"scholar-gate": {"PreToolUse": [{"matcher": "*", "hooks": [{"command": gate}]}]}}))
    # One file per prompt: agy cuts a rule file at 24 KB.
    for part in (phase,) if phase in ALONE else ("core", phase):
        _private(agents / "rules" / f"{part}.md", "---\ntrigger: always_on\n---\n" + (PROMPTS / f"{part}.md").read_text())
    return folder


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str, token: str
) -> AsyncIterator[dict]:
    # name: agy has no conversation titles. session_id: agy names a new conversation itself; init reports it, and a
    # conversation it no longer has starts afresh under a new id.
    folder = workspace(token, phase)
    proc = await asyncio.create_subprocess_exec(
        "agy",
        "--output-format", "stream-json", "--disable-slash-commands",
        "--settings", SETTINGS,
        *(["--model", model] if (model := model_for(phase)) else []),
        *(["--conversation", session_id] if resume else []),
        # The prompt comes on stdin, one message: no argument length limit, and not visible in the process list.
        "--input-format", "stream-json", "--print=",
        cwd=folder,
        env={**environment("GEMINI_*", "GOOGLE_*", "AGY_*", "ANTIGRAVITY_*"), "HOME": str(HOME)},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=2**24,
    )
    stderr = asyncio.create_task(proc.stderr.read())
    parser = EventParser(model_for(phase))
    done = False
    try:
        proc.stdin.write(json.dumps({"event": "user", "message": {"role": "user", "content": prompt}}).encode() + b"\n")
        await proc.stdin.drain()
        proc.stdin.close()
        async for line in proc.stdout:
            for event in parser.feed(line.decode()):
                done = done or event["type"] == "turn.done"
                yield event
        await proc.wait()
        if not done:
            tail = (await stderr).decode().strip()[-500:]
            yield {"type": "turn.done", "ok": False, "error": tail or f"agy exited with code {proc.returncode}"}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        stderr.cancel()
        shutil.rmtree(folder, ignore_errors=True)
