from wise_scholar.backends.opencode import EventParser

SID = "ses_1"


def ev(kind, **data):
    return {"id": "evt_1", "type": kind, "data": {"sessionID": SID, **data}}


def test_parser_streams_only_assistant_text_of_its_session():
    p = EventParser(SID)
    assert p.feed({"id": "evt_0", "type": "server.connected", "data": {}}) == []
    assert p.feed(ev("session.inbox.enqueued", item={"type": "user", "payload": {"text": "[learner] hi"}})) == []
    assert p.feed(ev("session.execution.started")) == []
    assert p.feed(ev("session.reasoning.delta", assistantMessageID="msg_a", ordinal=0, delta="hmm")) == []

    assert p.feed(ev("session.tool.input.started", assistantMessageID="msg_a", id="call_1", name="scholar_add_block")) == [
        {"type": "activity", "tool": "add_block"}
    ]
    assert p.feed(ev("session.tool.success", assistantMessageID="msg_a", id="call_1", content=[])) == []

    assert p.feed(ev("session.text.started", assistantMessageID="msg_a", ordinal=0)) == [{"type": "chat.break"}]
    assert p.feed(ev("session.text.delta", assistantMessageID="msg_a", ordinal=0, delta="Hello")) == [
        {"type": "chat.delta", "text": "Hello"}
    ]
    assert p.feed(ev("session.text.ended", assistantMessageID="msg_a", ordinal=0, text="Hello")) == []

    other = {"id": "evt_2", "type": "session.execution.succeeded", "data": {"sessionID": "ses_other"}}
    assert p.feed(other) == []
    tokens = {"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 300, "write": 40}}
    assert p.feed(ev("session.step.ended", assistantMessageID="msg_a", cost=0.002, tokens=tokens)) == []
    assert p.feed(ev("session.usage.recorded", source="title", cost=0.001, tokens={"input": 10, "output": 3})) == []
    assert p.feed({"id": "evt_3", "type": "session.step.ended", "data": {"sessionID": "ses_other", "cost": 9, "tokens": tokens}}) == []
    assert p.feed(ev("session.execution.succeeded")) == [{"type": "turn.done", "ok": True, "error": None, "usage": {
        "model": "opencode", "input": 110, "output": 28, "cache_read": 300, "cache_write": 40, "cost": 0.003,
    }}]


def test_parser_reports_failed_and_interrupted_turns():
    p = EventParser(SID)
    failed = ev("session.execution.failed", error={"type": "provider.no-route", "message": "Model unavailable: openrouter/x"})
    nothing = {"model": "opencode", "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}
    assert p.feed(failed) == [{"type": "turn.done", "ok": False, "error": "Model unavailable: openrouter/x", "usage": nothing}]
    assert p.feed(ev("session.execution.interrupted")) == [{"type": "turn.done", "ok": False, "error": "the turn was interrupted", "usage": nothing}]
