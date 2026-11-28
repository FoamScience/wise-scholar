import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult, ImageContent, TextContent

from .. import db, tutor
from . import MCP_HEADERS, MCP_URL, TURN_HEADER, model_for, system_prompt

# Streamed, so a long reply never runs into a request timeout.
MAX_TOKENS = 64000
# Requests in one turn, so a model that keeps calling tools (retrying one that refuses it, say) stops spending. Claude
# Code tutor turns took at most 17 over 704 turns (median 2, p99 11).
MAX_ROUNDS = 25
# How Anthropic ("prompt is too long") and Ollama ("exceeds the available context size") refuse a session past the
# model's context.
TOO_LONG = re.compile(r"too long|context (size|length|window)", re.IGNORECASE)
# USD per million tokens: input, 1-hour cache write, cache read, output. A model missing here (one a local server
# or another gateway names) records its tokens without a cost.
PRICES = {
    "claude-fable-5-2": (8, 16, 0.20, 40),
    "claude-opus-5-5": (4, 8, 0.20, 20),
    "claude-opus-5": (5, 10, 0.50, 25),
    "claude-sonnet-5-5": (2, 4, 0.10, 10),
    "claude-sonnet-5": (2, 4, 0.20, 10),
    "claude-haiku-5-5": (0.10, 0.20, 0.01, 0.50),
    "claude-haiku-4-5": (1, 2, 0.10, 5),
}
# Claude Haiku 5.5 bills a request whose prompt is over 100,000 tokens at these prices instead.
LONG_PROMPT = 100_000
LONG_PRICES = {"claude-haiku-5-5": (0.50, 1, 0.05, 2.50)}
# Models whose refusals the API can hand to another model in the same request.
FALLBACKS = ("claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.AsyncAnthropic | None = None


async def start() -> None:
    """The client reads ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) and ANTHROPIC_BASE_URL, so a gateway or a local
    server that speaks the Messages API stands in for Anthropic."""
    global _client
    _client = anthropic.AsyncAnthropic()


async def stop() -> None:
    if _client:
        await _client.close()


def _sessions(cwd: Path) -> Path:
    """Beside the agent folders of the other backends, so the clean-up of an old course takes its sessions too."""
    return db.DB_PATH.parent / "agents" / cwd.name / "api-sessions"


def _load(path: Path) -> list[dict] | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def _save(path: Path, messages: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = path.with_suffix(".part")
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
        json.dump(messages, out)
    partial.replace(path)


def cost(model: str, usage) -> float | None:
    """What one request cost at the API list price; None for a model without a price here."""
    prompt = usage.input_tokens + (usage.cache_read_input_tokens or 0) + (usage.cache_creation_input_tokens or 0)
    prices = LONG_PRICES.get(model) if prompt > LONG_PROMPT else None
    if not (prices := prices or PRICES.get(model)):
        return None
    base, write, read, output = prices
    return (usage.input_tokens * base + (usage.cache_creation_input_tokens or 0) * write
            + (usage.cache_read_input_tokens or 0) * read + usage.output_tokens * output) / 1e6


class Usage:
    """A turn's tokens and cost over all its requests."""

    def __init__(self):
        self.models: list[str] = []
        self.used = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}

    def add(self, message) -> None:
        u = message.usage
        if message.model not in self.models:
            self.models.append(message.model)
        self.used["input"] += u.input_tokens
        self.used["output"] += u.output_tokens
        self.used["cache_read"] += u.cache_read_input_tokens or 0
        self.used["cache_write"] += u.cache_creation_input_tokens or 0
        price = cost(message.model, u)
        self.used["cost"] = None if price is None or self.used["cost"] is None else self.used["cost"] + price

    def report(self) -> dict | None:
        return {"model": ", ".join(self.models), **self.used} if self.models else None


def _tool(tool) -> dict:
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


def _result_content(result: CallToolResult) -> list[dict]:
    content = []
    for part in result.content:
        if isinstance(part, TextContent):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, ImageContent):
            content.append({"type": "image", "source": {"type": "base64", "media_type": part.mime_type, "data": part.data}})
        else:
            content.append({"type": "text", "text": part.model_dump_json(exclude_none=True)})
    return content or [{"type": "text", "text": "done"}]


async def _call(tools: Client, block) -> dict:
    """The tool_result of one tool_use; a failed call answers as an error, so the model can recover."""
    try:
        result = await tools.call_tool(block.name, block.input)
    except Exception as e:
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": str(e) or type(e).__name__}
    return {"type": "tool_result", "tool_use_id": block.id, "is_error": bool(result.is_error), "content": _result_content(result)}


def _went_through(result: dict) -> bool:
    """A tool that refuses answers with an error, or with text that starts like one of tutor.REFUSALS."""
    return not result["is_error"] and not any(
        part.get("type") == "text" and part["text"].startswith(tutor.REFUSALS) for part in result["content"]
    )


def _request(model: str, phase: str, tools: list[dict], messages: list[dict]) -> dict:
    request = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt(phase),
        "tools": tools,
        "messages": messages,
        # The tools, the prompt and the conversation so far are read from the cache on the next request. An hour, not
        # the default five minutes: a learner often pauses longer, and app.COLD_AFTER keeps the lesson in its session.
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    if model in FALLBACKS:
        request |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return request


@asynccontextmanager
async def _tools(token: str):
    """The server's MCP tools as this turn sees them: its token rides on every call."""
    async with create_mcp_http_client(headers={**MCP_HEADERS, TURN_HEADER: token}) as http:
        async with Client(streamable_http_client(MCP_URL, http_client=http, terminate_on_close=False)) as tools:
            yield tools


