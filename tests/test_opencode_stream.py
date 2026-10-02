from wise_scholar.backends.opencode import EventParser

SID = "ses_1"


def ev(kind, **properties):
    return {"type": kind, "properties": {"sessionID": SID, **properties}}


def part(part_id, kind, message="msg_a", **extra):
    return ev("message.part.updated", part={"id": part_id, "messageID": message, "type": kind, **extra})


def test_parser_streams_only_assistant_text_of_its_session():
    p = EventParser(SID)
    assert p.feed(ev("message.updated", info={"id": "msg_u", "role": "user"})) == []
    assert p.feed(part("prt_u", "text", message="msg_u", text="[learner] hi")) == []
    assert p.feed(ev("message.updated", info={"id": "msg_a", "role": "assistant"})) == []

    assert p.feed(part("prt_r", "reasoning", text="")) == []
    assert p.feed(ev("message.part.delta", messageID="msg_a", partID="prt_r", field="text", delta="hmm")) == []

    assert p.feed(part("prt_tool", "tool", tool="scholar_add_block", state={"status": "pending"})) == [
        {"type": "activity", "tool": "add_block"}
    ]
    assert p.feed(part("prt_tool", "tool", tool="scholar_add_block", state={"status": "completed"})) == []

    assert p.feed(part("prt_t", "text", text="")) == [{"type": "chat.break"}]
    assert p.feed(ev("message.part.delta", messageID="msg_a", partID="prt_t", field="text", delta="Hello")) == [
        {"type": "chat.delta", "text": "Hello"}
    ]
    assert p.feed(part("prt_t", "text", text="Hello")) == []

    other = {"type": "session.idle", "properties": {"sessionID": "ses_other"}}
    assert p.feed(other) == []
    assert p.feed({"type": "server.connected", "properties": {}}) == []
    assert p.feed(ev("session.idle")) == [{"type": "turn.done", "ok": True, "error": None}]


def test_parser_reports_session_errors():
    p = EventParser(SID)
    assert p.feed(ev("session.error", error={"name": "APIError", "data": {"message": "rate limited"}})) == [
        {"type": "turn.done", "ok": False, "error": "rate limited"}
    ]
