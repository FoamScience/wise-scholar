import asyncio
import ctypes
import json
import os
import secrets
import signal
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from .. import db
from . import MCP_HEADERS, MCP_URL, MODEL, environment

ROOT = Path(__file__).resolve().parents[2]
OPENCODE_PORT = int(os.environ.get("WISE_SCHOLAR_OPENCODE_PORT", "8322"))
BASE = f"http://127.0.0.1:{OPENCODE_PORT}"
MCP_PREFIX = "scholar_"
# opencode serve answers anyone who reaches its port; a password known only to this process keeps it ours. The
# user name is fixed by opencode.
AUTH = ("opencode", secrets.token_urlsafe(24))
# opencode's own config folder for this server, empty: the user's plugins, agents and AGENTS.md stay out.
CONFIG_DIR = ROOT / "data" / "opencode-config"

_server: asyncio.subprocess.Process | None = None
PR_SET_PDEATHSIG = 1


def _die_with_parent() -> None:
    """Linux: the opencode server goes when this process does, also on a kill that never reaches stop()."""
    ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def _taken(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


async def start() -> None:
    """Run `opencode serve` with the repo's opencode.json; the user's plugins and Claude files stay out."""
    global _server
    if _taken(OPENCODE_PORT):
        raise RuntimeError(
            f"port {OPENCODE_PORT} is already in use, likely by an opencode server left from an earlier run; "
            "stop it, or set WISE_SCHOLAR_OPENCODE_PORT to a free port"
        )
    log = open(ROOT / "data" / "opencode.log", "ab")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _server = await asyncio.create_subprocess_exec(
        "opencode", "serve", "--port", str(OPENCODE_PORT),
        cwd=ROOT,
        env={
            # Its own settings and the keys of the model providers it may call; nothing else of the server's.
            **environment("OPENCODE_*", "ANTHROPIC_*", "OPENAI_*", "OPENROUTER_*", "GEMINI_*", "GOOGLE_*", "GROQ_*",
                          "MISTRAL_*", "DEEPSEEK_*", "XAI_*", "TOGETHER_*", "FIREWORKS_*", "OLLAMA_*", "AZURE_*", "AWS_*"),
            "OPENCODE_CONFIG": str(ROOT / "opencode.json"),
            "OPENCODE_CONFIG_CONTENT": json.dumps({"mcp": {"scholar": {"type": "remote", "url": MCP_URL, "enabled": True, "headers": MCP_HEADERS}}}),
            "OPENCODE_CONFIG_DIR": str(CONFIG_DIR),
            # an opencode.json or .opencode/ a command plants in a session's folder is not read
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_SERVER_PASSWORD": AUTH[1],
        },
        stdout=log,
        stderr=log,
        preexec_fn=_die_with_parent if sys.platform == "linux" else None,
    )
    async with httpx.AsyncClient(base_url=BASE, auth=AUTH) as client:
        for _ in range(100):
            if _server.returncode is not None:
                raise RuntimeError(f"opencode serve exited with code {_server.returncode}; see data/opencode.log")
            try:
                (await client.get("/api/info")).raise_for_status()
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
    """Turn the opencode event stream, which carries every session, into the UI events of one session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def feed(self, event: dict) -> list[dict]:
        kind, d = event["type"], event.get("data") or {}
        if d.get("sessionID") != self.session_id:
            return []
        if kind == "session.text.started":
            return [{"type": "chat.break"}]
        if kind == "session.text.delta":
            return [{"type": "chat.delta", "text": d["delta"]}]
        if kind == "session.tool.input.started":
            return [{"type": "activity", "tool": d["name"].removeprefix(MCP_PREFIX).lower()}]
        if kind == "session.execution.succeeded":
            return [{"type": "turn.done", "ok": True, "error": None}]
        if kind in ("session.execution.failed", "session.error"):
            error = d.get("error") or {}
            return [{"type": "turn.done", "ok": False, "error": error.get("message") or error.get("type") or "opencode reported an error"}]
        if kind == "session.execution.interrupted":
            return [{"type": "turn.done", "ok": False, "error": "the turn was interrupted"}]
        return []


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str, token: str
) -> AsyncIterator[dict]:
    # token: unused here; opencode's MCP connection is one for the whole server, so the tools bind its calls to
    # the lessons whose turns are running instead.
    # Not the course workspace: opencode loads opencode.json and .opencode/ from its directory, and commands can
    # write there. A file planted in the workspace could hand the agent its built-in shell back.
    directory = db.DB_PATH.parent / "agents" / cwd.name
    directory.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=BASE, timeout=None, auth=AUTH) as client:
        async def create() -> str:
            created = await client.post("/api/session", json={"title": name, "location": {"directory": str(directory)}})
            created.raise_for_status()
            return created.json()["data"]["id"]

        async def prepare(session: str) -> httpx.Response:
            """The session's agent and model for this turn; a phase change between turns picks another agent."""
            chosen = await client.post(f"/api/session/{session}/agent", json={"agent": f"tutor-{phase}"})
            if chosen.status_code < 400 and MODEL:
                provider, _, model = MODEL.partition("/")
                chosen = await client.post(f"/api/session/{session}/model", json={"model": {"id": model, "providerID": provider}})
            return chosen

        if not resume:
            session_id = await create()
            yield {"type": "session.started", "session_id": session_id}
        prepared = await prepare(session_id)
        if resume and prepared.status_code == 404:
            # A session opencode no longer has (one from opencode 1, or from before the move out of the workspace):
            # the lesson goes on in a fresh one, and the state header of every turn carries it over.
            session_id = await create()
            yield {"type": "session.started", "session_id": session_id}
            prepared = await prepare(session_id)
        if prepared.status_code >= 400:
            yield {"type": "turn.done", "ok": False, "error": f"opencode refused the turn: {prepared.text[:300]}"}
            return
        parser = EventParser(session_id)
        finished = False
        try:
            async with client.stream("GET", "/api/event") as events:
                sent = await client.post(f"/api/session/{session_id}/prompt", json={"text": prompt})
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
                await asyncio.shield(client.post(f"/api/session/{session_id}/interrupt", json={}))
