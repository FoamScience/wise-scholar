"""A figure played as a whiteboard: its `data-part` groups drawn in narrated steps, one sentence spoken while each
step draws or erases its parts. Parts no step draws stand from the start."""
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as safe
from pydantic import BaseModel, Field


MIN_STEPS, MAX_STEPS = 2, 8
SAY_CHARS = 300


class BoardStep(BaseModel):
    """One step of a board: the sentence said while it draws its parts and erases others."""
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

