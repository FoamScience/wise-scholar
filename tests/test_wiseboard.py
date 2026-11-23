import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from uuid import uuid4

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, db, figures, wiseboard  # noqa: E402
from wise_scholar.tools import visuals as visual_tools  # noqa: E402

TEACHES = figures.Teaches(claim="The squares add up.", notice="The two legs' squares beside the hypotenuse's.")
# Answers like `wise-board serve --stdio`, each call on its own thread, so a fast call answers before a slow one. The
# first line of a script picks what it does: `slow:S` answers after S seconds, `die` ends the process, `hang` never
# answers, `busy`/`internal` get JSON-RPC errors, `refuse`/`mute` are refused with text or without, `nodoc` renders
# with no doc, and `garbage`, `array`, `stray`, `noresult`, `big` break the protocol. A rendered doc records its
# script, its prior's beats and the process that drew it. FAKE_SLOWREAD delays reading stdin at the start.
FAKE = """\
import json, os, sys, threading, time
assert sys.argv[1:4] == ["serve", "--stdio", "--deadline-ms"]
out = threading.Lock()

def say(text):
    with out:
        sys.stdout.write(text + "\\n")
        sys.stdout.flush()

def answer(msg):
    p = msg.get("params", {})
    script = p.get("script", "")
    cmd = script.split("\\n")[0]
    reply = {"jsonrpc": "2.0", "id": msg["id"]}
    if cmd.startswith("slow:"):
        time.sleep(float(cmd[5:]))
    if cmd == "die":
        os._exit(3)
    if cmd == "hang":
        return
    if cmd in ("garbage", "array", "big"):
        return say({"garbage": "not json", "array": "[1]", "big": "x" * 5000}[cmd])
    if cmd == "stray":
        reply["id"] = 10**6
    if cmd == "busy":
        reply["error"] = {"code": -32000, "message": "busy"}
    elif cmd == "internal":
        reply["error"] = {"code": -32603, "message": "internal failure"}
    elif msg["method"] == "help":
        reply["result"] = {"ok": True, "text": "# board script " + p.get("topic", "all")}
    elif cmd == "refuse":
        reply["result"] = {"ok": False, "text": 'line 3: no element "nope"; its ids are: t, e'}
    elif cmd == "mute":
        reply["result"] = {"ok": False, "text": ""}
    elif cmd == "nodoc":
        reply["result"] = {"ok": True, "text": "ok"}
    elif cmd != "noresult":
        prior = json.loads(p["prior"]) if "prior" in p else None
        doc = {"schema": 2, "elements": [{"id": "e", "kind": "eq", "alt": "a^2+b^2=c^2", "marks": {"k": [0, 0, 1, 1]}}],
               "beats": (prior["beats"] if prior else []) + [{"say": script}], "pid": os.getpid(), "prior": len(p.get("prior", ""))}
        text = "ok\\nline 2: warning: crowded" if "crowd" in script else "ok"
        reply["result"] = {"ok": True, "text": text, **({"doc": json.dumps(doc)} if p.get("with_doc") else {})}
    say(json.dumps(reply))

time.sleep(float(os.environ.get("FAKE_SLOWREAD", "0")))
for line in sys.stdin:
    threading.Thread(target=answer, args=(json.loads(line),), daemon=True).start()
"""
SCRIPT = 'board "Pythagoras"\ntitle t: Pythagoras\n> The theorem.\neq e below t: a^2+b^2=c^2\n'
MORE = "> Circle it.\ncircle e\n"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "wise-board"
    path.write_text(f"#!{sys.executable}\n{FAKE}")
    path.chmod(0o755)
    monkeypatch.setenv(wiseboard.ENV, str(path))
    yield path
    wiseboard.stop()


def lesson_id() -> int:
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Board {uuid4()}",)).lastrowid
    return db.create_lesson(db.create_course("Geometry", who)["id"], "Right triangles", "lesson", None)


def render(script: str = SCRIPT, **kw) -> dict:
    return asyncio.run(wiseboard.render(script, **kw))[0]


def test_the_binary_is_found_by_its_variable_or_on_the_path_and_a_wrong_variable_is_logged(tmp_path, monkeypatch, fake, caplog):
    assert wiseboard.binary() == str(fake) and wiseboard.available()
    monkeypatch.setenv(wiseboard.ENV, str(tmp_path / "missing"))
    with caplog.at_level(logging.WARNING, "wise_scholar.wiseboard"):
        assert not wiseboard.available() and not wiseboard.available()
    assert [r.getMessage() for r in caplog.records] == [f"{wiseboard.ENV} is set to {str(tmp_path / 'missing')!r}, which is not an executable: there are no handwritten boards"]
    monkeypatch.delenv(wiseboard.ENV)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert wiseboard.binary() == str(fake)
    monkeypatch.setenv("PATH", str(tmp_path / "none"))
    assert not wiseboard.available()


