import re
import unicodedata
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from .. import db, figures, hub
from ..playbooks import PLAYBOOKS, check_ranking, describe
from ..tutor import _show, mcp


class Ranked(BaseModel):
    mechanism: str
    rationale: str


FACT_CHARS = 300
PLACEMENT_AREAS = (2, 8)
AREA_CHARS = 300


class Module(BaseModel):
    title: str
    concepts: list[str]
    known: list[str] = []
    needs: dict[str, list[str]] = {}


class Area(BaseModel):
    title: str
    holds: str
    lacks: str


class Renamed(BaseModel):
    old: str
    new: str


class Milestone(BaseModel):
    concept: str
    deliverable: str


@mcp.tool()
async def set_pace(course_id: int, pace: Literal["momentum", "speed"]) -> str:
    """Record how the learner wants to move through this course, from their answer in the interview.

    momentum: units of one sitting at a steady pace, the outline followed as set. speed: longer units,
    and the learner may test out of a step or a whole unit by answering its checks first. The learner can switch
    any time on the course map; the default is momentum.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    save_pace(course_id, pace)
    return f"pace set to {pace}"


@mcp.tool()
async def set_sitting(course_id: int, minutes: int) -> str:
    """Record how long one study sitting usually is for the learner in this course, from their answer in the
    interview. A unit is planned to fit one sitting, and the course map is sized from how long units really take."""
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    if not 5 <= minutes <= 240:
        return "error: a sitting is 5 to 240 minutes"
    db.conn.execute("UPDATE courses SET sitting = ? WHERE id = ?", (minutes, course_id))
    return f"sitting set to {minutes} minutes"


# Until two of the learner's units are measured, a unit is taken to run twice the sitting it is planned for.
SITTING_MINUTES = 30
UNMEASURED_STRETCH = 2


def unit_minutes(course: dict) -> tuple[float, int]:
    """Minutes one unit takes this learner, and over how many finished units that was measured (0: estimated)."""
    if pace := db.unit_pace(course["profile_id"]):
        return pace["unit"], pace["units"]
    return UNMEASURED_STRETCH * (course["sitting"] or SITTING_MINUTES), 0


def map_budget(course: dict, hours: int | None = None) -> int | None:
    """The most units to study that fit the course's hours, with the practice units the server adds; None for a
    prepared course or one without hours."""
    hours = hours or course["hours"]
    if not hours or course["mode"] == "teacher":
        return None
    units = max(1, round(hours * 60 / unit_minutes(course)[0]))
    return max(n for n in range(1, units + 1) if n + n // db.PRACTICE_EVERY <= units)


def _over_budget(course: dict, modules: list[Module], hours: int | None = None, known: frozenset[str] = frozenset(), allowed: int = 0) -> str | None:
    """Why a map does not fit the course's hours, or None when it does or holds no more units than allowed."""
    budget = map_budget(course, hours)
    studied = sum(len(set(m.concepts) - set(m.known) - known) for m in modules)
    if budget is None or studied <= max(budget, allowed):
        return None
    minutes, measured = unit_minutes(course)
    return (
        f"error: the map has {studied} units to study; at about {minutes:.0f} minutes a unit for this learner "
        f"({f'measured over their last {measured} units' if measured else 'twice the sitting, until units are measured'}), "
        f"with a practice unit after every {db.PRACTICE_EVERY}, the course's {hours or course['hours']} hours fit {budget}. "
        "Merge or cut units, or mark known ones; when the learner asked for more than fits, set hours to what the map needs."
    )


def save_pace(course_id: int, pace: str) -> None:
    db.conn.execute("UPDATE courses SET pace = ? WHERE id = ?", (pace, course_id))
    hub.publish(course_id, {"type": "course.pace", "pace": pace})


