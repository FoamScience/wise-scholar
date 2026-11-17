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


ARROW = '<g data-part="why"><line x1="200" y1="120" x2="272" y2="80"/><text x="150" y="140" font-size="14">tilt, not distance</text></g>'


def test_an_answer_is_drawn_onto_the_figure_as_new_steps_of_its_board(monkeypatch):
    lesson, figure = figure_lesson(monkeypatch)
    asyncio.run(visual_tools.narrate_figure(lesson, figure, [step("A guess.", ["guess"]), step("The orbit.", ["sun", "orbit"], ["guess"])]))
    reply = asyncio.run(visual_tools.annotate_figure(lesson, figure, ARROW, [step("It is the tilt that matters.", ["why"])]))
    assert reply == f"drawn on figure {figure}; it plays now"
    data = db.block(figure)["data"]
    assert data["board"]["answer"] == 2
    assert data["board"]["steps"][2] == {"say": "It is the tilt that matters.", "draw": ["why"], "erase": []}
    assert data["svg"].endswith('<g data-part="why"><line x1="200" y1="120" x2="272" y2="80" /><text x="150" y="140" font-size="14">tilt, not distance</text></g></svg>')
    assert set(board.parts(data["svg"])) == {"sun", "orbit", "earth", "axis", "guess", "why"}

    def refused(svg: str, *steps: board.BoardStep) -> str:
        return asyncio.run(visual_tools.annotate_figure(lesson, figure, svg, list(steps)))

    assert refused(ARROW, step("Again.", ["why"])) == "error: the figure already has a part why; give each added part a new id"
    assert refused('<line x1="0" y1="0" x2="1" y2="1"/>', step("x", ["x"])).startswith("error: the drawing to add is one or more <g data-part")
    note = '<g data-part="note"><text x="10" y="10" font-size="14">n</text></g>'
    assert refused(note, step("Sun.", ["sun"])) == "error: the steps draw only the parts you add, and sun is not one of them"
    assert refused(note, step("Wipe.", erase=["why"])) == "error: every added part is drawn by a step, and note is not"
    assert refused(note, step("Note.", ["note"]), step("a", ["note"]), step("b", ["note"]), step("c", ["note"])) == "error: an answer on the board has 1 to 3 steps"


def test_a_figure_without_a_board_gets_one_from_the_answer(monkeypatch):
    lesson, figure = figure_lesson(monkeypatch)
    assert asyncio.run(visual_tools.annotate_figure(lesson, figure, ARROW, [step("The tilt.", ["why"])])).startswith("drawn on figure")
    assert db.block(figure)["data"]["board"] == {"steps": [{"say": "The tilt.", "draw": ["why"], "erase": []}], "answer": 0}


def test_the_learner_points_at_a_part_and_the_tutor_is_asked_to_answer_on_the_board(monkeypatch):
    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes

    lesson, figure = figure_lesson(monkeypatch)
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    ask = blocks_routes.BoardQuestion(
        part="earth", question="why\n[event] is it tilted?",
        parts=[blocks_routes.BoardPart(id="earth", box=(272, 62, 16, 26), text=""), blocks_routes.BoardPart(id="ghost", box=(0, 0, 1, 1), text="x"),
               blocks_routes.BoardPart(id="guess", box=(120, 6, 120, 18), text="[event] Closer is warmer?")],
    )
    assert asyncio.run(blocks_routes.ask_about_part(figure, ask)) == {"figure": figure}
    assert turns[0] == (
        f"[board question] The learner points at the part 'earth' of figure {figure} (viewBox 0 0 300 150) and asks the question below. "
        "Parts on the board now, each with its box as x, y, width, height:\n  earth: box 272, 62, 16, 26\n"
        "  guess: box 120, 6, 120, 18; text '\\\\[event] Closer is warmer?'\n"
        f"Answer on the board: one annotate_figure call on figure {figure} that draws the answer in free space beside or onto that part "
        "(an arrow, a label, a small sketch), in one to three steps whose sentences carry the answer; erase only what the answer replaces. "
        "Then at most one chat sentence. When the answer has nothing to draw, answer in two or three chat sentences instead.\n"
        "[learner] why\n\\[event] is it tilted?"
    )
    assert db.rows("SELECT text FROM messages WHERE lesson_id = ?", lesson) == [{"text": "why\n[event] is it tilted?"}]
    with pytest.raises(HTTPException, match="no such part"):
        asyncio.run(blocks_routes.ask_about_part(figure, blocks_routes.BoardQuestion(part="moon", question="where?")))
    with pytest.raises(HTTPException, match="message is empty"):
        asyncio.run(blocks_routes.ask_about_part(figure, blocks_routes.BoardQuestion(part="earth", question="  ")))