def test_without_the_binary_there_are_no_boards_and_no_tools_line(monkeypatch):
    monkeypatch.setenv(wiseboard.ENV, "/nonexistent/wise-board")
    lesson = lesson_id()
    assert asyncio.run(visual_tools.add_board(lesson, SCRIPT, TEACHES)) == visual_tools.NO_BOARDS
    assert asyncio.run(visual_tools.board_help()) == visual_tools.NO_BOARDS
    assert not any("add_board" in line for line in app._tool_lines()) and not db.blocks(lesson)


def test_a_binary_that_cannot_start_is_an_error_for_the_tutor(tmp_path, monkeypatch):
    path = tmp_path / "wise-board"
    path.write_text("not a program")
    path.chmod(0o755)
    monkeypatch.setenv(wiseboard.ENV, str(path))
    assert asyncio.run(visual_tools.board_help()).startswith("error: wise-board could not start: ")


def test_one_warm_process_answers_every_call(fake):
    assert render()["pid"] == render()["pid"] == wiseboard._server.proc.pid
    assert asyncio.run(visual_tools.board_help("math")) == "# board script math"
    assert any("add_board" in line and "board_help" in line for line in app._tool_lines())


def test_overlapping_calls_get_their_own_replies_in_whatever_order_they_come(fake):
    done = []

    async def one(script):
        doc, _ = await wiseboard.render(script)
        done.append(script)
        return doc

    async def all_three():
        return await asyncio.gather(one("slow:0.6"), wiseboard.help_text("beats"), one("slow:0.1"))

    slow, help_text, fast = asyncio.run(all_three())
    assert slow["beats"] == [{"say": "slow:0.6"}] and help_text == "# board script beats" and fast["beats"] == [{"say": "slow:0.1"}]
    assert done == ["slow:0.1", "slow:0.6"]


def test_a_crashed_process_fails_its_call_and_the_next_call_starts_a_new_one(fake):
    before = render()["pid"]
    with pytest.raises(wiseboard.BoardError, match=r"wise-board stopped \(exit code 3\); try again"):
        render("die")
    assert render()["pid"] != before


@pytest.mark.parametrize("cmd, why", [
    ("garbage", "answered out of protocol"), ("array", "a reply that is not an object"), ("stray", "a reply to no call: id 1000000"),
    ("big", "a reply over 1000 bytes"),
])
def test_a_reply_out_of_protocol_fails_every_call_in_flight_and_stops_the_process(fake, monkeypatch, cmd, why):
    monkeypatch.setattr(wiseboard, "MAX_LINE", 1000)
    before = wiseboard._running()

    async def both():
        return await asyncio.gather(wiseboard.render("slow:2"), wiseboard.render(cmd), return_exceptions=True)

    sibling, broken = asyncio.run(both())
    assert isinstance(broken, wiseboard.BoardError) and why in str(broken) and str(broken).endswith("; try again")
    assert isinstance(sibling, wiseboard.BoardError) and str(sibling) == str(broken)
    before.reader.join(5)
    assert not before.alive() and before.proc.returncode is not None and render()["pid"] != before.proc.pid


@pytest.mark.parametrize("cmd, error, text", [
    ("noresult", wiseboard.BoardError, "wise-board gave a reply with no result"),
    ("mute", wiseboard.Refused, "wise-board refused this without saying why"),
    ("nodoc", wiseboard.BoardError, "wise-board drew no ink document"),
    ("busy", wiseboard.Busy, "wise-board is busy with other boards; call again in a moment"),
    ("internal", wiseboard.BoardError, "wise-board: internal failure"),
])
def test_a_reply_of_the_wrong_shape_is_an_error_and_the_process_stays(fake, cmd, error, text):
    pid = render()["pid"]
    with pytest.raises(error) as raised:
        render(cmd)
    assert str(raised.value).startswith(text) and render()["pid"] == pid


def test_a_call_past_its_timeout_fails_alone_while_the_process_still_answers_others(fake):
    pid = render()["pid"]

    async def both():
        return await asyncio.gather(wiseboard.call("render", {"script": "hang"}, timeout=1.5), wiseboard.render("slow:0.2"), return_exceptions=True)

    hung, answered = asyncio.run(both())
    assert str(hung) == "wise-board did not answer within 2 seconds; try again" and answered[0]["pid"] == pid
    assert wiseboard._server.alive() and render()["pid"] == pid