@mcp.tool()
async def note_learner(course_id: int, fact: str, scope: Literal["learner", "course"]) -> str:
    """Record one fact you learned about the learner, as a full sentence.

    scope learner: true of the person in any course (skills, background, interests).
    scope course: only about this course (goal, time per sitting, chosen theme).
    Recorded facts come back in the [known] lines of every later turn.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    fact = " ".join(fact.split())
    if len(fact) > FACT_CHARS:
        return f"error: a fact is one sentence, under {FACT_CHARS} characters"
    db.add_fact(course_id, fact, about_learner=scope == "learner")
    return "noted"


@mcp.tool()
async def list_playbooks() -> str:
    """List the teaching mechanisms with the rubric that says which topics and learners each one fits."""
    return "\n\n".join(f"{p['id']}: {p['title']}\nfits: {p['fits']}" for p in PLAYBOOKS.values())


@mcp.tool()
async def get_playbook(mechanism: str) -> str:
    """Return the full teaching procedure of one mechanism."""
    if mechanism not in PLAYBOOKS:
        return f"error: unknown mechanism; valid ids are {sorted(PLAYBOOKS)}"
    return PLAYBOOKS[mechanism]["body"]


@mcp.tool()
async def rank_mechanisms(course_id: int, ranking: list[Ranked]) -> str:
    """Show the learner your ranked teaching plan, best fit first.

    Each rationale is one sentence addressed to the learner that ties the rank to
    what they told you. The learner sees the ranking and may pick a different one.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    entries = [r.model_dump() for r in ranking]
    if problem := check_ranking(entries):
        return f"error: {problem}"
    db.set_ranking(course_id, entries)
    hub.publish(course_id, {"type": "plan.ranked", "ranking": describe(entries), "mechanism": entries[0]["mechanism"]})
    return "shown"


def _needs_problem(order: list[str], needs: dict[str, list[str]]) -> str | None:
    """Why prerequisites do not fit a map whose concept units come in this order, or None when they do."""
    at = {title: n for n, title in enumerate(order)}
    if stray := sorted({t for unit, ns in needs.items() for t in (unit, *ns)} - at.keys()):
        return f"error: needs names {stray}, which are not concept units of the map"
    if forward := [f"{unit} needs {n}" for unit, ns in needs.items() for n in ns if at[n] >= at[unit]]:
        return f"error: a unit needs only units before it in the map, not {forward}; reorder the map first"
    return None


def _module_needs(modules: list[Module]) -> tuple[dict[str, list[str]], str | None]:
    if stray := [k for m in modules for k in m.needs if k not in m.concepts]:
        return {}, f"error: needs keys {stray} are not concepts of their module"
    return {unit: ns for m in modules for unit, ns in m.needs.items()}, None


