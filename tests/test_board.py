import asyncio
import os
import tempfile
from uuid import uuid4

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import board, db, figcheck, figures  # noqa: E402
from wise_scholar.tools import visuals as visual_tools  # noqa: E402

TEACHES = figures.Teaches(claim="Seasons come from the tilt.", notice="Which hemisphere leans to the Sun.")
SVG = (
    '<svg viewBox="0 0 300 150"><g data-part="sun"><circle cx="40" cy="75" r="20"/></g>'
    '<g data-part="orbit"><ellipse cx="170" cy="75" rx="110" ry="40" fill="none"/>'
    '<g data-part="earth"><circle cx="280" cy="75" r="8"/><g data-part="axis"><line x1="276" y1="62" x2="284" y2="88"/></g></g></g>'
    '<g data-part="guess"><text x="120" y="20" font-size="14">Closer is warmer?</text></g></svg>'
)


def step(say: str, draw: list[str] = (), erase: list[str] = ()) -> board.BoardStep:
    return board.BoardStep(say=say, draw=list(draw), erase=list(erase))


def figure_lesson(monkeypatch, svg: str = SVG) -> tuple[int, int]:
    monkeypatch.setattr(figcheck, "available", lambda: False)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Boarder {uuid4()}",)).lastrowid
    course = db.create_course("Seasons", who)["id"]
    lesson = db.create_lesson(course, "Tilt", "lesson", None)
    assert asyncio.run(visual_tools.add_figure(lesson, svg, "The tilt", "Earth on its orbit", TEACHES)).startswith("shown as figure")
    return lesson, db.blocks(lesson)[-1]["id"]


def test_steps_draw_each_part_once_inside_what_is_already_on_the_board():
    def error(*steps: board.BoardStep, earlier: list[dict] = ()) -> str | None:
        return board.steps_error(figures.clean(SVG), list(steps), earlier)

    assert error(step("A guess.", ["guess"]), step("The orbit.", ["orbit"], ["guess"])) is None
    assert error(step("The orbit and the Earth on it.", ["orbit", "earth"]), step("Its tilted axis.", ["axis"])) is None
    assert error(step("Earth.", ["earth"]), step("Orbit.", ["orbit"])) == (
        "step 1 draws earth inside orbit, which is not on the board then; draw orbit first or move earth out of it"
    )
    assert error(step("Moon.", ["moon"])) == "no part moon in the figure; its parts are axis, earth, guess, orbit, sun"
    assert error(step("Sun.", ["sun"]), step("Sun again.", ["sun"])) == "a part is drawn once: sun is drawn in more than one step"
    assert error(step("Wipe.", erase=["guess"]), step("Wipe again.", erase=["guess"])) == "step 2 erases guess, which is not on the board then"
    assert error(step(" ", ["sun"])) == "every step says what it draws, in one sentence"
    assert error(step("Look.")) == "every step draws or erases a part; say about a part already there in the step that draws it"
    assert error(step("Sun.", ["sun"]), earlier=[{"say": "s", "draw": ["sun"], "erase": []}]) == "a part is drawn once: sun is drawn in more than one step"
    assert board.steps_error(figures.clean('<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'), [step("x", ["a"])]).startswith("the figure has no parts")


def test_a_figure_is_narrated_after_the_opening_and_redrawing_drops_the_board(monkeypatch):
    lesson, figure = figure_lesson(monkeypatch)
    steps = [step("First a common guess.", ["guess"]), step("The Sun and the orbit.", ["sun", "orbit"], ["guess"])]
    assert asyncio.run(visual_tools.narrate_figure(lesson, figure, steps)) == f"figure {figure} plays as a board in 2 steps"
    assert db.block(figure)["data"]["board"] == {"steps": [
        {"say": "First a common guess.", "draw": ["guess"], "erase": []},
        {"say": "The Sun and the orbit.", "draw": ["sun", "orbit"], "erase": ["guess"]},
    ]}
    assert asyncio.run(visual_tools.narrate_figure(lesson, figure, steps[:1])) == "error: a board has 2 to 8 steps"
    assert asyncio.run(visual_tools.narrate_figure(lesson, 10**9, steps)) == "error: no figure with id 1000000000 in this lesson"
    assert asyncio.run(visual_tools.replace_figure(lesson, figure, SVG, "Again", "Earth on its orbit")) == f"figure {figure} redrawn"
    assert "board" not in db.block(figure)["data"]
    assert db.block(figure)["data"]["previous"]["board"]["steps"][0]["draw"] == ["guess"]


def test_a_board_waits_for_the_opening_attempt(monkeypatch):
    from wise_scholar import tutor

    lesson, figure = figure_lesson(monkeypatch)
    monkeypatch.setattr(tutor, "_needs_opening", lambda lesson: True)
    reply = asyncio.run(visual_tools.narrate_figure(lesson, figure, [step("Sun.", ["sun"]), step("Orbit.", ["orbit"])]))
    assert reply.startswith("refused: the lesson has no attempted opening yet")