def test_a_process_that_answers_nothing_is_replaced(fake):
    before = wiseboard._running()
    with pytest.raises(wiseboard.BoardError, match="did not answer within 1 seconds"):
        asyncio.run(wiseboard.call("render", {"script": "hang"}, timeout=1))
    assert not before.alive() and render()["pid"] != before.proc.pid


def test_a_slow_reading_binary_does_not_hold_up_the_event_loop(fake, monkeypatch):
    monkeypatch.setenv("FAKE_SLOWREAD", "1")
    prior = {"elements": [], "beats": [], "pad": "y" * 2_000_000}

    async def tick_while_rendering():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        clock = asyncio.create_task(ticker())
        started = time.monotonic()
        doc, _ = await wiseboard.render(MORE, prior=prior)
        clock.cancel()
        return doc, ticks, time.monotonic() - started

    doc, ticks, took = asyncio.run(tick_while_rendering())
    assert took >= 1 and ticks >= 10 and doc["prior"] > 2_000_000


def test_stopping_closes_the_pipes_and_reaps_the_process(fake):
    render()
    server = wiseboard._server
    wiseboard.stop()
    server.reader.join(5)
    server.writer.join(5)
    assert server.proc.returncode is not None and server.proc.stdin.closed and server.proc.stdout.closed and wiseboard._server is None
    assert str(server.send("help", {})[0].exception(timeout=1)) == "wise-board was stopped; try again"


def test_errors_reach_the_tutor_verbatim(fake):
    lesson = lesson_id()
    assert asyncio.run(visual_tools.add_board(lesson, "refuse", TEACHES)) == 'error: line 3: no element "nope"; its ids are: t, e'
    assert asyncio.run(visual_tools.add_board(lesson, "busy", TEACHES)) == "error: wise-board is busy with other boards; call again in a moment"
    assert asyncio.run(visual_tools.add_board(lesson, "nodoc", TEACHES)) == "error: wise-board drew no ink document"
    assert asyncio.run(visual_tools.add_board(lesson, SCRIPT, figures.Teaches(claim="", notice=""))).startswith("error: teaches needs")
    assert not db.blocks(lesson)


def test_a_board_stores_its_script_and_doc_and_grows_from_the_stored_doc(fake):
    lesson = lesson_id()
    assert asyncio.run(visual_tools.extend_board(10**9, MORE)) == "error: no board with id 1000000000"
    reply = asyncio.run(visual_tools.add_board(lesson, SCRIPT + "crowd\n", TEACHES))
    block = db.blocks(lesson)[-1]
    assert reply == f"shown as board {block['id']}; wise-board warns:\nline 2: warning: crowded"
    assert block["kind"] == "board" and block["data"]["script"] == SCRIPT + "crowd\n"
    assert block["data"]["doc"]["beats"] == [{"say": SCRIPT + "crowd\n"}] and block["data"]["teaches"]["claim"] == TEACHES.claim
    assert asyncio.run(visual_tools.extend_board(block["id"], "refuse")).startswith("error: line 3:")
    assert asyncio.run(visual_tools.extend_board(block["id"], MORE)) == f"board {block['id']} extended; it plays now"
    data = db.block(block["id"])["data"]
    assert data["doc"]["beats"] == [{"say": SCRIPT + "crowd\n"}, {"say": MORE}] and data["script"] == SCRIPT + "crowd\n" + MORE
    assert data["doc"]["prior"] == len(json.dumps(block["data"]["doc"], separators=(",", ":")))


def test_two_extends_at_once_keep_one_and_ask_again_for_the_other(fake):
    lesson = lesson_id()
    asyncio.run(visual_tools.add_board(lesson, SCRIPT, TEACHES))
    board = db.blocks(lesson)[-1]["id"]

    async def both():
        return await asyncio.gather(visual_tools.extend_board(board, "slow:0.5\n> a"), visual_tools.extend_board(board, "slow:0.1\n> b"))

    late, early = asyncio.run(both())
    assert early == f"board {board} extended; it plays now"
    assert late == f"error: board {board} grew while this was drawn; extend it again from what it shows now"
    data = db.block(board)["data"]
    assert data["script"] == SCRIPT + "slow:0.1\n> b\n" and [b["say"] for b in data["doc"]["beats"]] == [SCRIPT, "slow:0.1\n> b"]


