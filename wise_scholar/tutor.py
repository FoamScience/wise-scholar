import importlib
import logging
import os
import random
from contextvars import ContextVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ListToolsResult, PaginatedRequestParams

from . import db, hub, vocab
from .backends import TURN_HEADER

mcp = MCPServer("scholar")


log = logging.getLogger(__name__)


def _shuffled(options: list) -> list:
    """The tutor tends to write the right option first; every choice card stores its options in random order."""
    return random.sample(options, len(options))


# A pretest is one short question; past this length it has become a lecture with questions attached.
PRETEST_CHARS = 700
# A turn that keeps calling tools is a tutor going in circles, or one talked into it.
TOOL_CALLS_PER_TURN = int(os.environ.get("WISE_SCHOLAR_TOOL_CALLS", "80"))


def _show(lesson: dict, block: dict, event: str = "block.added") -> None:
    hub.publish(lesson["course_id"], {"type": event, "lesson_id": lesson["id"], "block": block})


def _patch_block(challenge_id: int, change: dict, locked: dict | None = None) -> None:
    block = db.block(challenge_id)
    block = db.set_block_data(challenge_id, {**block["data"], **change}, locked)
    _show(db.lesson(block["lesson_id"]), block, "block.updated")


def _pretest_length_error(text: str) -> str | None:
    if len(text) <= PRETEST_CHARS:
        return None
    return (
        f"error: not shown. A pretest is one question with one prediction, at most {PRETEST_CHARS} characters; "
        f"this one has {len(text)}. Pose again with one question, without code or names the learner has not met"
    )


def prepared(lesson: dict) -> bool:
    """A teacher's course: cards are authored for a class, nobody answers them here, so the learner gates are off."""
    return lesson["mode"] == "teacher"


keyed = db.keyed


def shown_twice_error(lesson_id: int, kind: str, question: str) -> str | None:
    """Refuses a card whose question is already on screen unanswered, as a repeated tool call would show it."""
    same = " ".join(question.split()).casefold()
    for b in db.blocks(lesson_id):
        if b["kind"] == kind and " ".join(b["markdown"].split()).casefold() == same and b["data"] and b["data"].get("answer", "") is None:
            return f"error: not shown; the same question is already on screen as card {b['id']}, not answered yet"
    return None


def pretest_blocker(lesson: dict) -> str | None:
    """A concept lesson explains nothing until the learner has tried its opening card (a pretest challenge or quiz,
    or an exercise); placed-out concepts and prepared courses are exempt."""
    if not _needs_opening(lesson) or any(_tried_opening(block) for block in db.blocks(lesson["id"])):
        return None
    return (
        "the lesson has no attempted opening yet. Open it with pose_challenge or pose_quiz with pretest set, or with "
        "pose_exercise, end the turn, and explain only after the learner has tried it"
    )


def _needs_opening(lesson: dict) -> bool:
    """A concept lesson of a unit not placed out, in a course the learner answers here."""
    if lesson["phase"] != "lesson" or not lesson["concept_id"] or keyed(lesson):
        return False
    concept = db.row("SELECT known FROM concepts WHERE id = ?", lesson["concept_id"])
    return bool(concept) and not concept["known"]


def _tried_opening(block: dict) -> bool:
    """A pretest or exercise the learner has answered, attempted or run."""
    data = block["data"] or {}
    opening = data.get("pretest") or block["kind"] == "exercise"
    return bool(opening and (data.get("attempts") or data.get("answer") is not None or data.get("last_run")))


def capstone_brief(lesson: dict) -> str:
    """What the lesson-begins event says about the unit's milestone, if its module has a capstone."""
    m = db.milestone_for(lesson["concept_id"]) if lesson["concept_id"] else None
    if not m:
        return _capstone_proposal(lesson)
    stage = "the integration milestone: it joins the earlier parts into the finished project" if m["position"] == m["total"] else f"milestone {m['position']} of {m['total']}"
    return (
        f"\nCapstone {m['capstone']!r} for module {m['module']!r}: {m['brief']}\nThis unit's milestone, {stage}: {m['deliverable']}"
        f"{' (already done)' if m['done'] else ''}. Project folder: {m['folder']}/ in the workspace, shared by the module's lessons; "
        "pose the milestone with pose_exercise, pose_challenge or pose_writing with milestone set, after the unit's own practice."
        + ("\nAfter the integration milestone, pose one far-transfer challenge with transfer set: the same ideas on different data or in a different domain, no hints." if m["position"] == m["total"] else "")
    )


