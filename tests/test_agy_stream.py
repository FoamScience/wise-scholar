import json

from wise_scholar import backends
from wise_scholar.backends import agy
from wise_scholar.backends.agy import EventParser
from wise_scholar.backends.agy_gate import decide


def step(index: int, kind: str, **fields) -> str:
    return json.dumps({"event": "step_update", "step_update": {"conversation_id": "c", "step_index": index, "step_type": kind, **fields}})


def mcp_call(index: int, state: str, server: str = "scholar") -> str:
    params = {"Arguments": {}, "ServerName": server, "ToolName": "Add_Block"}
    return step(index, "tool", state=state, tool_name="call_mcp_tool", tool_info={"name": "call_mcp_tool", "parameters": params})


def test_stream_lines_map_to_ui_events():
    p = EventParser()
    assert p.feed(json.dumps({"event": "init", "conversation_id": "c1", "init": {"tools": []}})) == [
        {"type": "session.started", "session_id": "c1"}]
    assert p.feed(step(0, "user_input", state="DONE")) == []
    assert p.feed(step(1, "agent_response", state="DONE")) == [{"type": "chat.break"}]
    assert p.feed(mcp_call(2, "ACTIVE")) == [{"type": "activity", "tool": "add_block"}]
    assert p.feed(mcp_call(2, "DONE")) == []
    assert p.feed(mcp_call(3, "ACTIVE", server="other")) == []
    assert p.feed(step(4, "tool", state="ERROR", tool_name="run_command")) == []
    assert p.feed(step(5, "agent_response", state="ACTIVE", text_delta="Hello,")) == [
        {"type": "chat.break"}, {"type": "chat.delta", "text": "Hello,"}]
    assert p.feed(step(5, "agent_response", state="ACTIVE", text_delta=" you")) == [{"type": "chat.delta", "text": " you"}]
    assert p.feed("jetski: no output produced") == []


def test_a_result_ends_the_turn_with_its_tokens():
    used = {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 7, "cache_read_tokens": 3, "total_tokens": 25}
    done = EventParser().feed(json.dumps({"event": "result", "result": {"status": "SUCCESS", "usage": used}}))
    assert done == [{"type": "turn.done", "ok": True, "error": None, "usage": {
        "model": agy.MODEL or "agy", "input": 10, "output": 12, "cache_read": 3, "cache_write": 0, "cost": None}}]
    failed = EventParser().feed(json.dumps({"event": "result", "result": {"status": "ERROR", "error": "bad input"}}))
    assert failed == [{"type": "turn.done", "ok": False, "error": "bad input", "usage": None}]


def test_the_gate_lets_only_the_tutor_tools_and_their_schemas_through(tmp_path):
    schemas = str(tmp_path / "mcp" / "scholar")
    assert decide({"name": "call_mcp_tool", "args": {"ServerName": "scholar", "ToolName": "add_block"}}, schemas) == "allow"
    assert decide({"name": "call_mcp_tool", "args": {"ServerName": "other"}}, schemas) == "deny"
    assert decide({"name": "read_file", "args": {"Path": f"{schemas}/add_block.json"}}, schemas) == "allow"
    assert decide({"name": "read_file", "args": {"Path": f"{schemas}/../../oauth_creds.json"}}, schemas) == "deny"
    assert decide({"name": "read_file", "args": {"Path": f"{schemas}-evil/x.json"}}, schemas) == "deny"
    for name in ("run_command", "write_to_file", "search_web", "browser_subagent", "invoke_subagent"):
        assert decide({"name": name, "args": {}}, schemas) == "deny"


def test_a_turn_folder_holds_its_token_the_gate_and_the_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(agy, "TURNS", tmp_path)
    folder = agy.workspace("tok", "lesson")
    config = folder / ".agents" / "mcp_config.json"
    server = json.loads(config.read_text())["mcpServers"]["scholar"]
    assert server["headers"] == {**backends.MCP_HEADERS, "X-Scholar-Turn": "tok"} and oct(config.stat().st_mode)[-3:] == "600"
    hooks = json.loads((folder / ".agents" / "hooks.json").read_text())
    assert str(agy.GATE) in hooks["scholar-gate"]["PreToolUse"][0]["hooks"][0]["command"]
    rules = sorted(p.name for p in (folder / ".agents" / "rules").iterdir())
    assert rules == ["core.md", "lesson.md"]
    assert (folder / ".agents" / "rules" / "core.md").read_text().startswith("---\ntrigger: always_on\n---\n")
    assert (folder / ".git").is_dir()
    assert [p.name for p in (agy.workspace("tok2", "graph") / ".agents" / "rules").iterdir()] == ["graph.md"]
