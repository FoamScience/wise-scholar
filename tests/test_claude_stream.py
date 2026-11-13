import json

from wise_scholar.backends.claude import parse_event


def stream(event: dict) -> str:
    return json.dumps({"type": "stream_event", "event": event, "session_id": "s"})


def test_parse_event_maps_stream_lines_to_ui_events():
    assert parse_event(json.dumps({"type": "system", "subtype": "init"})) == {"type": "session.started"}
    assert parse_event(json.dumps({"type": "system", "subtype": "status"})) is None
    assert parse_event(stream({"type": "message_start", "message": {}})) == {"type": "chat.break"}
    assert parse_event(
        stream({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello,"}})
    ) == {"type": "chat.delta", "text": "Hello,"}
    assert parse_event(
        stream({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{"}})
    ) is None
    assert parse_event(
        stream({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "mcp__scholar__add_block"}})
    ) == {"type": "activity", "tool": "add_block"}
    assert parse_event(json.dumps({"type": "assistant", "message": {"content": []}})) is None
    assert parse_event(json.dumps({"type": "result", "subtype": "success", "is_error": False})) == {
        "type": "turn.done", "ok": True, "error": None, "usage": None,
    }
    assert parse_event(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True})) == {
        "type": "turn.done", "ok": False, "error": "error_max_turns", "usage": None,
    }


def test_a_result_reports_this_turns_tokens_and_the_sessions_running_cost():
    result = {"type": "result", "subtype": "success", "is_error": False, "session_id": "s1", "total_cost_usd": 0.05,
              "usage": {"input_tokens": 2, "output_tokens": 30, "cache_read_input_tokens": 700, "cache_creation_input_tokens": 400},
              "modelUsage": {
        "claude-haiku-5-5": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 100, "cacheCreationInputTokens": 0, "costUSD": 0.01},
        "claude-opus-5-5": {"inputTokens": 2, "outputTokens": 40, "cacheReadInputTokens": 900, "cacheCreationInputTokens": 3000, "costUSD": 0.04},
    }}
    assert parse_event(json.dumps(result))["usage"] == {
        "model": "claude-opus-5-5, claude-haiku-5-5", "input": 2, "output": 30, "cache_read": 700, "cache_write": 400,
        "cost": 0.05, "session": "s1",
    }