def _capstone_proposal(lesson: dict) -> str:
    """On the first unit of a module without a capstone, in a course that builds things, the ask to propose one."""
    concepts = [c for c in db.concepts(lesson["course_id"]) if c["kind"] == "concept"]
    mine = next((c for c in concepts if c["id"] == lesson["concept_id"]), None)
    module = [c for c in concepts if mine and c["module"] == mine["module"]]
    if not mine or module[0]["id"] != mine["id"] or lesson["mechanism"] not in ("hands-on", "leveled-course"):
        return ""
    units = [c["title"] for c in module]
    return (
        f"\nThis is the first unit of module {mine['module']!r}, which has no capstone yet. Propose one with set_capstone "
        f"in your first turn: one project the whole module builds (code for a programming course, a text or recorded piece for a language), "
        f"one deliverable per unit in this order: {units}. Then say what it is to the learner in two sentences."
    )


def vocab_round(lesson: dict, data: dict, known: list[str]) -> tuple[dict, str | None]:
    """Record one round of the vocabulary check; returns the new card data and, once the tier is bracketed,
    the event line for the tutor."""
    lang, current = data["lang"], data["current"]
    known = [w for w in current["words"] if w in known]
    for word in current["words"]:
        db.set_vocab(lesson["profile_id"], lang, word, "known" if word in known else "learning", "placement")
    passed = len(known) / len(current["words"]) >= vocab.TIER_DONE_SHARE
    rounds = [*data["rounds"], {**current, "known": known, "passed": passed}]
    results = {r["tier"]: r["passed"] for r in rounds}
    top = vocab.max_tier(lang)
    if (probe := vocab.next_probe(results, top)) is not None:
        return {**data, "rounds": rounds, "current": {"tier": probe, "words": vocab.sample_tier(lang, probe)}}, None
    tier = vocab.estimated_tier(results, top)
    db.set_vocab_tier(lesson["profile_id"], lang, tier)
    claimed = next((r["known"] for r in reversed(rounds) if r["passed"]), [])
    verify = ", ".join(claimed[:3]) or "none"
    held = f"holds the {(tier - 1) * vocab.TIER} most common words of {lang}" if tier > 1 else f"holds none of the {lang} tiers yet"
    event = (
        f"[event] The vocabulary check ended: the learner {held} "
        f"and works on tier {tier} (the {tier * vocab.TIER} most common). Rounds: "
        + "; ".join(f"tier {r['tier']} {len(r['known'])}/{len(r['words'])}" for r in rounds)
        + f". Claimed words to verify in context: {verify}. Pose two open questions in {lang} that each need one of "
        "them, with lemma set on pose_quiz, then continue the placement."
    )
    return {**data, "rounds": rounds, "current": None, "tier": tier}, event


# What each turn that runs beside a lesson may call.
CARD_TOOLS = ("split_card",)
GRAPH_TOOLS = ("search_claims", "record_claims")
CLEANUP_TOOLS = ("propose_edits",)
EXPLORE_TOOLS = ("suggest_courses",)
RECAP_TOOLS = ("write_recap",)
# A gist turn writes a finished lesson's gist board with the lesson's own board tools.
GIST_TOOLS = ("board_help", "add_board")
CONTRIBUTE_TOOLS = ("find_repos", "find_issues", "look_at_repo", "outline_repo_file", "read_repo_lines", "search_repo_code", "suggest_contributions")
_searched: set[int] = set()  # lessons whose running graph turn has searched the claims
_calling: ContextVar[dict | None] = ContextVar("calling", default=None)


# --- Binding tool calls to the turn they belong to ---------------------------------------------------------------
# Every tool call reaches the server over HTTP. The claude backend sends the turn's token with each call, so a call
# may only touch that turn's lesson and course; opencode shares one connection, so its calls may touch any lesson
# whose turn is running. Either way a tutor talked into it cannot reach another course, and a turn gets a bounded
# number of calls.
# A graph turn reads a finished lesson for its claims, a cards turn makes long or missed review cards short and a
# cleanup turn proposes edits to a version before it is published, an explore turn writes the learner's suggested next
# courses, a recap turn writes the story of a finished course, a contribute turn searches GitHub for open-source work
# that puts a finished course to use, a gist turn writes a finished lesson's gist board; each may call only its own
# tools, and a lesson turn may call none of them.
turns: dict[int | tuple[str, int], dict] = {}  # lesson_id, or (kind, lesson_id) -> {"token", "calls", "lesson_id", "course_id", "kind"}
_ID_ARGUMENTS = ("lesson_id", "course_id", "challenge_id", "quiz_id", "block_id")


