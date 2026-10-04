import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from . import MCP_URL, MODEL, PORT

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "wise_scholar" / "prompts"
MCP_PREFIX = "mcp__scholar__"

MCP_CONFIG = ROOT / "data" / f"mcp-{PORT}.json"


async def start() -> None:
    MCP_CONFIG.parent.mkdir(exist_ok=True)
    MCP_CONFIG.write_text(json.dumps({"mcpServers": {"scholar": {"type": "http", "url": MCP_URL}}}))


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


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str
) -> AsyncIterator[dict]:
    session = ["--resume", session_id] if resume else ["--session-id", session_id, "--name", name]
    system_prompt = "\n\n".join((PROMPTS / f"{part}.md").read_text() for part in ("core", phase))
    # Empty --setting-sources keeps user-level hooks, plugins and CLAUDE.md out of the tutor session, and with
    # --strict-mcp-config and no built-in tools nothing a command plants in the workspace (the cwd) is loaded or usable.
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p",
        "--output-format", "stream-json", "--include-partial-messages", "--verbose",
        "--setting-sources", "", "--disable-slash-commands",
        "--strict-mcp-config", "--mcp-config", str(MCP_CONFIG),
        "--system-prompt", system_prompt,
        # No built-in tools: the tutor acts only through the server's MCP tools, which sandbox what they run.
        "--tools", "",
        "--allowedTools", "mcp__scholar",
        *(["--model", MODEL] if MODEL else []),
        *session,
        cwd=cwd,
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
            if event:
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