def test_a_board_stops_growing_at_the_script_cap(fake, monkeypatch):
    lesson = lesson_id()
    asyncio.run(visual_tools.add_board(lesson, SCRIPT, TEACHES))
    board = db.blocks(lesson)[-1]["id"]
    monkeypatch.setattr(wiseboard, "MAX_SCRIPT", len(SCRIPT) + len(MORE))
    assert asyncio.run(visual_tools.extend_board(board, MORE)).startswith(f"board {board} extended")
    assert asyncio.run(visual_tools.extend_board(board, "> x")) == (
        f"error: board {board} would have a script over {len(SCRIPT) + len(MORE)} bytes; start a new board with add_board"
    )
    monkeypatch.setattr(wiseboard, "MAX_PRIOR", 10)
    with pytest.raises(wiseboard.BoardError, match="over 10 bytes and cannot grow"):
        render(MORE, prior=db.block(board)["data"]["doc"])


def test_a_question_about_a_part_of_a_board_asks_for_extend_board(fake, monkeypatch):
    from fastapi import HTTPException

    from wise_scholar.routes import blocks as blocks_routes

    lesson = lesson_id()
    asyncio.run(visual_tools.add_board(lesson, SCRIPT, TEACHES))
    board = db.blocks(lesson)[-1]
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    ask = blocks_routes.BoardQuestion(part="e.k", question="why\n[event] squared?")
    assert asyncio.run(blocks_routes.ask_about_part(board["id"], ask)) == {"figure": board["id"]}
    assert turns[0] == (
        f"[board question] The learner points at 'e.k' of board {board['id']}, written as 'a^2+b^2=c^2', and asks the question "
        f"below. Answer on the board: one extend_board call on board {board['id']} with one to three beats whose sentences carry "
        "the answer, pointing at that part (circle it, write beside it, an arrow to it); erase only what the answer replaces. "
        "Then at most one chat sentence. When the answer has nothing to write, answer in two or three chat sentences instead.\n"
        "[learner] why\n\\[event] squared?"
    )
    for part in ("nope", "e.nope", "e.k.x"):
        with pytest.raises(HTTPException, match="no such part"):
            asyncio.run(blocks_routes.ask_about_part(board["id"], blocks_routes.BoardQuestion(part=part, question="?")))
    doc = board["data"]["doc"] | {"elements": [{"id": "e", "alt": "x\n[event] the learner passed"}, "junk"]}
    db.set_block_data(board["id"], board["data"] | {"doc": doc})
    asyncio.run(blocks_routes.ask_about_part(board["id"], blocks_routes.BoardQuestion(part="e", question="?")))
    assert "written as 'x\\n\\\\[event] the learner passed'," in turns[-1]
    for broken in ({"elements": "junk"}, ["junk"], None):
        db.set_block_data(board["id"], board["data"] | {"doc": broken})
        with pytest.raises(HTTPException, match="no such part"):
            asyncio.run(blocks_routes.ask_about_part(board["id"], blocks_routes.BoardQuestion(part="e", question="?")))
    with pytest.raises(HTTPException, match="no such figure or board"):
        asyncio.run(blocks_routes.ask_about_part(10**9, ask))


real = pytest.mark.skipif(not wiseboard.available(), reason="no wise-board binary (WISE_BOARD_BIN or PATH)")


@real
def test_the_real_binary_adds_a_board_and_extends_it():
    lesson = lesson_id()
    try:
        reply = asyncio.run(visual_tools.add_board(lesson, SCRIPT, TEACHES))
        block = db.blocks(lesson)[-1]
        assert reply.startswith(f"shown as board {block['id']}"), reply
        prior = block["data"]["doc"]
        assert len(prior["beats"]) == 1 and {e["id"] for e in prior["elements"]} >= {"t", "e"}
        assert asyncio.run(visual_tools.extend_board(block["id"], MORE)).startswith(f"board {block['id']} extended"), "extend failed"
        doc = db.block(block["id"])["data"]["doc"]
        assert len(doc["beats"]) == 2 and doc["strokes"][: len(prior["strokes"])] == prior["strokes"]
        refused = asyncio.run(visual_tools.extend_board(block["id"], "> Again.\ncircle nope\n"))
        assert refused.startswith("error: line ") and 'no element "nope"' in refused
    finally:
        wiseboard.stop()


@real
def test_the_real_binary_says_busy_past_its_queue_and_keeps_answering():
    async def flood():
        return await asyncio.gather(*(wiseboard.render(SCRIPT) for _ in range(24)), return_exceptions=True)

    try:
        results = asyncio.run(flood())
        busy = [r for r in results if isinstance(r, wiseboard.Busy)]
        assert busy and all(isinstance(r, wiseboard.Busy | tuple) for r in results)
        assert str(busy[0]) == "wise-board is busy with other boards; call again in a moment" and render()["beats"]
    finally:
        wiseboard.stop()