def turn_started(lesson: dict, token: str, kind: str = "lesson") -> None:
    turns[lesson["id"] if kind == "lesson" else (kind, lesson["id"])] = {
        "token": token, "calls": 0, "lesson_id": lesson["id"], "course_id": lesson["course_id"], "kind": kind,
    }
    if kind == "graph":
        _searched.discard(lesson["id"])


def close_turn(lesson_id: int) -> None:
    """What the lesson's running turn still writes in chat is dropped."""
    if turn := turns.get(lesson_id):
        turn["closed"] = True


def turn_closed(lesson_id: int) -> bool:
    return bool(turns.get(lesson_id, {}).get("closed"))


def turn_ended(key: int | tuple[str, int]) -> None:
    turns.pop(key, None)


def _targets(arguments: dict) -> list[tuple[int | None, int | None]]:
    """(lesson_id, course_id) for every id the call carries; each must belong to the calling turn."""
    found = []
    if (lesson_id := arguments.get("lesson_id")) is not None:
        lesson = db.lesson(lesson_id)
        found.append((lesson_id, lesson["course_id"] if lesson else None))
    if (course_id := arguments.get("course_id")) is not None:
        found.append((None, course_id))
    found += [_block_target(arguments[name]) for name in ("challenge_id", "quiz_id", "block_id") if arguments.get(name) is not None]
    return found


def _block_target(block_id: int) -> tuple[int | None, int | None]:
    """A block's lesson and course; (-1, None) for a block that does not exist, which no turn owns."""
    block = db.block(block_id)
    lesson = db.lesson(block["lesson_id"]) if block else None
    return (block["lesson_id"], lesson["course_id"]) if block and lesson else (-1, None)


def _token(request_context) -> str | None:
    """The turn token that came with the request, if the backend sends one."""
    try:
        return request_context.request.headers.get(TURN_HEADER) or None
    except (AttributeError, ValueError):
        return None


def _kind(tool: str) -> str:
    return (
        "graph" if tool in GRAPH_TOOLS else "cards" if tool in CARD_TOOLS else "cleanup" if tool in CLEANUP_TOOLS
        else "explore" if tool in EXPLORE_TOOLS else "recap" if tool in RECAP_TOOLS else "contribute" if tool in CONTRIBUTE_TOOLS
        else "lesson"
    )


def _serves(tool: str, kind: str) -> bool:
    """Whether a turn of this kind may call the tool."""
    return _kind(tool) == kind or (kind == "gist" and tool in GIST_TOOLS)


# What the interview and placement prompts use besides the tools every phase shares; lessons and practice see all.
SHARED_TOOLS = (
    "add_animation", "add_block", "add_board", "add_crafted_figure", "add_diagram", "add_figure", "add_plot", "add_widget", "ask",
    "board_help", "craft_help", "extend_board", "find_art", "note_learner", "replace_crafted_figure", "revise_course_map", "view_handwork",
)
PHASE_TOOLS = {
    "interview": (*SHARED_TOOLS, "get_playbook", "list_playbooks", "offer_resources", "rank_mechanisms", "set_course_map", "set_cover", "set_pace", "set_prerequisites", "set_sitting"),
    "placement": (*SHARED_TOOLS, "get_playbook", "grade_quiz", "pose_quiz", "pose_vocab_check", "set_course_map", "set_known", "set_placement"),
}
# The tools that set a course up; the phases after the interview and the placement never see them.
SETUP_TOOLS = (
    "list_playbooks", "offer_resources", "pose_vocab_check", "rank_mechanisms", "set_course_map", "set_cover", "set_known",
    "set_pace", "set_placement", "set_prerequisites", "set_sitting",
)


# A card the learner answers ends the turn, and the tools that go with it in the same reply return nothing the tutor must
# read back: a backend that runs the tool loop itself ends the turn there instead of asking the model again.
POSES = (
    "ask", "end_roleplay", "finish_lesson", "give_hint", "pose_challenge", "pose_comparison", "pose_exercise", "pose_quiz",
    "pose_sort", "pose_speaking", "pose_teachback", "pose_vocab_check", "pose_writing",
)
BESIDE_POSE = ("grade_quiz", "mark_solved", "note_learner", "set_outline", "step_done")
# How a tool's text answer starts when it did not do what it was asked.
REFUSALS = ("error:", "refused:", "rewrite:")


