import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import anthropic
import anyio
import httpx2
import pytest
from mcp.types import CallToolResult, TextContent

from wise_scholar import backends, db
from wise_scholar.backends import api


def reply(*blocks: dict, stop: str, model: str = "claude-sonnet-5-5", tokens: tuple = (100, 20, 0, 0)) -> str:
    """The server-sent events of one streamed message; tokens: input, output, cache read, cache write."""
    inputs, output, read, write = tokens
    events = [{"type": "message_start", "message": {
        "id": "msg", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": inputs, "output_tokens": 0, "cache_read_input_tokens": read, "cache_creation_input_tokens": write},
    }}]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}}]
        else:
            events += [{"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}}]
        events.append({"type": "content_block_stop", "index": i})
    events += [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": output}},
               {"type": "message_stop"}]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


class CutStream(httpx2.AsyncByteStream):
    """A reply stream the server drops partway through."""

    def __init__(self, text: str):
        self.text = text

    async def __aiter__(self):
        yield self.text[: len(self.text) // 2].encode()
        raise httpx2.RemoteProtocolError("peer closed connection without sending complete message body")


class FakeAPI:
    """Answers each request with the next reply, and keeps what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({"body": json.loads(request.content), "beta": request.headers.get("anthropic-beta")})
        answer = self.replies.pop(0)
        if isinstance(answer, int):
            return httpx2.Response(answer, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        if isinstance(answer, tuple):
            status, message = answer
            return httpx2.Response(status, json={"type": "error", "error": {"type": "invalid_request_error", "message": message}})
        if isinstance(answer, CutStream):
            return httpx2.Response(200, stream=answer, headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, text=answer, headers={"content-type": "text/event-stream"})


class FakeTools:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="add_block", description="Add a block.", input_schema={"type": "object"})])

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        self.calls.append((name, arguments))
        return CallToolResult(content=[TextContent(type="text", text="refused" if self.fail else "added")], is_error=self.fail)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    tools = FakeTools()

    @asynccontextmanager
    async def connect(token):
        # Like the MCP client, which holds the turn inside a task group.
        async with anyio.create_task_group():
            yield tools

    monkeypatch.setattr(api, "_tools", connect)

    def use(*replies, model="claude-sonnet-5-5"):
        server = FakeAPI(*replies)
        transport = httpx2.MockTransport(server.handle)
        monkeypatch.setattr(api, "_client", anthropic.AsyncAnthropic(
            api_key="test", base_url="http://api.test", max_retries=0,
            http_client=anthropic.DefaultAsyncHttpxClient(transport=transport),
        ))
        monkeypatch.setattr(api, "model_for", lambda phase: model)
        return server, tools

    return use


def turn(prompt="hi", *, session_id="s1", resume=False) -> list[dict]:
    async def run():
        return [e async for e in api.run_turn(
            prompt, session_id=session_id, resume=resume, name="n", cwd=Path("/workspace/course"), phase="lesson", token="t",
        )]

    return asyncio.run(run())


def session(session_id="s1") -> list[dict]:
    return json.loads((db.DB_PATH.parent / "agents" / "course" / "api-sessions" / f"{session_id}.json").read_text())


def test_a_turn_streams_the_reply_runs_the_tools_it_calls_and_asks_again_until_it_ends(fake):
    server, tools = fake(
        reply({"type": "text", "text": "Let me add that."}, {"type": "tool_use", "id": "t1", "name": "add_block", "input": {"text": "x"}},
              stop="tool_use", tokens=(100, 20, 0, 1000)),
        reply({"type": "text", "text": "Done."}, stop="end_turn", tokens=(10, 5, 1000, 0)),
    )
    events = turn()
    assert events[0] == {"type": "session.started", "session_id": "s1"}
    assert [e for e in events[1:-1]] == [
        {"type": "chat.break"}, {"type": "chat.delta", "text": "Let me add that."}, {"type": "activity", "tool": "add_block"},
        {"type": "chat.break"}, {"type": "chat.delta", "text": "Done."},
    ]
    done = events[-1]
    assert done["ok"] and done["error"] is None
    assert done["usage"] == {"model": "claude-sonnet-5-5", "input": 110, "output": 25, "cache_read": 1000, "cache_write": 1000,
                             "cost": pytest.approx((110 * 2 + 1000 * 4 + 1000 * 0.10 + 25 * 10) / 1e6)}
    assert tools.calls == [("add_block", {"text": "x"})]
    first, second = (r["body"] for r in server.requests)
    assert first["system"] == backends.system_prompt("lesson")
    assert first["tools"] == [{"name": "add_block", "description": "Add a block.", "input_schema": {"type": "object"}}]
    assert first["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert first["fallbacks"] == "default" and server.requests[0]["beta"] == api.FALLBACK_BETA
    assert second["messages"][-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": [{"type": "text", "text": "added"}]},
    ]}
    assert [m["role"] for m in session()] == ["user", "assistant", "user", "assistant"]


def test_a_resumed_turn_goes_on_in_its_session_and_a_lost_one_in_a_fresh_one(fake):
    server, _ = fake(reply({"type": "text", "text": "One."}, stop="end_turn"), reply({"type": "text", "text": "Two."}, stop="end_turn"))
    turn("first")
    events = turn("second", resume=True)
    assert events[0] == {"type": "session.started", "session_id": "s1"}
    assert [m["content"] for m in server.requests[1]["body"]["messages"]] == [
        "first", [{"type": "text", "text": "One."}], "second",
    ]
    server, _ = fake(reply({"type": "text", "text": "Fresh."}, stop="end_turn"))
    events = turn("third", session_id="gone", resume=True)
    assert events[0]["session_id"] != "gone"
    assert [m["content"] for m in server.requests[0]["body"]["messages"]] == ["third"]
    assert session(events[0]["session_id"])[0]["content"] == "third"


def test_a_failed_tool_call_answers_as_an_error_the_model_can_recover_from(fake, monkeypatch):
    server, tools = fake(
        reply({"type": "tool_use", "id": "t1", "name": "add_block", "input": {}}, stop="tool_use"),
        reply({"type": "text", "text": "Sorry."}, stop="end_turn"),
    )
    tools.fail = True
    assert turn()[-1]["ok"]
    assert server.requests[1]["body"]["messages"][-1]["content"][0]["is_error"] is True


def test_a_tool_call_cut_off_by_the_token_limit_never_runs(fake):
    server, tools = fake(reply({"type": "tool_use", "id": "t1", "name": "add_block", "input": {"text": "x"}}, stop="max_tokens"))
    done = turn()[-1]
    assert not done["ok"] and "tokens" in done["error"]
    assert tools.calls == []
    assert [m["role"] for m in session()] == ["user"]


def test_a_refusal_or_an_api_error_ends_the_turn_with_what_it_used(fake):
    fake(reply({"type": "text", "text": ""}, stop="refusal"))
    done = turn()[-1]
    assert not done["ok"] and "declined" in done["error"] and done["usage"]["input"] == 100
    fake(529)
    done = turn(session_id="s2")[-1]
    assert not done["ok"] and "529" in done["error"] and done["usage"] is None
    fake(CutStream(reply({"type": "text", "text": "Half a reply."}, stop="end_turn")))
    done = turn(session_id="s3")[-1]
    assert not done["ok"] and "could not be reached" in done["error"] and done["usage"]["input"] == 100


def test_a_model_that_keeps_calling_tools_stops_after_max_rounds(fake, monkeypatch):
    monkeypatch.setattr(api, "MAX_ROUNDS", 3)
    call = reply({"type": "tool_use", "id": "t1", "name": "add_block", "input": {}}, stop="tool_use")
    server, tools = fake(call, call, call)
    done = turn()[-1]
    assert not done["ok"] and "3 times" in done["error"] and done["usage"]["input"] == 300
    assert len(server.requests) == 3 and len(tools.calls) == 3


def test_a_session_past_the_context_drops_its_older_turns_and_asks_again(fake):
    answers = [reply({"type": "text", "text": f"Reply {n}."}, stop="end_turn") for n in range(3)]
    fake(*answers)
    for n in range(3):
        turn(f"turn {n}", resume=n > 0)
    too_long = (400, "prompt is too long: 210000 tokens > 200000 maximum")
    server, _ = fake(too_long, reply({"type": "text", "text": "Still here."}, stop="end_turn"))
    done = turn("turn 3", resume=True)[-1]
    assert done["ok"]
    sent = [m["content"] for m in server.requests[1]["body"]["messages"] if m["role"] == "user"]
    assert sent == ["turn 2", "turn 3"]
    assert [m["content"] for m in session() if m["role"] == "user"] == ["turn 2", "turn 3"]

    # Down to the turn under way, nothing is left to drop.
    server, _ = fake(too_long, too_long, too_long)
    done = turn("huge", session_id="s9")[-1]
    assert not done["ok"] and "400" in done["error"] and len(server.requests) == 1


def test_the_tools_connection_carries_the_server_secret_and_the_turn_token(monkeypatch):
    seen = {}

    @asynccontextmanager
    async def http_client(headers):
        seen["headers"] = headers
        yield "http"

    class Client:
        def __init__(self, transport):
            seen["transport"] = transport

        async def __aenter__(self):
            return "tools"

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(api, "create_mcp_http_client", http_client)
    monkeypatch.setattr(api, "streamable_http_client", lambda url, http_client, terminate_on_close: (url, http_client))
    monkeypatch.setattr(api, "Client", Client)

    async def connect():
        async with api._tools("tok") as tools:
            return tools

    assert asyncio.run(connect()) == "tools"
    assert seen == {"headers": {**backends.MCP_HEADERS, backends.TURN_HEADER: "tok"}, "transport": (backends.MCP_URL, "http")}


def test_a_model_without_a_price_records_its_tokens_without_a_cost_and_no_fallback(fake):
    server, _ = fake(reply({"type": "text", "text": "Hi."}, stop="end_turn", model="qwen3:8b"), model="qwen3:8b")
    done = turn()[-1]
    assert done["usage"]["model"] == "qwen3:8b" and done["usage"]["cost"] is None and done["usage"]["input"] == 100
    assert "fallbacks" not in server.requests[0]["body"] and server.requests[0]["beta"] is None


def test_haiku_bills_a_prompt_over_100k_tokens_at_its_long_prompt_prices():
    usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    assert api.cost("claude-haiku-5-5", usage) == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    usage.cache_read_input_tokens = 100_000
    assert api.cost("claude-haiku-5-5", usage) == pytest.approx((1000 * 0.50 + 100_000 * 0.05 + 100 * 2.50) / 1e6)


def test_the_anthropic_backend_picks_a_model_per_kind(monkeypatch):
    monkeypatch.setattr(backends, "BACKEND", "anthropic")
    monkeypatch.setattr(backends, "MODEL", "")
    monkeypatch.setattr(backends, "MODELS", {"cards": "qwen3:8b"})
    assert backends.model_for("lesson-teacher") == "claude-opus-5-5"
    assert backends.model_for("graph") == "claude-sonnet-5-5"
    assert backends.model_for("cards") == "qwen3:8b"
    monkeypatch.setattr(backends, "MODELS", {"lesson": "sonnet"})
    assert backends.model_for("lesson-teacher") == "claude-sonnet-5-5"
    monkeypatch.setattr(backends, "MODELS", {})
    monkeypatch.setattr(backends, "MODEL", "haiku")
    assert backends.model_for("lesson") == "claude-haiku-5-5"
    monkeypatch.setattr(backends, "MODEL", "claude-sonnet-5-5")
    assert backends.model_for("lesson") == "claude-sonnet-5-5"


def test_closing_the_turn_early_as_the_app_does_ends_it_cleanly(fake):
    fake(reply({"type": "text", "text": "Done."}, stop="end_turn"), reply({"type": "text", "text": "Again."}, stop="end_turn"))

    async def run(stop_at):
        events = api.run_turn("hi", session_id=stop_at, resume=False, name="n", cwd=Path("/workspace/course"), phase="lesson", token="t")
        async for event in events:
            if event["type"] == stop_at:
                break
        await events.aclose()
        return event

    assert asyncio.run(run("turn.done"))["ok"]
    assert asyncio.run(run("chat.delta"))["text"] == "Again."


def test_every_prefix_a_tool_answers_with_is_known_as_a_refusal_or_a_success():
    import re

    from wise_scholar import tutor

    tools = Path(tutor.__file__).parent / "tools"
    said = {m for path in tools.glob("*.py") for m in re.findall(r'return f?"(\w+):', path.read_text())}
    assert said - {p.rstrip(":") for p in tutor.REFUSALS} == {"recorded"}


def test_a_reply_that_poses_a_card_ends_the_turn_without_asking_again(fake, monkeypatch):
    from wise_scholar import tutor

    monkeypatch.setattr(tutor, "_turn_of", lambda token: {"kind": "lesson", "lesson_id": 1})
    monkeypatch.setattr(tutor.db, "lesson", lambda lesson_id: {"mode": "learner", "batch": 0})
    pose = reply({"type": "tool_use", "id": "t1", "name": "pose_quiz", "input": {}}, stop="tool_use")
    server, tools = fake(pose)
    done = turn()[-1]
    assert done["ok"] and len(server.requests) == 1 and tools.calls == [("pose_quiz", {})]
    assert [m["role"] for m in session()] == ["user", "assistant", "user"]

    server, tools = fake(pose, reply({"type": "text", "text": "Retry."}, stop="end_turn"))
    tools.fail = True
    assert turn(session_id="s2")[-1]["ok"] and len(server.requests) == 2

    monkeypatch.setattr(tutor.db, "lesson", lambda lesson_id: {"mode": "learner", "batch": 1})
    server, _ = fake(pose, reply({"type": "text", "text": "More."}, stop="end_turn"))
    assert turn(session_id="s3")[-1]["ok"] and len(server.requests) == 2
