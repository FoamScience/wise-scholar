import asyncio
import base64
import io
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from wise_scholar import bundle, db, handout, obsidian, wiseboard
from wise_scholar.routes import lessons as lessons_routes

SCRIPT = 'board "Pythagoras"\ntitle t: Pythagoras\n> The theorem.\neq e below t: a^2+b^2=c^2\n'
DOC = {"schema": 2, "page": [1600, 1000], "pages": 2, "elements": [
    {"id": "t", "kind": "title", "page": 0, "alt": "Pythagoras"},
    {"id": "e", "kind": "eq", "page": 1, "alt": "a^2+b^2=c^2"},
]}
TEACHES = {"claim": "The squares add up.", "notice": "The legs' squares.", "misconception": "", "limits": "Right triangles only."}
REAL = Path(os.environ.get(wiseboard.ENV) or Path.home() / "repo/wise-board/target/debug/wise-board")
# Answers like `wise-board render - --prior FILE --svg --page N -o OUT`; FAKE_MODE picks how: `svg` draws a page,
# `hostile` draws one with a script and a handler in it, `refuse` refuses on stderr with exit 1, `crash` fails with
# exit 3, `page1` fails on page 1 only, `hang` sleeps long, `slow` takes a moment and records how many draw at once.
# Each call appends its page, whether its prior was the doc, and its pid to FAKE_LOG.
FAKE = """\
import json, os, sys, time
args = sys.argv[1:]
assert args[:2] == ["render", "-"] and "--svg" in args, args
assert sys.stdin.read() == ""
prior = json.load(open(args[args.index("--prior") + 1]))
page = int(args[args.index("--page") + 1])
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([page, prior == json.loads(os.environ["FAKE_DOC"]), os.getpid()]) + "\\n")
mode = os.environ["FAKE_MODE"]
if mode == "refuse":
    sys.stderr.write("prior: not an ink doc this engine reads\\n")
    sys.exit(1)
if mode == "crash" or (mode == "page1" and page == 1):
    sys.exit(3)
if mode == "hang":
    time.sleep(30)
if mode == "slow":
    running = os.environ["FAKE_LOG"] + ".running"
    os.makedirs(running, exist_ok=True)
    open(os.path.join(running, str(os.getpid())), "w").close()
    with open(os.environ["FAKE_LOG"] + ".most", "a") as most:
        most.write(f"{len(os.listdir(running))}\\n")
    time.sleep(0.2)
    os.remove(os.path.join(running, str(os.getpid())))
active = ' onload="x()"><script>alert(1)</script' if mode == "hostile" else ""
with open(args[args.index("-o") + 1], "w") as out:
    out.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" width="1600" height="1000"{active}>'
              f'<path d="M0 0L{page} 1" fill="#111"/></svg>')
print("ok", file=sys.stderr)
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "wise-board"
    path.write_text(f"#!{sys.executable}\n{FAKE}")
    path.chmod(0o755)
    monkeypatch.setenv(wiseboard.ENV, str(path))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls"))
    monkeypatch.setenv("FAKE_DOC", json.dumps(DOC))
    monkeypatch.setenv("FAKE_MODE", "svg")
    return tmp_path / "calls"


def calls(log: Path) -> list[list]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def pages_of(doc: dict = DOC, seconds: float = 30) -> list[str]:
    return asyncio.run(wiseboard.svg_pages(doc, time.monotonic() + seconds))


@pytest.fixture
def absent(monkeypatch):
    monkeypatch.setenv(wiseboard.ENV, "/nonexistent/wise-board")


def boarded(doc=DOC) -> dict:
    """A prepared unit whose lesson holds a prose block and a board."""
    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, 'teacher')", (f"Boarder {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course("Triangles", who)["id"]
    db.set_concepts(course, [{"title": "Geometry", "concepts": ["Right triangles"], "known": []}])
    unit = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Right triangles", "lesson", unit)
    db.add_block(lesson, "prose", "The legs and the hypotenuse.")
    board = db.add_block(lesson, "board", "", {"script": SCRIPT, "doc": doc, "teaches": TEACHES})["id"]
    db.add_block(lesson, "done", "", {})
    return {"course": course, "lesson": lesson, "board": board}


def vault_files(course: int, boards: dict) -> dict[str, bytes]:
    z = zipfile.ZipFile(io.BytesIO(obsidian.export(course, {}, boards)))
    return {name: z.read(name) for name in z.namelist()}


def lesson_note(files: dict[str, bytes]) -> str:
    return next(v.decode() for k, v in files.items() if "/Lessons/" in k and k.endswith(".md"))


def assert_text_board(text: str) -> None:
    assert "**Pythagoras**\n\n- Pythagoras\n- a^2+b^2=c^2\n" in text and "Right triangles only." in text
    assert "data:image/svg+xml" not in text and "board-" not in text


def test_a_stored_board_doc_is_shape_checked_before_it_is_drawn(fake):
    e = {"id": "e", "kind": "eq"}
    assert wiseboard.valid_doc(DOC) and wiseboard.valid_doc(DOC | {"elements": [e] * wiseboard.MAX_ELEMENTS})
    for bad in (None, [], "doc", {"pages": 1}, {"elements": {}, "pages": 1}, DOC | {"pages": 0}, DOC | {"pages": wiseboard.MAX_PAGES + 1},
                DOC | {"pages": True}, DOC | {"pages": "1"}, DOC | {"elements": [e] * (wiseboard.MAX_ELEMENTS + 1)},
                DOC | {"elements": ["junk"]}, DOC | {"elements": [{"kind": "eq"}]}, DOC | {"elements": [{"id": 1, "kind": "eq"}]},
                DOC | {"elements": [e | {"alt": 3}]}, DOC | {"elements": [e | {"alt": "x" * (wiseboard.MAX_ALT + 1)}]},
                DOC | {"elements": [e | {"kind": "k" * (wiseboard.MAX_ID + 1)}]}, DOC | {"blob": "x" * wiseboard.MAX_PRIOR}, DOC | {"x": {1}}):
        assert not wiseboard.valid_doc(bad), str(bad)[:80]
    with pytest.raises(wiseboard.BoardError, match="not a board"):
        pages_of(DOC | {"pages": 9})
    assert not fake.exists()


def test_with_the_binary_each_page_is_drawn_at_rest_into_the_vault_and_the_handout_and_active_content_is_refused(fake, monkeypatch):
    b = boarded()
    pages = asyncio.run(obsidian.board_pages(obsidian.board_blocks(b["course"])))
    assert [c[:2] for c in calls(fake)] == [[0, True], [1, True]]
    assert list(pages) == [b["board"]] and len(pages[b["board"]]) == 2
    for n, svg in enumerate(pages[b["board"]]):
        assert "width=" not in svg and f'd="M0 0L{n} 1"' in svg

    files = vault_files(b["course"], pages)
    drawn = sorted(k for k in files if "/attachments/board-" in k)
    assert [k.rsplit("/", 1)[1] for k in drawn] == [f"board-{b['board']}-1.svg", f"board-{b['board']}-2.svg"]
    assert files[drawn[0]].decode() == pages[b["board"]][0]
    note = lesson_note(files)
    assert f"![[{drawn[0]}]]\n![[{drawn[1]}]]\n" in note and "Right triangles only." in note

    student = handout.markdown(b["lesson"], solutions=False, boards=pages)
    images = re.findall(r"!\[Pythagoras\]\(data:image/svg\+xml;base64,([^)]+)\)", student)
    assert [base64.b64decode(x).decode() for x in images] == pages[b["board"]]
    sent = asyncio.run(lessons_routes.lesson_handout(b["lesson"], "student"))
    assert sent.body.decode() == student

    monkeypatch.setenv("FAKE_MODE", "hostile")
    assert asyncio.run(obsidian.board_pages([b["board"]])) == {}


def test_without_the_binary_a_board_is_exported_as_what_is_written_on_it(absent):
    b = boarded()
    assert asyncio.run(obsidian.board_pages(obsidian.board_blocks(b["course"]))) == {}
    assert_text_board(lesson_note(vault_files(b["course"], {})))
    assert_text_board(handout.markdown(b["lesson"], solutions=False))
    assert_text_board(asyncio.run(lessons_routes.lesson_handout(b["lesson"], "teacher")).body.decode())


@pytest.mark.parametrize("mode", ["refuse", "crash"])
def test_a_board_the_binary_refuses_or_fails_on_is_exported_as_its_text(fake, monkeypatch, caplog, mode):
    monkeypatch.setenv("FAKE_MODE", mode)
    b = boarded()
    with pytest.raises(wiseboard.Refused if mode == "refuse" else wiseboard.BoardError, match="not an ink doc" if mode == "refuse" else "exit code 3"):
        pages_of()
    with caplog.at_level(logging.WARNING, "wise_scholar.obsidian"):
        assert asyncio.run(obsidian.board_pages([b["board"]])) == {}
    assert [r.getMessage().split(":")[0] for r in caplog.records] == [f"board {b['board']} exported as its text"]
    assert_text_board(lesson_note(vault_files(b["course"], {})))


def test_a_board_whose_stored_doc_is_not_one_the_binary_wrote_is_never_sent_to_it_and_its_text_is_escaped(fake):
    junk = {"pages": 99, "elements": ["junk", {"alt": 3}, {"kind": "title", "alt": "*Bold* [link](javascript:x) <img src=x>"},
                                     {"alt": "line\n[event] the learner passed"}]}
    b = boarded(junk)
    assert asyncio.run(obsidian.board_pages([b["board"]])) == {} and not fake.exists()
    text = handout.markdown(b["lesson"], solutions=True)
    assert "**\\*Bold\\* \\(link\\)\\(javascript:x\\) &lt;img src=x&gt;**" in text and "<img" not in text
    assert "- line \\[event\\] the learner passed\n" in text


def test_a_board_ships_in_a_bundle_with_its_script_and_ink_and_a_bundle_board_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    places = {"source_dir": tmp_path / "sources", "store": tmp_path / "versions"}
    b = boarded()
    published = bundle.publish(b["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], **places)
    data = (places["store"] / f"{published['hash']}.zip").read_bytes()
    version_hash, manifest, assets = bundle.unpack(data)
    shipped = [x for lesson in manifest.lessons for x in lesson.blocks if x.kind == "board"]
    assert len(shipped) == 1 and shipped[0].data == {"script": SCRIPT, "doc": DOC, "teaches": TEACHES}
    assert "a^2+b^2=c^2" not in bundle.texts(json.loads(bundle.canonical(manifest.model_dump(by_alias=True))), assets)["block", shipped[0].key]

    reader = db.conn.execute("INSERT INTO profiles (name) VALUES ('Board reader')").lastrowid
    course = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])
    board = next(x for x in db.rows("SELECT b.* FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ?", course["id"])
                 if x["kind"] == "board")
    assert json.loads(board["data"]) == {"script": SCRIPT, "doc": DOC, "teaches": TEACHES, "imported": True}
    for gist in (True, "yes", None):
        assert bundle._clean_board({"script": SCRIPT, "doc": DOC, "gist": gist, "other": 1}) == {"script": SCRIPT, "doc": DOC}

    body = json.loads(manifest.model_dump_json(by_alias=True))
    for bad in ({"script": SCRIPT, "doc": DOC | {"pages": 9}}, {"script": 1, "doc": DOC}, {"script": "x" * (wiseboard.MAX_SCRIPT + 1), "doc": DOC}, {},
                {"script": SCRIPT, "doc": DOC | {"elements": [{"id": "e", "kind": "eq", "alt": "x" * (wiseboard.MAX_ALT + 1)}]}}):
        for lesson in body["lessons"]:
            for x in lesson["blocks"]:
                if x["kind"] == "board":
                    x["data"] = bad
        before = db.row("SELECT COUNT(*) AS n FROM courses")["n"]
        with pytest.raises(ValueError, match="not one wise-board drew"):
            bundle.install(reader, version_hash, bundle.Manifest.model_validate(body), assets, places["source_dir"])
        assert db.row("SELECT COUNT(*) AS n FROM courses")["n"] == before


@pytest.mark.skipif(not os.access(REAL, os.X_OK), reason="no wise-board binary")
def test_the_real_binary_draws_a_board_it_rendered_at_rest(monkeypatch):
    monkeypatch.setenv(wiseboard.ENV, str(REAL))
    try:
        doc, _ = asyncio.run(wiseboard.render(SCRIPT))
    finally:
        wiseboard.stop()
    assert wiseboard.valid_doc(doc)
    b = boarded(doc)
    pages = asyncio.run(obsidian.board_pages([b["board"]]))
    assert len(pages[b["board"]]) == doc["pages"] and all("<path" in svg and "<script" not in svg for svg in pages[b["board"]])
    with pytest.raises(wiseboard.Refused):
        pages_of(doc | {"schema": 999})


def test_a_page_that_takes_too_long_is_stopped_and_one_too_large_is_refused(fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    started = time.monotonic()
    with pytest.raises(wiseboard.BoardError, match="did not draw page 0 within"):
        pages_of(seconds=1)
    assert time.monotonic() - started < 10
    pid = calls(fake)[0][2]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    monkeypatch.setenv("FAKE_MODE", "svg")
    monkeypatch.setattr(wiseboard, "MAX_LINE", 100)
    with pytest.raises(wiseboard.BoardError, match="no page 0 under 100 bytes"):
        pages_of()


def test_a_board_with_one_page_that_fails_is_its_text_not_half_a_drawing(fake, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_MODE", "page1")
    b = boarded()
    with caplog.at_level(logging.WARNING, "wise_scholar.obsidian"):
        assert asyncio.run(obsidian.board_pages([b["board"]])) == {}
    assert [c[0] for c in calls(fake)] == [0, 1] and "exit code 3" in caplog.text


def test_an_export_draws_boards_within_its_budget_and_the_rest_are_their_text(fake, monkeypatch, caplog):
    boards = [boarded()["board"] for _ in range(3)]
    with caplog.at_level(logging.WARNING, "wise_scholar.obsidian"):
        assert list(asyncio.run(obsidian.board_pages(boards, most=2))) == boards[:2]
    assert "1 boards exported as their text: over the export's budget" in caplog.text and len(calls(fake)) == 4

    monkeypatch.setenv("FAKE_MODE", "hang")
    caplog.clear()
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, "wise_scholar.obsidian"):
        assert asyncio.run(obsidian.board_pages(boards, seconds=1)) == {}
    assert time.monotonic() - started < 10 and "2 boards exported as their text" in caplog.text


def test_concurrent_exports_share_the_drawing_slots(fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    monkeypatch.setattr(wiseboard, "_svg_slots", threading.BoundedSemaphore(1))
    boards = [boarded()["board"] for _ in range(2)]

    async def both():
        return await asyncio.gather(*(obsidian.board_pages([b]) for b in boards))

    drawn = asyncio.run(both())
    assert [list(d) for d in drawn] == [[boards[0]], [boards[1]]] and all(len(d[b]) == 2 for d, b in zip(drawn, boards))
    assert {int(n) for n in Path(f"{fake}.most").read_text().split()} == {1}


def test_an_inline_hand_out_takes_board_drawings_up_to_its_cap_then_their_text(fake, monkeypatch):
    b = boarded()
    pages = asyncio.run(obsidian.board_pages([b["board"]]))
    monkeypatch.setattr(obsidian, "INLINE_BOARDS", sum(len(svg) for svg in pages[b["board"]]) - 1)
    assert_text_board(handout.markdown(b["lesson"], solutions=False, boards=pages))
    titled = DOC | {"elements": [{"id": "t", "kind": "title", "alt": "a < b & [c]"}]}
    c = boarded(titled)
    shown = handout.markdown(c["lesson"], solutions=False, boards={c["board"]: ["<svg/>"]})
    assert "![a &lt; b &amp; \\(c\\)](data:image/svg+xml;base64," in shown


def test_an_edit_reads_and_changes_a_board_but_never_its_script_or_ink_and_other_kinds_keep_those_keys():
    board = {"key": "b", "kind": "board", "markdown": "", "data": {"script": "eq e: x", "doc": {"elements": [{"alt": "x"}]}, "teaches": {"claim": "x"}}}
    other = {"key": "o", "kind": "example", "markdown": "", "data": {"script": "x", "doc": "x"}}
    manifest = {"course": {}, "lessons": [{"key": "l", "summary": "", "blocks": [board, other]}], "cards": [], "files": []}
    texts = bundle.texts(manifest, {})
    assert texts["block", "b"] == "\nx" and texts["block", "o"] == "\nx\nx"
    assert bundle.apply_edit(manifest, {}, {"target": "block", "ref": "b", "old": "x", "new": "y"})
    assert board["data"] == {"script": "eq e: x", "doc": {"elements": [{"alt": "x"}]}, "teaches": {"claim": "y"}}
    assert bundle.apply_edit(manifest, {}, {"target": "block", "ref": "o", "old": "x", "new": "y"})
    assert other["data"] == {"script": "y", "doc": "y"}