def ends_turn(token: str, results: list[tuple[str, bool]]) -> bool:
    """Whether a reply whose tool calls went (name, ok) ends its turn: it posed a card, every call went through, and the
    lesson waits for the learner. A lesson taken offline or a teacher's course poses many cards in one turn."""
    turn = _turn_of(token)
    lesson = db.lesson(turn["lesson_id"]) if turn and turn["kind"] == "lesson" else None
    names = [name for name, _ in results]
    return (
        bool(lesson) and not keyed(lesson) and any(n in POSES for n in names)
        and all(n in POSES or n in BESIDE_POSE for n in names) and all(ok for _, ok in results)
    )


async def _list_tools(ctx, params) -> ListToolsResult:
    """A turn sees only the tools it may call, so their schemas do not ride along in every request; a caller without a
    turn token (opencode shares one connection) sees them all."""
    tools = await mcp.list_tools()
    turn = _turn_of(token) if (token := _token(ctx)) else None
    if turn is not None:
        allowed = _phase_tools(turn)
        tools = [
            t for t in tools
            if _serves(t.name, turn["kind"]) and (t.name in allowed if allowed is not None else t.name not in SETUP_TOOLS)
        ]
    return ListToolsResult(tools=tools)


def _turn_of(token: str) -> dict | None:
    return next((t for t in turns.values() if t["token"] == token), None)


def _phase_tools(turn: dict) -> tuple[str, ...] | None:
    """The tools a lesson turn's phase is limited to; None for no limit."""
    lesson = db.lesson(turn["lesson_id"]) if turn["kind"] == "lesson" else None
    return PHASE_TOOLS.get(lesson["phase"]) if lesson else None


def calling_turn() -> dict | None:
    """The turn the running tool call was bound to; None outside a call or for an unnamed call with no turn."""
    return _calling.get()


def _owns(turn: dict, target: tuple[int | None, int | None]) -> bool:
    target_lesson, target_course = target
    return target_lesson == turn["lesson_id"] if target_lesson is not None else target_course == turn["course_id"]


def _turn_with_token(token: str, tool: str, targets: list) -> dict:
    turn = _turn_of(token)
    if turn is None:
        raise ToolError("this turn is over; nothing more can be changed")
    if not _serves(tool, turn["kind"]):
        raise ToolError("that tool is not available in this turn")
    if not all(_owns(turn, target) for target in targets):
        raise ToolError("that id belongs to another lesson or course; use the ids of the [state] line")
    return turn


def _turn_without_token(tool: str, targets: list) -> dict | None:
    # Without a token (opencode shares one connection) a call lands on a lesson whose turn is running.
    running = [t for t in turns.values() if _serves(tool, t["kind"]) and all(_owns(t, target) for target in targets)]
    # A gist turn may run beside the lesson's own turn; an unnamed call to a tool both may call is the lesson's.
    running.sort(key=lambda t: t["kind"] != _kind(tool))
    if targets and not running:
        raise ToolError("this lesson has no turn running; use the ids of the [state] line")
    return running[0] if running else None


def _count_call(turn: dict) -> None:
    turn["calls"] += 1
    if turn["calls"] > TOOL_CALLS_PER_TURN:
        raise ToolError(f"over {TOOL_CALLS_PER_TURN} tool calls this turn; end the turn with a short reply")


def _guard(call_tool):
    async def guarded(name: str, arguments: dict, context, convert_result: bool = False):
        targets = _targets(arguments)
        if token := _token(context.request_context):
            turn = _turn_with_token(token, name, targets)
        else:
            turn = _turn_without_token(name, targets)
        if turn is not None:
            _count_call(turn)
        bound = _calling.set(turn)
        try:
            return await call_tool(name, arguments, context, convert_result)
        finally:
            _calling.reset(bound)

    return guarded


# The wrapped method's signature is pinned by the test suite; an mcp upgrade that changes it fails there, not here.
mcp._tool_manager.call_tool = _guard(mcp._tool_manager.call_tool)
mcp._lowlevel_server.add_request_handler("tools/list", PaginatedRequestParams, _list_tools)

# The tools register on mcp by area.
for _area in ('lesson_flow', 'course_plan', 'visuals', 'practice', 'language', 'quizzes', 'lookup', 'side_turns', 'contributions'):
    importlib.import_module(f".tools.{_area}", __package__)