@mcp.tool()
async def set_course_map(course_id: int, modules: list[Module]) -> str:
    """Lay out the course as ordered modules, each a list of concept titles, and show it as the course map.

    One concept is what one sitting can cover. The learner opens a concept to start its lesson.
    known lists the concept titles of a module that a placement check showed the learner
    already has; they appear as placed out. The server adds a practice unit after every third
    unit to study: earlier tasks come back varied and mixed, with no teaching.
    needs: for units of the module, the earlier units of the map they build on directly (not what
    those build on in turn); a unit that builds on nothing in the map is left out. A unit can
    only need units placed before it.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    if db.concepts(course_id):
        return "error: this course already has a map"
    if not any(m.concepts for m in modules):
        return "error: the map has no concepts"
    if stray := [k for m in modules for k in m.known if k not in m.concepts]:
        return f"error: known titles {stray} are not concepts of their module"
    needs, problem = _module_needs(modules)
    if problem or (problem := _needs_problem([t for m in modules for t in m.concepts], needs)):
        return problem
    if problem := _over_budget(db.course(course_id), modules):
        return problem
    db.set_concepts(course_id, [m.model_dump() for m in modules])
    db.set_needs(course_id, needs, replace=True, linked=bool(needs))
    hub.publish(course_id, {"type": "map.set", "concepts": db.concept_view(course_id)})
    return "shown"


@mcp.tool()
async def revise_course_map(course_id: int, modules: list[Module], renamed: list[Renamed] = [], hours: int | None = None) -> str:
    """Change the course map after it exists, when the learner asks to leave something out, add something,
    reorder, shorten or go deeper. Give the whole new map, in order.

    Give the concept units only: the server lays the practice units out again by itself.
    A unit whose title stays exactly as it is keeps its lesson, its cards and its progress, wherever
    you move it. A title you leave out is dropped; a new title becomes a new unit. To reword a title
    without losing its lesson, list it in renamed and use the new title in modules. A unit that already
    has a lesson cannot be dropped: keep it, and list it in known if the learner is done with it.
    known: titles to mark as already mastered; units marked before stay marked (set_known unmarks one).
    needs: as in set_course_map, by the new titles; a unit you give needs for gets exactly that list,
    the others keep theirs unless the new order puts what they need after them.
    hours: set it only when the learner changes the teaching time planned for the whole course.
    Each module appears once. A capstone keeps the milestones of the units that remain and moves to the
    module that holds most of them; one whose units are all gone, or whose module another capstone holds,
    is removed, and you may propose a new one with set_capstone.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    current = {c["title"] for c in db.concepts(course_id) if c["kind"] == "concept"}
    if not current:
        return "error: this course has no map yet; use set_course_map"
    titles = [title for m in modules for title in m.concepts]
    if not titles:
        return "error: the map has no concepts"
    if practice := [t for t in titles if t in {c["title"] for c in db.concepts(course_id) if c["kind"] == "practice"}]:
        return f"error: {practice} are practice units the server places by itself; give the concept units only"
    if repeated := sorted({t for t in titles if titles.count(t) > 1}):
        return f"error: titles {repeated} appear more than once"
    module_titles = [m.title for m in modules]
    if repeated := sorted({t for t in module_titles if module_titles.count(t) > 1}):
        return f"error: modules {repeated} appear more than once; give each module once, with all its units"
    if hours is not None and not 1 <= hours <= 5000:
        return "error: hours must be between 1 and 5000"
    if stray := [k for m in modules for k in m.known if k not in m.concepts]:
        return f"error: known titles {stray} are not concepts of their module"
    needs, problem = _module_needs(modules)
    if problem or (problem := _needs_problem(titles, needs)):
        return problem
    names = {r.old: r.new for r in renamed}
    if unknown := sorted(set(names) - current):
        return f"error: renamed titles {unknown} are not in the current map"
    if clash := sorted(new for new in names.values() if new in current - set(names) or list(names.values()).count(new) > 1):
        return f"error: new titles {clash} are taken"
    after = {names.get(t, t) for t in db.started_concepts(course_id)}
    if lost := sorted(after - set(titles)):
        return f"error: units {lost} already have a lesson and cannot be dropped; keep them, and list them in known if the learner is done with them"
    units = [c for c in db.concepts(course_id) if c["kind"] == "concept"]
    known = frozenset(names.get(c["title"], c["title"]) for c in units if c["known"])
    if problem := _over_budget(db.course(course_id), modules, hours, known, allowed=sum(not c["known"] for c in units)):
        return problem
    try:
        removed = db.revise_concepts(course_id, [m.model_dump() for m in modules], names, hours)
    except ValueError as started:
        return f"error: units {started} already have a lesson and cannot be dropped"
    db.set_needs(course_id, needs, replace=False, linked=bool(needs))
    hub.publish(course_id, {"type": "map.set", "concepts": db.concept_view(course_id), "capstones": db.capstones(course_id)})
    dropped = sorted(current - set(names) - set(titles))
    note = f"; dropped {dropped}" if dropped else ""
    note += f"; capstones removed with their units: {removed}" if removed else ""
    return f"shown{note}"


@mcp.tool()
async def set_prerequisites(course_id: int, needs: dict[str, list[str]]) -> str:
    """Record which units of the existing course map build on which, replacing what was recorded before.

    needs: for each concept unit, the earlier units it builds on directly (not what those build on
    in turn), by their exact titles; a unit that builds on nothing in the map is left out. A unit
    can only need units placed before it.
    """
    order = [c["title"] for c in db.concepts(course_id) if c["kind"] == "concept"]
    if not order:
        return "error: this course has no map yet; use set_course_map"
    if not any(needs.values()):
        return "error: no unit needs another; give, for each unit that builds on earlier ones, those units"
    if problem := _needs_problem(order, needs):
        return problem
    db.set_needs(course_id, needs, replace=True, linked=True)
    hub.publish(course_id, {"type": "map.set", "concepts": db.concept_view(course_id)})
    return "linked"


