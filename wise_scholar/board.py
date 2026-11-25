"""A figure played as a whiteboard: its `data-part` groups drawn in narrated steps, one sentence shown while each
step draws or erases its parts. Parts no step draws stand from the start. A learner's question about a part is
answered by drawing on the same figure: new parts merged in, played as further steps."""
import re
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as safe
from pydantic import BaseModel, Field

from . import art, figures

MIN_STEPS, MAX_STEPS = 2, 8
MAX_ADDED = 3
SAY_CHARS = 300
VIEWBOX = re.compile(r'viewBox="([^"]*)"')


class BoardStep(BaseModel):
    """One step of a board: the sentence shown while it draws its parts and erases others."""
    say: str = Field(max_length=SAY_CHARS)
    draw: list[str] = []
    erase: list[str] = []


def parts(svg: str) -> dict[str, set[str]]:
    """Every part id of the drawing, with the ids of the parts it sits inside."""
    found: dict[str, set[str]] = {}

    def walk(element: ET.Element, outer: frozenset[str]) -> None:
        part = element.get("data-part")
        if part:
            found.setdefault(part, set()).update(outer)
            outer = outer | {part}
        for child in element:
            walk(child, outer)

    walk(safe.fromstring(svg), frozenset())
    return found


def steps_error(svg: str, steps: list[BoardStep], earlier: list[dict] = ()) -> str | None:
    """Why these steps cannot play on this drawing after the earlier ones, or None."""
    known = parts(svg)
    if not known:
        return 'the figure has no parts: a board draws its <g data-part="id"> groups, so draw it again with them first'
    named = [p for s in steps for p in (*s.draw, *s.erase)]
    if unknown := sorted({p for p in named if p not in known}):
        return f"no part {', '.join(unknown)} in the figure; its parts are {', '.join(sorted(known))}"
    if any(not s.say.strip() for s in steps):
        return "every step says what it draws, in one sentence"
    if any(not s.draw and not s.erase for s in steps):
        return "every step draws or erases a part; say about a part already there in the step that draws it"
    drawn = [p for s in (*earlier, *(s.model_dump() for s in steps)) for p in s["draw"]]
    if twice := sorted({p for p in drawn if drawn.count(p) > 1}):
        return f"a part is drawn once: {', '.join(twice)} is drawn in more than one step"
    return _order_error(known, set(drawn), [*earlier, *(s.model_dump() for s in steps)])


def _order_error(known: dict[str, set[str]], stepped: set[str], steps: list[dict]) -> str | None:
    on = {p for p in known if p not in stepped}
    for n, step in enumerate(steps, 1):
        for p in step["erase"]:
            if p not in on:
                return f"step {n} erases {p}, which is not on the board then"
            on.discard(p)
        for p in step["draw"]:
            if hidden := sorted(a for a in known[p] if a not in on and a not in step["draw"]):
                return f"step {n} draws {p} inside {', '.join(hidden)}, which is not on the board then; draw {hidden[0]} first or move {p} out of it"
            on.add(p)
    return None


def merge(svg: str, fragment: str, prefix: str) -> tuple[str, list[str], list[dict]]:
    """The drawing with the fragment's parts added on top, the new part ids and the art they credit; raises ValueError
    when the fragment is not a series of new `<g data-part>` groups."""
    box = VIEWBOX.search(svg)
    wrapped, credits = art.inline(figures.clean(f'<svg xmlns="{figures.SVG_NS}" viewBox="{box[1] if box else "0 0 600 400"}">{fragment}</svg>'))
    added = safe.fromstring(wrapped)
    new = [child.get("data-part") for child in added if child.tag != f"{{{figures.SVG_NS}}}defs"]
    if not new or not all(new):
        raise ValueError('the drawing to add is one or more <g data-part="id"> groups, each a new part with its labels and arrows')
    if taken := sorted(set(new) & set(parts(svg))):
        raise ValueError(f"the figure already has a part {', '.join(taken)}; give each added part a new id")
    if len(set(new)) < len(new):
        raise ValueError("each added part has its own id")
    inner = figures.prefix_ids(wrapped, prefix).split(">", 1)[1].rpartition("</svg>")[0]
    head, _, _ = svg.rpartition("</svg>")
    return f"{head}{inner}</svg>", new, credits


FIGURE = ("svg", "credits", "board")


def unanswered(data: dict) -> dict | None:
    """The drawing, credits and board a figure had before answers were drawn on it, None when none were. A figure
    answered before this was kept tells its last answer alone, by the steps that draw it."""
    if "unanswered" in data:
        return data["unanswered"]
    board = data.get("board", {})
    if "answer" not in board:
        return None
    before, answer = board["steps"][: board["answer"]], board["steps"][board["answer"] :]
    drawn = {p for s in answer for p in s["draw"]}
    root = safe.fromstring(data["svg"])
    root[:] = [child for child in root if child.get("data-part") not in drawn]
    if not any(figures._split(e.tag)[1] in art.DRAWN for child in root if child.tag != f"{{{figures.SVG_NS}}}defs" for e in child.iter()):
        return None
    ET.register_namespace("", figures.SVG_NS)
    return {"svg": ET.tostring(root, encoding="unicode"), "credits": data["credits"]} | ({"board": {"steps": before}} if before else {})


def narrated(kept: dict, steps: list[dict]) -> dict:
    """What a figure was before its answers, narrated anew by the steps that draw what it had."""
    known = parts(kept["svg"])
    steps = [s | {"erase": [p for p in s["erase"] if p in known]} for s in steps if known.keys() >= set(s["draw"])]
    steps = [s for s in steps if s["draw"] or s["erase"]]
    return {k: v for k, v in kept.items() if k != "board"} | ({"board": {"steps": steps}} if steps else {})


def without_answers(data: dict, authored: bool = False) -> dict:
    """A figure's data, and that of the drawing it replaced, without the answers drawn for the learner. In a prepared
    course (authored) they were drawn for its author and stay, as any part of the figure."""
    if "previous" in data:
        data = data | {"previous": without_answers(data["previous"], authored)}
    if authored:
        return {k: v for k, v in data.items() if k != "unanswered"} | ({"board": {"steps": data["board"]["steps"]}} if "board" in data else {})
    kept = unanswered(data)
    return {k: v for k, v in data.items() if k not in (*FIGURE, "unanswered")} | kept if kept else data
