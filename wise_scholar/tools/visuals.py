import asyncio
from contextlib import suppress

from .. import art, board, db, diagrams, figcheck, figures, plots, widgets, wiseboard
from ..tutor import _show, calling_turn, mcp, pretest_blocker


def figure_blocker(lesson: dict, setup: bool) -> str | None:
    """Before the opening's attempt, the one figure that sets up its card is the only figure the lesson may show."""
    problem = pretest_blocker(lesson)
    if not problem or not setup:
        return problem
    if any(block["kind"] in ("figure", "plot") for block in db.blocks(lesson["id"])):
        return "an opening has one setup figure, and this lesson has it. Pose the card and end the turn"
    return None


@mcp.tool()
async def add_figure(lesson_id: int, svg: str, caption: str, alt: str, teaches: figures.Teaches, setup: bool = False) -> str:
    """Show a figure you draw yourself as SVG: a schematic, a labelled structure, an apparatus sketch, a force
    diagram, a small infographic.

    teaches: what the figure is for, decided before drawing it. claim: the sentence of the lesson it makes
    visible. notice: what the learner should see in it that shows the claim (a cause and its effect, a part and
    where it sits). misconception: the wrong belief it shows failing, when there is one. limits: where the
    drawing stops matching the real thing (scale, left-out parts, an idealised model); the learner sees it under
    the caption. A figure with no claim to make visible is not drawn.

    svg: a complete <svg> with a viewBox (no wider than 3:2), transparent background, shapes and paths, labels
    as <text> elements readable at 600 px wide. Fills and strokes from the palette only: teal #0b5f5a, teal tint
    #e1f0ee, amber #6b3a00, amber tint #fbebd3, line #8794a1; text and outlines in currentColor so both themes
    read it. No script, style element, image, foreignObject or external links; they are stripped or refused.
    caption: one sentence under the figure. alt: what the figure shows, for a reader who cannot see it.
    setup: this figure shows the situation of the opening card you pose next, with what the card asks left out;
    only then, and only once, may a figure come before the learner's first attempt. claim says what the situation is.
    Before showing it the server lays it out 600 px wide and refuses it, saying why, when nothing is drawn, a label
    runs past the viewBox, two labels overlap, or a label is under 9 px tall.
    Wrap each part the lesson text talks about in `<g data-part="id">` (a short lowercase id); the text names it as
    `[left ventricle](#part-id)`, and pointing at the term or the part lights up both while the other parts dim.

    Icons from an installed art pack (see the [tools] line) go in as `<use href="art:ID" x="" y="" width="" height=""/>`
    with an ID from find_art, sized by its ratio; the server inlines the drawing and credits its author under the
    caption. Place them, then add your own labels, arrows and callouts around them.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if problem := figure_blocker(lesson, setup):
        return f"refused: {problem}"
    try:
        data = _figure_data(svg, alt) | {"teaches": figures.teaching(teaches)}
    except ValueError as e:
        return f"error: {e}"
    if found := await figcheck.problems([data["svg"]]):
        return f"error: {figcheck.report(found)}"
    block = db.add_block(lesson_id, "figure", caption, {"svg": "", "alt": data["alt"]})
    block = db.set_block_data(block["id"], {**data, "svg": figures.prefix_ids(data["svg"], f"f{block['id']}-")})
    _show(lesson, block)
    return f"shown as figure {block['id']}"


@mcp.tool()
async def replace_figure(lesson_id: int, block_id: int, svg: str, caption: str, alt: str, teaches: figures.Teaches | None = None) -> str:
    """Draw an existing figure of this lesson again in its place: same block, same position in the lesson. Same
    rules as add_figure; without teaches the figure keeps what it was for. Use it when asked to redraw figures, or
    when a figure of yours turned out wrong."""
    block = db.block(block_id)
    if not block or block["kind"] != "figure" or block["lesson_id"] != lesson_id:
        return f"error: no figure with id {block_id} in this lesson"
    try:
        data = _figure_data(svg, alt) | _kept_teaches(block, teaches)
    except ValueError as e:
        return f"error: {e}"
    if found := await figcheck.problems([data["svg"]]):
        return f"error: {figcheck.report(found)}"
    # The drawing being replaced is kept, so the learner can go back to it.
    previous = {k: v for k, v in block["data"].items() if k not in ("previous", "restored")} | {"caption": block["markdown"]}
    block = db.set_block(block_id, caption, {**data, "svg": figures.prefix_ids(data["svg"], f"f{block_id}-"), "previous": previous})
    _show(db.lesson(block["lesson_id"]), block, "block.updated")
    return f"figure {block_id} redrawn"


@mcp.tool()
async def narrate_figure(lesson_id: int, block_id: int, steps: list[board.BoardStep]) -> str:
    """Play a figure of this lesson as a whiteboard: the learner presses play and watches it drawn stroke by stroke,
    one step at a time, each step's sentence shown under it. For an idea built up in order: a derivation, a
    mechanism, a proof, a cause and the chain of its effects, a structure assembled part by part.

    steps: 2 to 8, in the order you would draw them at a board. say: the one sentence shown while the step draws,
    about what it draws. draw: the `data-part` ids the step draws; each part is drawn once. erase: parts on the board
    the step wipes (a first guess, a scaffold no longer needed). Parts no step draws stand from the start, so the
    frame (axes, an outline) needs no step. A part inside another part is drawn with it or after it. A figure
    without parts is drawn again with replace_figure first."""
    block = db.block(block_id)
    if not block or block["kind"] != "figure" or block["lesson_id"] != lesson_id:
        return f"error: no figure with id {block_id} in this lesson"
    if problem := pretest_blocker(db.lesson(lesson_id)):
        return f"refused: {problem}"
    if block["data"].get("frames"):
        return "error: this figure is an animation that plays its own stages; narrate a still figure"
    if not board.MIN_STEPS <= len(steps) <= board.MAX_STEPS:
        return f"error: a board has {board.MIN_STEPS} to {board.MAX_STEPS} steps"
    if problem := board.steps_error(block["data"]["svg"], steps):
        return f"error: {problem}"
    told = [_step(s) for s in steps]
    kept = board.unanswered(block["data"])
    data = block["data"] | {"board": {"steps": told}} | ({"unanswered": board.narrated(kept, told)} if kept else {})
    block = db.set_block_data(block_id, data)
    _show(db.lesson(lesson_id), block, "block.updated")
    return f"figure {block_id} plays as a board in {len(steps)} steps"


@mcp.tool()
async def annotate_figure(lesson_id: int, block_id: int, svg: str, steps: list[board.BoardStep]) -> str:
    """Answer the learner's question about a figure by drawing on it, as at a whiteboard: the new parts are added on
    top and play right away as further steps of its board, each step's sentence shown while it draws.

    svg: the drawing to add, as one or more `<g data-part="id">` groups with new ids, in the figure's own viewBox
    coordinates (the question gives the boxes of the parts on it): an arrow, a label, a small sketch, a mark on the
    part asked about. Put labels in free space and point with arrows; a new label that sits on what is already drawn
    is refused. Same palette and rules as add_figure. steps: 1 to 3, each with the sentence shown while it draws; they
    draw every added part, and may erase parts the answer replaces."""
    block = db.block(block_id)
    if refusal := _annotate_refusal(lesson_id, block_id, block, steps):
        return refusal
    earlier = block["data"].get("board", {}).get("steps", [])
    error, drawing, credits = await _drawn_on(block, svg, steps, earlier)
    if error:
        return error
    data = block["data"] | {
        "svg": drawing,
        "credits": [*block["data"].get("credits", []), *(c for c in credits if c not in block["data"].get("credits", []))],
        "board": {"steps": [*earlier, *(_step(s) for s in steps)], "answer": len(earlier)},
        "unanswered": board.unanswered(block["data"]) or {k: block["data"][k] for k in board.FIGURE if k in block["data"]},
    }
    block = db.set_block_data(block_id, data)
    _show(db.lesson(lesson_id), block, "block.updated")
    return f"drawn on figure {block_id}; it plays now"


def _annotate_refusal(lesson_id: int, block_id: int, block: dict | None, steps: list[board.BoardStep]) -> str | None:
    if not block or block["kind"] != "figure" or block["lesson_id"] != lesson_id:
        return f"error: no figure with id {block_id} in this lesson"
    if problem := pretest_blocker(db.lesson(lesson_id)):
        return f"refused: {problem}"
    if block["data"].get("frames"):
        return "error: this figure is an animation; answer in chat"
    if not 1 <= len(steps) <= board.MAX_ADDED:
        return f"error: an answer on the board has 1 to {board.MAX_ADDED} steps"
    return None


async def _drawn_on(block: dict, svg: str, steps: list[board.BoardStep], earlier: list) -> tuple[str | None, str, list]:
    """The figure with the added parts merged in and its credits, or the error that refuses the answer."""
    try:
        drawing, added, credits = board.merge(block["data"]["svg"], svg, f"f{block['id']}-a{len(earlier)}-")
    except ValueError as e:
        return f"error: {e}", "", []
    if strays := sorted({p for s in steps for p in s.draw} - set(added)):
        return f"error: the steps draw only the parts you add, and {', '.join(strays)} is not one of them", "", []
    if undrawn := [p for p in added if not any(p in s.draw for s in steps)]:
        return f"error: every added part is drawn by a step, and {', '.join(undrawn)} is not", "", []
    if problem := board.steps_error(drawing, steps, earlier):
        return f"error: {problem}", "", []
    before = await figcheck.problems([block["data"]["svg"]])
    if found := [p for p in await figcheck.problems([drawing], fresh=added) if p not in before]:
        return f"error: {figcheck.report(found)}", "", []
    return None, drawing, credits


def _step(step: board.BoardStep) -> dict:
    return {"say": step.say.strip(), "draw": step.draw, "erase": step.erase}


def _figure_data(svg: str, alt: str, limit: int = figures.MAX_CHARS) -> dict:
    if not alt.strip():
        raise ValueError("alt text is required")
    drawing, credits = art.inline(figures.clean(svg, limit=limit))
    return {"svg": drawing, "alt": alt.strip(), "credits": credits}


def _kept_teaches(block: dict, teaches: figures.Teaches | None) -> dict:
    """The teaching spec of a redrawn figure: the one given, else the one it had."""
    if teaches is not None:
        return {"teaches": figures.teaching(teaches)}
    return {"teaches": block["data"]["teaches"]} if "teaches" in block["data"] else {}


# A layout holds a core for up to a minute; two at a time, the rest wait.
_layouts = asyncio.Semaphore(2)


@mcp.tool()
async def add_diagram(lesson_id: int, domain: str, substance: str, caption: str, alt: str, teaches: figures.Teaches, setup: bool = False) -> str:
    """Show a diagram the server lays out from what you state, in a domain listed on the [tools] line (read
    diagram_help first). substance: a Penrose Substance program for that domain: declare the objects, state the
    predicates, give labels with `Label x "text"`. The layout follows the domain's rules; an error names the rule
    that cannot be met, then state fewer or smaller things. caption, alt, teaches and setup as for add_figure."""
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if problem := figure_blocker(lesson, setup):
        return f"refused: {problem}"
    if not alt.strip():
        return "error: alt text is required"
    try:
        async with _layouts:
            svg = await asyncio.to_thread(diagrams.render, domain.strip(), substance)
        data = _figure_data(svg, alt) | {"diagram": {"domain": domain.strip(), "substance": substance}, "teaches": figures.teaching(teaches)}
    except ValueError as e:
        return f"error: {e}"
    block = db.add_block(lesson_id, "figure", caption, {"svg": "", "alt": data["alt"]})
    block = db.set_block_data(block["id"], {**data, "svg": figures.prefix_ids(data["svg"], f"f{block['id']}-")})
    _show(lesson, block)
    return f"shown as figure {block['id']}"


@mcp.tool()
async def add_animation(lesson_id: int, domain: str, stages: list[str], caption: str, alt: str, teaches: figures.Teaches) -> str:
    """Show a phenomenon unfolding: 2 to 6 stages, each a Substance program of the same domain with the same
    objects (same names) and what changes between stages changed (a cell's type, a predicate, a label). The server
    lays the stages out one after the other and plays them as one animation; the book and the hand-outs show the
    stages side by side. caption, alt and teaches as for add_figure; alt tells the whole sequence, notice what
    changes from stage to stage."""
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if problem := pretest_blocker(lesson):
        return f"refused: {problem}"
    if not alt.strip():
        return "error: alt text is required"
    try:
        async with _layouts:
            svg, frames = await asyncio.to_thread(diagrams.animate, domain.strip(), stages)
        data = _figure_data(svg, alt, limit=figures.MAX_CHARS * len(stages)) | {
            "diagram": {"domain": domain.strip(), "stages": stages},
            "frames": [figures.clean(f) for f in frames],
            "teaches": figures.teaching(teaches),
        }
    except ValueError as e:
        return f"error: {e}"
    block = db.add_block(lesson_id, "figure", caption, {"svg": "", "alt": data["alt"]})
    block = db.set_block_data(block["id"], _prefixed(block["id"], data))
    _show(lesson, block)
    return f"shown as figure {block['id']}, animated over {len(frames)} stages"


def _prefixed(block_id: int, data: dict) -> dict:
    """The data with the ids inside its drawings made unique to the block, so figures on one page stay apart."""
    prefix = f"f{block_id}-"
    frames = {"frames": [figures.prefix_ids(f, f"{prefix}{n}-") for n, f in enumerate(data["frames"])]} if "frames" in data else {}
    return {**data, "svg": figures.prefix_ids(data["svg"], prefix), **frames}


NO_BOARDS = "error: this server has no wise-board, so there are no handwritten boards; draw a figure and narrate_figure it"
# A gist turn writes one board for its finished lesson, kept to one page.
GIST_SCRIPT = 4 * 1024


@mcp.tool()
async def board_help(topic: str = "") -> str:
    """The board script language, to read before add_board: the whole reference, or one section of it (script,
    elements, placement, beats, annotations, math, options, limits, errors)."""
    if not wiseboard.available():
        return NO_BOARDS
    try:
        return await wiseboard.help_text(topic.strip())
    except wiseboard.BoardError as e:
        return f"error: {e}"


@mcp.tool()
async def add_board(lesson_id: int, script: str, teaches: figures.Teaches) -> str:
    """Show a handwritten whiteboard: math and short text written in marker, beat by beat, each beat's sentence shown
    while it draws, as at a lecture board. For a derivation, a proof, a worked calculation, a chain of equations, the
    gist of a lesson. Read board_help first. script: a board script as board_help describes; no coordinates or
    colours. A refused script comes back with the engine's errors, line by line; fix those lines and call again.
    The lesson text links a part of the board as `[the sum](#board-<block>-<id>)` or `#board-<block>-<id>.<mark>`.
    teaches as for add_figure. A board explains, so it never comes before the opening's attempt."""
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if problem := pretest_blocker(lesson):
        return f"refused: {problem}"
    if not wiseboard.available():
        return NO_BOARDS
    gist = turn if (turn := calling_turn()) and turn["kind"] == "gist" else None
    if gist and gist.get("board"):
        return f"refused: the gist board is written as board {gist['board']}; end the turn"
    if gist and len(script.encode()) > GIST_SCRIPT:
        return f"error: a gist board's script stays under {GIST_SCRIPT} bytes; keep to the few claims that carry the lesson"
    try:
        spec = figures.teaching(teaches)
        doc, notes = await wiseboard.render(script)
    except (ValueError, wiseboard.BoardError) as e:
        return f"error: {e}"
    block = db.add_block(lesson_id, "board", "", {"script": script, "doc": doc, "teaches": spec} | ({"gist": True} if gist else {}))
    if gist:
        gist["board"] = block["id"]
    _show(lesson, block)
    return f"shown as board {block['id']}" + _board_notes(notes)


@mcp.tool()
async def extend_board(block_id: int, script: str) -> str:
    """Write more on an earlier board: new beats after its last one, drawn in its free space, with everything on it
    left where it is. To continue a derivation, or to answer a question about a part of the board on the board.
    script: only the new beats, starting with a `>` line, no `board` line; it may circle, box, point at, erase and
    wipe what is on the board by its ids. Errors come back as for add_board."""
    block = db.block(block_id)
    if not block or block["kind"] != "board":
        return f"error: no board with id {block_id}"
    if problem := pretest_blocker(db.lesson(block["lesson_id"])):
        return f"refused: {problem}"
    if not wiseboard.available():
        return NO_BOARDS
    before = block["data"]["script"]
    grown = _grown(before, script)
    if len(grown.encode()) > wiseboard.MAX_SCRIPT:
        return f"error: board {block_id} would have a script over {wiseboard.MAX_SCRIPT} bytes; start a new board with add_board"
    turn, kept = calling_turn(), block["data"].get("unanswered")
    try:
        doc, notes = await wiseboard.render(script, prior=block["data"]["doc"])
        if turn and turn.get("asked") == block_id:
            kept = kept or {"script": before, "doc": block["data"]["doc"]}
        elif kept:
            # Beats that name a part of an answer are refused there, and what is kept stays as it was.
            with suppress(wiseboard.Refused):
                kept = {"script": _grown(kept["script"], script), "doc": (await wiseboard.render(script, prior=kept["doc"]))[0]}
    except wiseboard.BoardError as e:
        return f"error: {e}"
    # Another extend may have landed while this one was drawn; this one was drawn on what the board was before it.
    block = db.block(block_id)
    if not block or block["data"].get("script") != before:
        return f"error: board {block_id} grew while this was drawn; extend it again from what it shows now"
    block = db.set_block_data(block_id, block["data"] | {"script": grown, "doc": doc} | ({"unanswered": kept} if kept else {}))
    _show(db.lesson(block["lesson_id"]), block, "block.updated")
    return f"board {block_id} extended; it plays now" + _board_notes(notes)


def _grown(script: str, more: str) -> str:
    return f"{script.rstrip()}\n{more.strip()}\n"


def _board_notes(notes: str) -> str:
    """The engine's warnings, when it gave any beyond `ok`."""
    warnings = notes.removeprefix("ok").strip()
    return f"; wise-board warns:\n{warnings}" if warnings else ""


@mcp.tool()
async def diagram_help(domain: str) -> str:
    """The types, predicates, labels and an example Substance of a diagram domain, to read before add_diagram."""
    if domain.strip() not in diagrams.domains():
        return f"error: no diagram domain named {domain!r}; the domains are {', '.join(diagrams.domains()) or 'none'}"
    return diagrams.help_text(domain.strip())


@mcp.tool()
async def find_art(query: str) -> str:
    """Search the installed art packs for icons to place in a figure: a cell, an organ, an animal, a flask, a virus,
    a molecule. query: one to three words naming the thing. Returns up to 20 icons as `ID | name | category |
    author | licence | ratio` (ratio is width over height, to size the <use>). Nothing found: try a broader or
    English word, or draw the shape yourself.
    """
    if not art.installed():
        return "no art packs are installed: draw the figure yourself"
    found, more = art.search(query)
    if not found:
        return "nothing found: try a broader word, or draw the shape yourself"
    lines = [f"{i['id']} | {i['name']} | {i['category']} | {i['author']} | {i['licence']} | {i['ratio']}" for i in found]
    return "\n".join(lines + (["(more matched; add a word to narrow the search)"] if more else []))


@mcp.tool()
async def add_plot(lesson_id: int, title: str, spec: dict, alt: str, teaches: figures.Teaches, setup: bool = False) -> str:
    """Show a plot: a function, a comparison of numbers, or data from a file in the workspace.

    spec: {"x": {"label": "t (s)", "domain"?: [a, b], "grid"?: true, "type"?: "log"}, "y": {...},
    "marks": [...]} where each mark is one of
      {"type": "line", "fn": "sin(x)/x", "domain": [-10, 10], "samples"?: 200, "label"?: "sinc"} — sampled here,
          never compute points yourself; x, numbers, + - * / ** and sin cos tan exp log sqrt abs pi e ...
      {"type": "line"|"dot"|"bar"|"area", "data": [{"t": 0, "v": 1.2, "case": "A"}, ...], "x": "t", "y": "v",
          "stroke"?: "case" (or "fill" for bar/area), "label"?: "..."} — up to 2,000 rows inline
      {"type": "line"|"dot"|..., "file": "results.csv", "x": "t", "y": "residual", "stroke"?: "case"} — a CSV or
          TSV in the course workspace, read here
      {"type": "rule", "y": 0, "label"?: "boiling point"} or {"type": "rule", "x": 0} — a label is written with the value; {"type": "text", "data": [{"x", "y", "text"}]};
      {"type": "rect", "data": [...], "x1", "x2", "y1", "y2"}.
    Name the quantity and unit on each axis label. One finding per plot. alt: what the plot shows, in words.
    teaches as for add_figure: the claim is the finding, notice is where on the plot it shows. setup as for add_figure.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not alt.strip():
        return "error: alt text is required"
    if problem := figure_blocker(lesson, setup):
        return f"refused: {problem}"
    try:
        purpose = figures.teaching(teaches)
        resolved = plots.resolve(spec, db.workspace(lesson["slug"]))
    except ValueError as e:
        return f"error: {e}"
    block = db.add_block(lesson_id, "plot", title, {"spec": resolved, "alt": alt.strip(), "teaches": purpose})
    _show(lesson, block)
    return f"shown as plot {block['id']}"


@mcp.tool()
async def add_widget(lesson_id: int, title: str, spec: dict, alt: str, teaches: figures.Teaches) -> str:
    """Show a model the learner operates: sliders set its inputs, readouts and a plot follow at once. Use it after
    the learner has predicted (a pose_challenge prediction, or a block asking them to decide what they expect), so
    moving a slider tests what they said.

    spec: {"controls": [{"name": "teeth", "label": "Output gear teeth", "min": 12, "max": 48, "step": 12, "value": 24,
    "unit"?: "teeth"}, ...] (1 to 3 sliders, at most 400 settings together; name is a short lowercase identifier),
    "readouts": [{"label": "Output turns per input turn", "expr": "-12/teeth", "unit"?: "turns", "digits"?: 2}, ...]
    (1 to 4; expr uses the slider names, numbers, + - * / ** and the plot functions), "plot"?: {"x": {"label",
    "domain"?}, "y": {"label", "domain"?}, "marks": [{"type": "line"|"area", "fn": "a*x**2", "domain": [-3, 3],
    "label"?}, {"type": "rule", "x"|"y": "expr of the sliders"}]} (1 to 4 marks; fn uses x and the slider names),
    "figure"?: an SVG drawn as for add_figure whose numbers follow the sliders: write `{{expr}}` in an attribute value
    (`r="{{teeth/4}}"`, `transform="rotate({{360/teeth}} 50 50)"`) or in text, `{{expr|2}}` to show it with two
    decimals; 1 to 30 places}. The drawing is checked as add_figure's is, at the starting setting and with every
    slider at its least and at its most.
    The server evaluates every setting; you never compute values yourself. The y range stays fixed across settings
    unless you give one. Start the sliders where the learner's prediction can be checked with one move; the first
    comparison changes one slider. alt: what the widget shows and what moving each slider changes. teaches as for
    add_figure: notice names the slider to move and what to watch. Each setting the learner stops at reaches you as a
    `[widget ID]` line on your next turn, with what the readouts showed; ask for the explanation from what they saw.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not alt.strip():
        return "error: alt text is required"
    if problem := pretest_blocker(lesson):
        return f"refused: {problem}"
    try:
        purpose = figures.teaching(teaches)
        resolved = widgets.resolve(spec)
    except ValueError as e:
        return f"error: {e}"
    if "figure" in resolved:
        settings = widgets.extremes(resolved)
        drawings, names = [widgets.filled(resolved, at) for at in settings], [f"with {widgets.setting(resolved, at)}" for at in settings]
        if found := await figcheck.problems(drawings, where=names):
            return f"error: {figcheck.report(found)}"
    block = db.add_block(lesson_id, "widget", title, {"spec": spec, "widget": resolved, "alt": alt.strip(), "teaches": purpose})
    _show(lesson, block)
    return f"shown as widget {block['id']}"
