import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from . import ALONE, MCP_HEADERS, MCP_URL, MODEL, PORT, TURN_HEADER, environment

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "wise_scholar" / "prompts"
MCP_PREFIX = "mcp__scholar__"

CONFIGS = ROOT / "data" / "mcp"
# Not the course workspace: a file a command plants there (CLAUDE.md, .claude/) must never be near the agent.
AGENT_HOMES = ROOT / "data" / "agents"


async def start() -> None:
    CONFIGS.mkdir(parents=True, exist_ok=True)
    for stale in CONFIGS.glob(f"{PORT}-*.json"):
        stale.unlink()


async def stop() -> None:
    pass


def parse_event(line: str) -> dict | None:
    """Map one stream-json line from `claude -p` to a UI event; None when the line carries nothing for the UI."""
    e = json.loads(line)
    kind = e.get("type")
    if kind == "system" and e.get("subtype") == "init":
        return {"type": "session.started"}
    if kind == "stream_event":
        ev = e["event"]
        if ev["type"] == "message_start":
            return {"type": "chat.break"}
        if ev["type"] == "content_block_delta" and ev["delta"]["type"] == "text_delta":
            return {"type": "chat.delta", "text": ev["delta"]["text"]}
        if ev["type"] == "content_block_start" and ev["content_block"]["type"] == "tool_use":
            return {"type": "activity", "tool": ev["content_block"]["name"].removeprefix(MCP_PREFIX).lower()}
    if kind == "result":
        ok = e.get("subtype") == "success" and not e.get("is_error")
        return {"type": "turn.done", "ok": ok, "error": None if ok else str(e.get("result") or e.get("subtype"))}
    return None


def mcp_config(token: str) -> Path:
    """The MCP config of one turn: the server's secret and the turn's token ride as headers, so the tools know which
    lesson is calling."""
    CONFIGS.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = CONFIGS / f"{PORT}-{token}.json"
    config = json.dumps({"mcpServers": {"scholar": {"type": "http", "url": MCP_URL, "headers": {**MCP_HEADERS, TURN_HEADER: token}}}})
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
        out.write(config)
    return path


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str, token: str
) -> AsyncIterator[dict]:
    session = ["--resume", session_id] if resume else ["--session-id", session_id, "--name", name]
    system_prompt = "\n\n".join((PROMPTS / f"{part}.md").read_text() for part in ((phase,) if phase in ALONE else ("core", phase)))
    home = AGENT_HOMES / cwd.name
    home.mkdir(parents=True, exist_ok=True)
    config = mcp_config(token)
    # Empty --setting-sources keeps user-level hooks, plugins and CLAUDE.md out of the tutor session, and with
    # --strict-mcp-config and no built-in tools nothing a command plants in the workspace is loaded or usable.
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p",
        "--output-format", "stream-json", "--include-partial-messages", "--verbose",
        "--setting-sources", "", "--disable-slash-commands",
        "--strict-mcp-config", "--mcp-config", str(config),
        "--system-prompt", system_prompt,
        # No built-in tools: the tutor acts only through the server's MCP tools, which sandbox what they run.
        "--tools", "",
        "--allowedTools", "mcp__scholar",
        *(["--model", MODEL] if MODEL else []),
        *session,
        cwd=home,
        # Its own settings and keys, and the cloud credentials a Bedrock or Vertex setup signs with.
        env=environment("ANTHROPIC_*", "CLAUDE_*", "AWS_*", "GOOGLE_*", "GCLOUD_*", "CLOUD_ML_REGION"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=2**24,
    )
    stderr = asyncio.create_task(proc.stderr.read())
    done = False
    try:
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        async for line in proc.stdout:
            event = parse_event(line.decode())
            if not event:
                continue
            if event["type"] == "turn.done" and resume and not event["ok"] and "conversation" in (event["error"] or "").lower():
                # A session started before the move out of the workspace is not found from here: the lesson goes on
                # in a fresh one, and the state header of every turn carries it over.
                async for again in run_turn(prompt, session_id=str(uuid.uuid4()), resume=False, name=name, cwd=cwd, phase=phase, token=token):
                    yield again
                return
            done = done or event["type"] == "turn.done"
            yield event
        await proc.wait()
        if not done:
            tail = (await stderr).decode().strip()[-500:]
            yield {"type": "turn.done", "ok": False, "error": tail or f"claude exited with code {proc.returncode}"}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        stderr.cancel()
        config.unlink(missing_ok=True)
