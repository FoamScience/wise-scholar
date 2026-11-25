from typing import Literal

from .. import db
from ..tutor import _show, mcp, prepared, pretest_blocker, shown_twice_error


@mcp.tool()
async def add_block(lesson_id: int, kind: Literal["prose", "example"], markdown: str) -> str:
    """Append a block to the lesson area of the learner's screen.

    markdown may hold LaTeX math in $...$ and $$...$$. prose: explanation the learner reads. example: a worked example.
    Anything the learner should work out themselves goes through pose_challenge instead.
    Take lesson_id from the [state] line of the turn.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if problem := pretest_blocker(lesson):
        return f"refused: {problem}"
    _show(lesson, db.add_block(lesson_id, kind, markdown))
    return "shown"


@mcp.tool()
async def ask(lesson_id: int, question: str, options: list[str], multiple: bool = False, non_goals: bool = False) -> str:
    """Show the learner one question card with 2 to 5 short answer options.

    multiple: more than one option may be true (what they already know, what they want to do,
    what equipment there is): the learner picks any number and the answer arrives as the picks
    joined by "; ". The learner can also answer in their own words, alone or after their picks, in the same
    "; "-joined answer. This returns at once: end your
    turn after calling it, and the answer arrives as the next turn.
    non_goals: for the question about what the course should enable; implies multiple. The learner can
    also mark options as not wanted, and the server records those as the course's non-goals.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not 2 <= len(options) <= 5:
        return "error: a question card takes 2 to 5 options"
    if problem := shown_twice_error(lesson_id, "question", question):
        return problem
    data = {"options": options, "answer": None, "multiple": multiple or non_goals}
    if non_goals:
        data["non_goals"] = []
    _show(lesson, db.add_block(lesson_id, "question", question, data))
    return "shown; end the turn and wait for the answer"


OUTLINE_STEPS = (3, 6)
MOMENTUM_STEPS = 4


def _outline(lesson_id: int) -> dict | None:
    return next((b for b in db.blocks(lesson_id) if b["kind"] == "outline"), None)


def cards_shown(lesson_id: int) -> int:
    return db.row("SELECT COUNT(*) AS n FROM blocks WHERE lesson_id = ? AND kind != 'outline'", lesson_id)["n"]


def _cards_error(lesson_id: int, cards: int, steps: int) -> str | None:
    least = max(steps, cards_shown(lesson_id) + 1)
    if cards >= least:
        return None
    return f"error: cards is the estimate for the whole unit, at least {least} here (cards already shown, plus the summary still to come)"


def _write_outline(block: dict, data: dict) -> dict:
    db.conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (db.outline_text(data["steps"], data["at"]), block["id"]))
    return db.set_block_data(block["id"], data)


def _steps_error(steps: list[str]) -> str | None:
    if not (OUTLINE_STEPS[0] <= len(steps) <= OUTLINE_STEPS[1] + 1) or not all(steps):
        return f"error: an outline has {OUTLINE_STEPS[0]} to {OUTLINE_STEPS[1]} non-empty steps"
    if len(set(steps)) != len(steps):
        return "error: each step is named differently"
    return None


def _first_outline(lesson: dict, steps: list[str], reason: str, cards: int) -> str:
    # a momentum unit stays short; speed allows the full range
    most = MOMENTUM_STEPS if lesson["pace"] == "momentum" else OUTLINE_STEPS[1]
    if len(steps) > most or reason.strip():
        return f"error: a first outline here has {OUTLINE_STEPS[0]} to {most} steps and no reason"
    if not cards:
        return "error: cards is required: how many cards the whole unit will show"
    if problem := _cards_error(lesson["id"], cards, len(steps)):
        return problem
    block = db.add_block(lesson["id"], "outline", "", {"steps": steps, "at": 0, "added": None, "cards": cards})
    _show(lesson, _write_outline(block, block["data"]))
    return f"outline shown: step 1 of {len(steps)}, about {cards} cards"


def _new_step(old: list[str], steps: list[str]) -> int | None:
    # steps are unique, so the one new step has a single place
    return next((i for i in range(len(steps)) if steps[:i] + steps[i + 1:] == old), None) if len(steps) == len(old) + 1 else None


