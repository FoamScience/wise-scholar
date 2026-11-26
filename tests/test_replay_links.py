"""A link in lesson text to a part of a handwritten board names the board's block; an install, and an upgrade that
restarts a unit, point it at the board the course now holds when the part's name finds that board."""
import uuid

from replays import import_version as _import, publish as _publish, shelf, who as _who  # noqa: F401

from wise_scholar import db
from wise_scholar.routes import sharing as sharing_routes

TEACHES = {"claim": "The squares add up.", "notice": "The legs' squares.", "misconception": "", "limits": "Right triangles only."}


def _board(lesson: int, *ids: str) -> int:
    doc = {"schema": 2, "page": [1600, 1000], "pages": 1, "elements": [{"id": i, "kind": "eq", "page": 0, "alt": "x=1"} for i in ids]}
    return db.add_block(lesson, "board", "", {"script": 'board "B"\n', "doc": doc, "teaches": TEACHES})["id"]


def _authored(text) -> tuple[int, dict[str, int]]:
    """A prepared course of one finished unit whose lesson holds three boards and the text text(boards) links them by."""
    course = db.create_course(f"Links {uuid.uuid4().hex[:6]}", _who("teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Squares", "concepts": ["Pythagoras"], "known": []}])
    lesson = db.create_lesson(course, "Pythagoras", "lesson", db.concepts(course)[0]["id"])
    prose = db.add_block(lesson, "prose", "", {})["id"]
    boards = {"sum": _board(lesson, "t", "sum", "#eq1"), "proof": _board(lesson, "t", "step"), "twin": _board(lesson, "t", "step")}
    db.conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (text(boards), prose))
    db.add_block(lesson, "done", "The squares add up.", {})
    return course, boards


def _installed(course: int) -> tuple[str, dict[str, int]]:
    """The installed lesson's text and its boards, in order, named as the author's are."""
    rows = db.rows("SELECT b.* FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? ORDER BY b.position", course)
    text = next(r["markdown"] for r in rows if r["kind"] == "prose")
    boards = [r for r in rows if r["kind"] == "board"]
    return text, {"sum": boards[0]["id"], "proof": boards[1]["id"], "twin": boards[2]["id"]}


def _links(b: dict[str, int]) -> str:
    return (f"[the sum](#board-{b['sum']}-sum) and [its square](#board-{b['sum']}-sum.sq), "
            f"[the first equation](#board-{b['sum']}-%23eq1), [the title](#board-{b['sum']}-t), "
            f"[a step](#board-{b['proof']}-step), [the leg](#part-leg).")


def test_an_install_points_a_link_to_a_named_part_at_the_installed_board(shelf):
    course, author = _authored(_links)
    replay = _import(_publish(course), _who())["id"]
    text, b = _installed(replay)
    assert author["sum"] != b["sum"]
    assert f"(#board-{b['sum']}-sum)" in text and f"(#board-{b['sum']}-sum.sq)" in text
    assert f"(#board-{b['sum']}-t)" in text  # the title is in every board, but the link's other parts pick this one
    assert f"(#board-{author['sum']}-%23eq1)" in text  # an unnamed part may be another part of the board that shipped
    assert f"(#board-{author['proof']}-step)" in text  # two boards have a part named step
    assert "(#part-leg)" in text


def test_a_link_whose_part_no_installed_board_has_is_left_as_it_was(shelf):
    course, author = _authored(lambda b: f"[the answer](#board-{b['sum']}-answer) and [the title](#board-{b['sum']}-t).")
    replay = _import(_publish(course), _who())["id"]
    text, _ = _installed(replay)
    assert text == f"[the answer](#board-{author['sum']}-answer) and [the title](#board-{author['sum']}-t)."


def test_an_upgrade_points_a_restarted_units_links_at_its_new_boards(shelf):
    course, author = _authored(_links)
    replay = _import(_publish(course), _who())["id"]
    prose = db.row("SELECT b.id FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND b.kind = 'prose'", course)["id"]
    db.conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (_links(author) + " Again.", prose))
    done = sharing_routes.upgrade_course(replay, sharing_routes.Upgrade(hash=_publish(course)))["upgraded"]
    assert done["restarted"] and not done["kept"]
    text, b = _installed(replay)
    assert author["sum"] != b["sum"] and text.endswith(" Again.")
    assert f"(#board-{b['sum']}-sum)" in text and f"(#board-{author['sum']}-%23eq1)" in text
