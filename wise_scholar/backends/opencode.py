import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from .. import db
from . import MCP_URL, MODEL

ROOT = Path(__file__).resolve().parents[2]
OPENCODE_PORT = int(os.environ.get("WISE_SCHOLAR_OPENCODE_PORT", "8322"))
BASE = f"http://127.0.0.1:{OPENCODE_PORT}"
MCP_PREFIX = "scholar_"

_server: asyncio.subprocess.Process | None = None


async def start() -> None:
    """Run `opencode serve` with the repo's opencode.json; the user's plugins and Claude files stay out."""
    global _server
    log = open(ROOT / "data" / "opencode.log", "ab")
    _server = await asyncio.create_subprocess_exec(
        "opencode", "serve", "--pure", "--port", str(OPENCODE_PORT),
        cwd=ROOT,
        env={
            **os.environ,
            "OPENCODE_CONFIG": str(ROOT / "opencode.json"),
            "OPENCODE_CONFIG_CONTENT": json.dumps({"mcp": {"scholar": {"type": "remote", "url": MCP_URL, "enabled": True}}}),
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        },
        stdout=log,
        stderr=log,
    )
    async with httpx.AsyncClient(base_url=BASE) as client:
        for _ in range(100):
            if _server.returncode is not None:
                raise RuntimeError(f"opencode serve exited with code {_server.returncode}; see data/opencode.log")
            try:
                await client.get("/global/health")
                return
            except httpx.TransportError:
                await asyncio.sleep(0.2)
    await stop()
    raise RuntimeError("opencode serve did not come up; see data/opencode.log")


async def stop() -> None:
    if _server and _server.returncode is None:
        _server.terminate()
        await _server.wait()


class EventParser:
    """Turn the opencode event stream of one session into UI events."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.assistant_messages: set[str] = set()
        self.text_parts: set[str] = set()
        self.tool_parts: set[str] = set()

    def feed(self, event: dict) -> list[dict]:
        kind, p = event["type"], event.get("properties", {})
        if p.get("sessionID") != self.session_id:
            return []
        if kind == "message.updated" and p["info"]["role"] == "assistant":
            self.assistant_messages.add(p["info"]["id"])
        elif kind == "message.part.updated" and p["part"]["messageID"] in self.assistant_messages:
            part = p["part"]
            if part["type"] == "text" and part["id"] not in self.text_parts:
                self.text_parts.add(part["id"])
                return [{"type": "chat.break"}]
            if part["type"] == "tool" and part["id"] not in self.tool_parts:
                self.tool_parts.add(part["id"])
                return [{"type": "activity", "tool": part["tool"].removeprefix(MCP_PREFIX).lower()}]
        elif kind == "message.part.delta" and p["partID"] in self.text_parts and p["field"] == "text":
            return [{"type": "chat.delta", "text": p["delta"]}]
        elif kind == "session.error":
            error = p.get("error") or {}
            message = (error.get("data") or {}).get("message") or error.get("name") or "opencode reported an error"
            return [{"type": "turn.done", "ok": False, "error": message}]
        elif kind == "session.idle":
            return [{"type": "turn.done", "ok": True, "error": None}]
        return []


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str
) -> AsyncIterator[dict]:
    # Not the course workspace: opencode loads opencode.json and .opencode/ from its directory, and commands can
    # write there. A file planted in the workspace could hand the agent its built-in shell back.
    directory = db.DB_PATH.parent / "agents" / cwd.name
    directory.mkdir(parents=True, exist_ok=True)
    params = {"directory": str(directory)}
    body: dict = {"agent": f"tutor-{phase}", "parts": [{"type": "text", "text": prompt}]}
    if MODEL:
        provider, _, model = MODEL.partition("/")
        body["model"] = {"providerID": provider, "modelID": model}
    async with httpx.AsyncClient(base_url=BASE, timeout=None) as client:
        async def create() -> str:
            created = await client.post("/session", params=params, json={"title": name})
            created.raise_for_status()
            return created.json()["id"]

        if not resume:
            session_id = await create()
            yield {"type": "session.started", "session_id": session_id}
        parser = EventParser(session_id)
        finished = False
        try:
            async with client.stream("GET", "/event", params=params) as events:
                sent = await client.post(f"/session/{session_id}/prompt_async", params=params, json=body)
                if resume and sent.status_code >= 400:
                    # A session from before the move out of the workspace is not found here: the lesson goes on in
                    # a fresh one, and the state header of every turn carries it over.
                    session_id = await create()
                    yield {"type": "session.started", "session_id": session_id}
                    parser = EventParser(session_id)
                    sent = await client.post(f"/session/{session_id}/prompt_async", params=params, json=body)
                if sent.status_code >= 400:
                    finished = True
                    yield {"type": "turn.done", "ok": False, "error": f"opencode refused the turn: {sent.text[:300]}"}
                    return
                async for line in events.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    for event in parser.feed(json.loads(line[5:])):
                        finished = event["type"] == "turn.done"
                        yield event
                        if finished:
                            return
        finally:
            if not finished:
                await asyncio.shield(client.post(f"/session/{session_id}/abort", params=params))