def _add_step(lesson: dict, block: dict, steps: list[str], reason: str, cards: int) -> str:
    data = block["data"]
    if cards and (problem := _cards_error(lesson["id"], cards, len(steps))):
        return problem
    if data["added"]:
        return "refused: the outline already took its one added step"
    if not reason.strip():
        return "error: reason is required when adding a step"
    old = data["steps"]
    if data["at"] >= len(old):
        return "refused: every step is already done"
    if missing := [step for step in old if step not in steps]:
        return f"error: keep every earlier step word for word; missing: {missing[0]!r}"
    new = _new_step(old, steps)
    if new is None:
        return "error: keep every earlier step in its order and add exactly one"
    if new < data["at"]:
        return "error: a step goes after the step the learner is on, not before"
    data = {**data, "steps": steps, "added": {"step": steps[new], "reason": " ".join(reason.split())}} | ({"cards": cards} if cards else {})
    _show(lesson, _write_outline(block, data), "block.updated")
    return f"step added: now step {data['at'] + 1} of {len(steps)}"


@mcp.tool()
async def set_outline(lesson_id: int, steps: list[str], reason: str = "", cards: int = 0) -> str:
    """Show the unit's plan: 3 to 6 short steps (at most 4 when the course's pace is momentum), each one thing the learner does or gets ("Predict what foldr
    returns", "See the pattern behind it", "Practise on lists", "Check yourself"). The learner sees them as a
    numbered list with a step counter. Call it once in the unit's first turn, together with the opening.
    cards: required the first time, your estimate of how many cards the whole unit shows, the opening, each
    explanation, check and task and the closing summary included. Each card is numbered for the learner
    against it ("4 / 12"), so keep it honest; revise it here or with step_done when the plan changes.

    Later, at most once, call it again to insert one step the learner turned out to need (after a confident miss,
    say): steps then holds every earlier step in its order plus the new one, never before a step already done, and
    reason says in one sentence to the learner why it was added. Steps are never dropped. Call step_done as each
    step ends.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if lesson["phase"] != "lesson" or lesson["concept_id"] is None:
        return "error: only a unit lesson has an outline"
    steps = [" ".join(s.split()) for s in steps]
    if problem := _steps_error(steps):
        return problem
    block = _outline(lesson_id)
    if not block:
        return _first_outline(lesson, steps, reason, cards)
    return _add_step(lesson, block, steps, reason, cards)


@mcp.tool()
async def step_done(lesson_id: int, cards: int = 0) -> str:
    """Mark the current step of the unit's outline done, moving the learner's counter on by one.

    cards: when the unit turns out longer or shorter than planned, the new estimate of all its cards.
    """
    block = _outline(lesson_id)
    if not block:
        return "error: this lesson has no outline; call set_outline first"
    data = block["data"]
    if data["at"] >= len(data["steps"]):
        return "refused: every step is already done"
    if cards and (problem := _cards_error(lesson_id, cards, len(data["steps"]))):
        return problem
    data = {**data, "at": data["at"] + 1} | ({"cards": cards} if cards else {})
    _show(db.lesson(lesson_id), _write_outline(block, data), "block.updated")
    left = len(data["steps"]) - data["at"]
    return f"step {data['at']} of {len(data['steps'])} done" + ("" if left else "; every step is done, finish the lesson when its checks are answered")


def _unfinished(lesson: dict, blocks: list[dict]) -> str | None:
    if any(b["kind"] == "done" for b in blocks):
        return "refused: this lesson is already finished"
    if not prepared(lesson) and any(b["kind"] == "quiz" and b["data"].get("correct") is None for b in blocks):
        return "refused: a quick check is still unanswered or ungraded"
    return None


@mcp.tool()
async def finish_lesson(lesson_id: int, summary: str) -> str:
    """Close a unit lesson once its concept is covered and the quick checks are answered, or a revisit once its items are.

    summary: two or three sentences to the learner on what they can now do. It becomes the last card of
    the lesson, under which the learner gets a button to the next unit. Call it once, then end the turn.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if lesson["concept_id"] is None and lesson["phase"] != "revisit":
        return "error: only a unit lesson or a revisit is finished this way"
    if problem := _unfinished(lesson, db.blocks(lesson_id)):
        return problem
    if (outline := _outline(lesson_id)) and outline["data"]["at"] < len(outline["data"]["steps"]):
        _show(lesson, _write_outline(outline, {**outline["data"], "at": len(outline["data"]["steps"])}), "block.updated")
    _show(lesson, db.add_block(lesson_id, "done", summary, {}))
    return "finished; end the turn"
