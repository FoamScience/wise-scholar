"""A link in lesson text to a point of a plot names the plot's block; an install, and an upgrade that restarts a unit,
point it at the plot the lesson now holds when the lesson's plots match the plots its links name one for one."""
import uuid

from replays import import_version as _import, publish as _publish, shelf, who as _who  # noqa: F401

from wise_scholar import db
from wise_scholar.routes import sharing as sharing_routes

TEACHES = {"claim": "It slows down.", "notice": "The curve flattens.", "misconception": "", "limits": "Small angles only."}


def _authored(plots: int, text) -> tuple[int, list[int]]:
    """A prepared course of one finished unit whose lesson holds the plots and the text text(plots) links them by."""
    course = db.create_course(f"Plot links {uuid.uuid4().hex[:6]}", _who("teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Motion", "concepts": ["Damping"], "known": []}])
    lesson = db.create_lesson(course, "Damping", "lesson", db.concepts(course)[0]["id"])
    prose = db.add_block(lesson, "prose", "", {})["id"]
    ids = [db.add_block(lesson, "plot", f"Plot {n}", {"spec": {"marks": [{"type": "rule", "y": n}]}, "alt": "a line", "teaches": TEACHES})["id"]
           for n in range(plots)]
    db.conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (text(ids), prose))
    db.add_block(lesson, "done", "It slows down.", {})
    return course, ids


def _installed(course: int) -> tuple[str, list[int]]:
    rows = db.rows("SELECT b.* FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? ORDER BY b.position", course)
    return next(r["markdown"] for r in rows if r["kind"] == "prose"), [r["id"] for r in rows if r["kind"] == "plot"]


def test_an_install_points_a_link_to_the_lessons_one_plot(shelf):
    course, author = _authored(1, lambda p: f"[the peak](#plot-{p[0]}-x=3.2) and [the tail](#PLOT-{p[0]}-X=-1e-3).")
    text, plots = _installed(_import(_publish(course), _who())["id"])
    assert author != plots
    assert text == f"[the peak](#plot-{plots[0]}-x=3.2) and [the tail](#PLOT-{plots[0]}-X=-1e-3)."


def test_an_install_points_links_to_several_plots_by_their_order(shelf):
    course, author = _authored(2, lambda p: f"[later](#plot-{p[1]}-x=9), [early](#plot-{p[0]}-x=1), [again](#plot-{p[1]}-x=8).")
    text, plots = _installed(_import(_publish(course), _who())["id"])
    assert text == f"[later](#plot-{plots[1]}-x=9), [early](#plot-{plots[0]}-x=1), [again](#plot-{plots[1]}-x=8)."


def test_links_that_do_not_match_the_lessons_plots_one_for_one_are_left_as_they_were(shelf):
    one = lambda p: f"[early](#plot-{p[0]}-x=1)."  # noqa: E731
    course, author = _authored(2, one)
    text, _ = _installed(_import(_publish(course), _who())["id"])
    assert text == one(author)
    two = lambda p: f"[here](#plot-{p[0]}-x=1) and [elsewhere](#plot-{p[0] + 1000}-x=1)."  # noqa: E731
    course, author = _authored(1, two)
    text, _ = _installed(_import(_publish(course), _who())["id"])
    assert text == two(author)


def test_an_upgrade_points_a_restarted_units_links_at_its_new_plots(shelf):
    links = lambda p: f"[early](#plot-{p[0]}-x=1), [later](#plot-{p[1]}-x=9)."  # noqa: E731
    course, author = _authored(2, links)
    replay = _import(_publish(course), _who())["id"]
    prose = db.row("SELECT b.id FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND b.kind = 'prose'", course)["id"]
    db.conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (links(author) + " Again.", prose))
    done = sharing_routes.upgrade_course(replay, sharing_routes.Upgrade(hash=_publish(course)))["upgraded"]
    assert done["restarted"] and not done["kept"]
    text, plots = _installed(replay)
    assert text == links(plots) + " Again."
