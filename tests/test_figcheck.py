import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figcheck, figures, tutor  # noqa: E402


def check(svg: str, **k) -> list[str]:
    return asyncio.run(figcheck.problems([figures.clean(svg)], **k))


def can_look() -> bool:
    """Without a browser the checker finds nothing, not even an empty drawing."""
    return figcheck.available() and check('<svg viewBox="0 0 1 1"/>') != []


looks = pytest.mark.skipif(not can_look(), reason="no Playwright or no browser here")


@looks
def test_a_figure_a_reader_trips_over_is_described():
    assert check('<svg viewBox="0 0 300 150"><rect width="100" height="80"/><text x="20" y="120" font-size="14">Left</text><text x="200" y="120" font-size="14">Right</text></svg>') == []
    assert check('<svg viewBox="0 0 300 150"><g/></svg>') == ["nothing is drawn: every shape is empty or outside the viewBox"]
    found = check(
        '<svg viewBox="0 0 300 150"><rect width="100" height="80"/><text x="250" y="120" font-size="14">Far too long a label</text>'
        '<text x="20" y="60" font-size="14">Ventricle</text><text x="25" y="62" font-size="14">Atrium</text><text x="20" y="140" font-size="3">tiny</text></svg>'
    )
    assert found == [
        'the label "Far too long a label" runs past the edge of the viewBox',
        'the label "tiny" is 6.0 px tall at 600 px wide; make it at least 9 px',
        'the labels "Ventricle" and "Atrium" overlap',
    ]
    assert not any("tiny" in f for f in check('<svg viewBox="0 0 300 150"><rect width="1" height="1"/><text x="20" y="140" font-size="3">tiny</text></svg>', small_text=False))


@looks
def test_the_tool_refuses_a_figure_with_overlapping_labels_and_shows_nothing():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Checker')").lastrowid
    course = db.create_course("Hearts", who)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    try:
        lesson = db.create_lesson(course, "Chambers", "lesson", None)
        svg = '<svg viewBox="0 0 300 150"><rect width="100" height="80"/><text x="20" y="60" font-size="14">Ventricle</text><text x="25" y="62" font-size="14">Atrium</text></svg>'
        reply = asyncio.run(tutor.add_figure(lesson, svg, "c", "a", figures.Teaches(claim="c", notice="n")))
        assert reply == 'error: the figure was not shown; fix these and draw it again: the labels "Ventricle" and "Atrium" overlap'
        assert db.blocks(lesson) == []
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))
