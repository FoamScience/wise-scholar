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
    assert p.feed(ev("session.execution.succeeded")) == [{"type": "turn.done", "ok": True, "error": None}]


def test_parser_reports_failed_and_interrupted_turns():
    p = EventParser(SID)
    failed = ev("session.execution.failed", error={"type": "provider.no-route", "message": "Model unavailable: openrouter/x"})
    assert p.feed(failed) == [{"type": "turn.done", "ok": False, "error": "Model unavailable: openrouter/x"}]
    assert p.feed(ev("session.execution.interrupted")) == [{"type": "turn.done", "ok": False, "error": "the turn was interrupted"}]