@mcp.tool()
async def set_cover(course_id: int, svg: str, alt: str) -> str:
    """Draw the course's cover, shown on its card on the home screen, replacing the one before it.

    svg: a flat editorial illustration of what the course is about: the one object, scene or idea a reader
    recognises the subject by, built from a few large simple shapes, with the subject's real proportions. viewBox
    "0 0 640 360", a full-bleed background rect, no text, no outlines thinner than 2 px. It is shown as a picture,
    the same in both themes, so give every shape a fill or stroke from the palette: teal #0b5f5a, deep teal
    #084742, teal tint #e0efec, amber #f0b35c, amber tint #fbecd5, ink #16201f, paper #fcfdfd. No script, style
    element, image, foreignObject, art pack icon or external link. alt: what the cover shows, in one sentence.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    if "art:" in svg:
        return "error: a cover has no art pack icons; draw every shape yourself"
    if not alt.strip():
        return "error: alt text is required"
    try:
        drawing = figures.clean(svg)
    except ValueError as e:
        return f"error: {e}"
    db.conn.execute("UPDATE courses SET cover = ?, cover_alt = ? WHERE id = ?", (drawing, alt.strip(), course_id))
    return "drawn"


@mcp.tool()
async def set_capstone(course_id: int, module: str, title: str, brief: str, milestones: list[Milestone]) -> str:
    """Propose the project that runs through one module of the course map: one milestone per unit.

    module: a module title from the map. brief: what the finished project is, in a few sentences the
    learner reads. milestones: for every concept of the module, in order, the deliverable that unit adds
    (a file and what it must do; for a language course, a piece of the text or recording being built).
    The last one is the integration milestone. Files live in the project's folder under the workspace,
    shared by every lesson of the module.
    """
    concepts = [c for c in db.concepts(course_id) if c["module"] == module and c["kind"] == "concept"]
    if not concepts:
        return f"error: no module {module!r} in the map; modules are {sorted({c['module'] for c in db.concepts(course_id)})}"
    if any(c["module"] == module for c in db.capstones(course_id)):
        return "error: this module already has a capstone"
    by_title = {c["title"]: c["id"] for c in concepts}
    if [m.concept for m in milestones] != list(by_title):
        return f"error: milestones must name every concept of the module in map order: {list(by_title)}"
    ascii_title = unicodedata.normalize("NFKD", module).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-") or f"module-{len(db.capstones(course_id)) + 1}"
    folder = f"projects/{slug}"
    course = db.course(course_id)
    (db.workspace(course["slug"]) / folder).mkdir(parents=True, exist_ok=True)
    capstone = db.add_capstone(course_id, module, title, brief, folder, [(by_title[m.concept], m.deliverable) for m in milestones])
    hub.publish(course_id, {"type": "capstone.set", "capstone": capstone})
    return f"set; project folder {folder}/ (relative to the workspace)"


@mcp.tool()
async def set_known(course_id: int, known: list[str], unknown: list[str]) -> str:
    """After a retaken placement check, mark which concepts of the existing map the learner now has (placed out)
    and which they lack (open again). Titles must match the map exactly; other concepts keep their state."""
    titles = {c["title"] for c in db.concepts(course_id) if c["kind"] == "concept"}
    if not titles:
        return "error: this course has no map yet; use set_course_map"
    if stray := [t for t in [*known, *unknown] if t not in titles]:
        return f"error: {stray} are not concepts of the map"
    db.set_known(course_id, known, unknown)
    hub.publish(course_id, {"type": "map.set", "concepts": db.concept_view(course_id)})
    return "updated"


@mcp.tool()
async def set_placement(course_id: int, level: str, summary: str, areas: list[Area]) -> str:
    """Record the result of the placement check.

    level: a short label of where the learner starts. For a natural language use the
    CEFR level (A1, A2, B1, B2, C1, C2). summary: two or three sentences to the learner
    on what the check showed they have and what it showed they lack.
    areas: one per part of the topic the check bracketed, in the order the course builds them:
    title names the part, holds says in one sentence what the learner has in it (empty when
    nothing), lacks says where their understanding of it ends (empty when it does not end
    within the course).
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    low, high = PLACEMENT_AREAS
    if not low <= len(areas) <= high:
        return f"error: give {low} to {high} areas"
    entries = [{k: " ".join(v.split()) for k, v in a.model_dump().items()} for a in areas]
    if not all(e["title"] for e in entries):
        return "error: every area needs a title"
    if twice := sorted(t for t, n in Counter(e["title"] for e in entries).items() if n > 1):
        return f"error: areas {twice} appear more than once"
    if long := [e["title"] for e in entries if max(len(v) for v in e.values()) > AREA_CHARS]:
        return f"error: areas {long} are too long; one sentence each, under {AREA_CHARS} characters"
    db.set_placement(course_id, level, summary, entries)
    hub.publish(course_id, {"type": "placement.set", "level": level, "placement": summary, "areas": entries})
    # Each check keeps its own result card, so a retake leaves the earlier ones readable.
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'placement' ORDER BY id DESC LIMIT 1", course_id)
    if lesson:
        _show(db.lesson(lesson["id"]), db.add_block(lesson["id"], "placement", summary, {"level": level, "areas": entries}))
    return "recorded"