def _trim(messages: list[dict]) -> bool:
    """Drop the older half of the session's turns in place, never the turn under way; False when only that is left."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)]
    if len(starts) < 2:
        return False
    del messages[: starts[len(starts) // 2]]
    return True


def _shown(event) -> dict | None:
    if event.type == "message_start":
        return {"type": "chat.break"}
    if event.type == "content_block_start" and event.content_block.type == "tool_use":
        return {"type": "activity", "tool": event.content_block.name.lower()}
    if event.type == "content_block_delta" and event.delta.type == "text_delta":
        return {"type": "chat.delta", "text": event.delta.text}
    return None


async def _stream(
    model: str, phase: str, listed: list, messages: list[dict], path: Path, usage: Usage, got: list
) -> AsyncIterator[dict]:
    """One request, its events as they stream; the final message goes into got, nothing when the turn asks again."""
    started = False
    try:
        async with _client.beta.messages.stream(**_request(model, phase, listed, messages)) as stream:
            try:
                async for event in stream:
                    started = started or event.type == "message_start"
                    if shown := _shown(event):
                        yield shown
            except httpx2.TransportError:
                # What streamed before the cut is billed all the same.
                if started:
                    usage.add(stream.current_message_snapshot)
                raise
            got.append(await stream.get_final_message())
    except anthropic.BadRequestError as e:
        # A session grown past the model's context: its older turns go, and the turn asks again without them.
        if not started and TOO_LONG.search(e.message) and _trim(messages):
            _save(path, messages)
            return
        raise


def _ended(message, calls: list, messages: list[dict], path: Path, usage: Usage) -> dict | None:
    """The turn.done a reply ends the turn with, None when the tools it called are to run."""
    if message.stop_reason == "refusal":
        _save(path, messages)
        return {"type": "turn.done", "ok": False, "error": "the model declined to answer", "usage": usage.report()}
    if message.stop_reason == "max_tokens":
        if calls:
            # A tool call cut off mid-input never runs; the cut call stays out of the session.
            messages.pop()
        _save(path, messages)
        return {"type": "turn.done", "ok": False, "error": f"the reply ran past {MAX_TOKENS} tokens", "usage": usage.report()}
    if not calls:
        _save(path, messages)
        return {"type": "turn.done", "ok": True, "error": None, "usage": usage.report()}
    return None


async def _converse(
    model: str, phase: str, tools: Client, messages: list[dict], path: Path, usage: Usage, token: str
) -> AsyncIterator[dict]:
    """Ask the model, run the tools it calls, and ask again until it ends its turn."""
    listed = [_tool(t) for t in (await tools.list_tools()).tools]
    for _ in range(MAX_ROUNDS):
        got: list = []
        async for event in _stream(model, phase, listed, messages, path, usage, got):
            yield event
        if not got:
            continue
        message = got[0]
        usage.add(message)
        messages.append({"role": "assistant", "content": [block.to_dict() for block in message.content]})
        calls = [block for block in message.content if block.type == "tool_use"]
        if done := _ended(message, calls, messages, path, usage):
            yield done
            return
        # One after another: the tools change the lesson, and the results go back together in one message.
        results = [await _call(tools, block) for block in calls]
        messages.append({"role": "user", "content": results})
        _save(path, messages)
        if tutor.ends_turn(token, [(block.name, _went_through(result)) for block, result in zip(calls, results)]):
            # The card is up and the learner answers next: asking again would only buy a line pointing at it. The
            # results stay in the session, and the next turn's prompt joins them in one user message.
            yield {"type": "turn.done", "ok": True, "error": None, "usage": usage.report()}
            return
    yield {"type": "turn.done", "ok": False, "error": f"the tutor called tools {MAX_ROUNDS} times in one reply without finishing it, so it was stopped", "usage": usage.report()}


async def run_turn(
    prompt: str, *, session_id: str, resume: bool, name: str, cwd: Path, phase: str, token: str
) -> AsyncIterator[dict]:
    # name: unused here; a session is a file of messages, named by its id.
    path = _sessions(cwd) / f"{session_id}.json"
    messages = _load(path) if resume else None
    if messages is None:
        # A session this server no longer has goes on in a fresh one; the state header of every turn carries it over.
        session_id = session_id if not resume else str(uuid.uuid4())
        path = _sessions(cwd) / f"{session_id}.json"
        messages = []
    yield {"type": "session.started", "session_id": session_id}
    messages.append({"role": "user", "content": prompt})
    _save(path, messages)
    usage = Usage()
    model = model_for(phase)
    events: asyncio.Queue[dict | None] = asyncio.Queue()

    async def converse() -> None:
        try:
            async with _tools(token) as tools:
                # Caught inside the MCP client: its task group would hand them on wrapped in an ExceptionGroup.
                try:
                    async for event in _converse(model, phase, tools, messages, path, usage, token):
                        await events.put(event)
                except anthropic.APIStatusError as e:
                    await events.put({"type": "turn.done", "ok": False, "error": f"the model API answered {e.status_code}: {e.message}"[:500], "usage": usage.report()})
                except (anthropic.APIConnectionError, httpx2.TransportError) as e:
                    # A stream cut off midway raises the transport's own error, not the SDK's.
                    await events.put({"type": "turn.done", "ok": False, "error": f"the model API could not be reached: {e}"[:500], "usage": usage.report()})
        finally:
            events.put_nowait(None)

    # The MCP client's task group lives in a task of its own: the app closes this generator as soon as the turn is done
    # (or stopped), and closing it while it waits inside a task group would raise out of the group.
    task = asyncio.create_task(converse())
    try:
        while (event := await events.get()) is not None:
            yield event
        await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
