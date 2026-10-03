from collections import Counter
from typing import Literal

import simplemma
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from . import challenge, db, hub, quiz, vocab
from .playbooks import PLAYBOOKS, check_ranking, describe

mcp = MCPServer("scholar")


class Ranked(BaseModel):
    mechanism: str
    rationale: str


class Gloss(BaseModel):
    word: str
    meaning: str


class ExerciseFile(BaseModel):
    path: str
    content: str


class Module(BaseModel):
    title: str
    concepts: list[str]
    known: list[str] = []


def _show(lesson: dict, block: dict, event: str = "block.added") -> None:
    hub.publish(lesson["course_id"], {"type": event, "lesson_id": lesson["id"], "block": block})


def _update_challenge(challenge_id: int, change: dict) -> None:
    block = db.block(challenge_id)
    block = db.set_block_data(challenge_id, {**block["data"], **change})
    _show(db.lesson(block["lesson_id"]), block, "block.updated")


def _open_challenge(challenge_id: int) -> dict | str:
    block = db.block(challenge_id)
    if not block or block["kind"] not in challenge.KINDS:
        return f"error: no challenge or exercise with id {challenge_id}"
    return block["data"]


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
    _show(lesson, db.add_block(lesson_id, kind, markdown))
    return "shown"


@mcp.tool()
async def ask(lesson_id: int, question: str, options: list[str]) -> str:
    """Show the learner one question card with 2 to 5 short answer options.

    The learner can also answer in their own words. This returns at once: end your
    turn after calling it, and the answer arrives as the next turn.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    _show(lesson, db.add_block(lesson_id, "question", question, {"options": options, "answer": None}))
    return "shown; end the turn and wait for the answer"


@mcp.tool()
async def note_learner(course_id: int, fact: str, scope: Literal["learner", "course"]) -> str:
    """Record one fact you learned about the learner, as a full sentence.

    scope learner: true of the person in any course (skills, background, interests).
    scope course: only about this course (goal, time per sitting, chosen theme).
    Recorded facts come back in the [known] lines of every later turn.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
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


@mcp.tool()
async def set_course_map(course_id: int, modules: list[Module]) -> str:
    """Lay out the course as ordered modules, each a list of concept titles, and show it as the course map.

    One concept is what one sitting can cover. The learner opens a concept to start its lesson.
    known lists the concept titles of a module that a placement check showed the learner
    already has; they appear as placed out.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    if db.concepts(course_id):
        return "error: this course already has a map"
    if not any(m.concepts for m in modules):
        return "error: the map has no concepts"
    if stray := [k for m in modules for k in m.known if k not in m.concepts]:
        return f"error: known titles {stray} are not concepts of their module"
    db.set_concepts(course_id, [m.model_dump() for m in modules])
    hub.publish(course_id, {"type": "map.set", "concepts": db.concepts(course_id)})
    return "shown"


@mcp.tool()
async def pose_challenge(lesson_id: int, markdown: str) -> str:
    """Show something the learner must work out themselves: a prediction, a question, a problem.

    The card has an answer box, a hint ladder and a locked solution. Attempts, hint
    requests and give-ups arrive as later turns that name the challenge id. End your
    turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    block = db.add_block(lesson_id, "challenge", markdown, challenge.new())
    _show(lesson, block)
    return f"shown as challenge {block['id']}; end the turn and wait for the learner"


@mcp.tool()
async def pose_exercise(lesson_id: int, markdown: str, files: list[ExerciseFile], run: str) -> str:
    """Show a hands-on exercise: starter files the learner edits in their own editor, and a command that runs them.

    files: paths relative to the course workspace (your working directory), with the starter
    content; put each concept's files in its own subfolder. Existing files are overwritten.
    run: one shell command, executed in the workspace when the learner presses Run.
    The card shows the files as they are on disk, the run output, a hint ladder and a locked
    solution, exactly like a challenge; its id works with give_hint, reveal and mark_solved.
    `[learner attempt]` turns for an exercise carry the current files and the last run output.
    End your turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not files:
        return "error: an exercise needs at least one file"
    workspace = db.workspace(lesson["slug"])
    targets = [(workspace / f.path).resolve() for f in files]
    if outside := [f.path for f, t in zip(files, targets) if not t.is_relative_to(workspace)]:
        return f"error: paths {outside} leave the course workspace"
    for f, target in zip(files, targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content)
    data = {**challenge.new(), "files": [f.path for f in files], "run": run, "last_run": None}
    block = db.add_block(lesson_id, "exercise", markdown, data)
    _show(lesson, block)
    return f"shown as exercise {block['id']}; end the turn and wait for the learner"


@mcp.tool()
async def give_hint(challenge_id: int, hint: str, marks: list[str] = []) -> str:
    """Add the next rung of the hint ladder to a challenge, exercise or writing task.

    marks: for a writing task, the exact pieces of the learner's last attempt that
    contain an error; they are underlined in the learner's text.

    Each hint is the smallest nudge that moves the learner one step: a question or a
    pointer, never the answer or a part of it.
    """
    data = _open_challenge(challenge_id)
    if isinstance(data, str):
        return data
    if problem := challenge.hint_blocker(data):
        return f"refused: {problem}"
    last = data["attempts"][-1] if data["attempts"] else ""
    if stray := [m for m in marks if m not in last]:
        return f"error: marks {stray} are not exact pieces of the learner's last attempt"
    _update_challenge(challenge_id, {"hints": [*data["hints"], hint], "marks": marks})
    return f"shown as hint {len(data['hints']) + 1} of {data['max_hints']}"


def _vocab(lesson: dict, lang: str) -> dict:
    """The learner's vocabulary scope in a language: tier, known lemmas, and the lemmas still to meet."""
    base = lang.split("-")[0].lower()
    tier = db.vocab_tier(lesson["profile_id"], base, vocab.starting_tier(lesson["level"], base))
    known = db.vocab_lemmas(lesson["profile_id"], base)
    return {"lang": base, "tier": tier, "known": known}


def vocab_brief(lesson: dict, lang: str, n: int = 6) -> str:
    """One paragraph for the tutor: where the learner stands and which words to work into the next text."""
    v = _vocab(lesson, lang)
    progress = vocab.tier_progress(v["lang"], v["tier"], db.vocab_lemmas(lesson["profile_id"], v["lang"], ("known",)))
    targets = vocab.next_targets(v["lang"], v["tier"], v["known"], n)
    return (
        f"Vocabulary tier {v['tier']} (the {v['tier'] * vocab.TIER} most common words), "
        f"{progress['known']} of {progress['size']} in this tier known. "
        f"Targets for the next text, each used at least {vocab.REPEATS} times: {', '.join(targets)}. "
        f"Texts must keep {vocab.COVERAGE:.0%} of their words inside the tiers up to {v['tier']}, the learner's known words, these targets and declared names."
    )


@mcp.tool()
async def next_targets(lesson_id: int, lang: str, n: int = 6) -> str:
    """The next vocabulary targets for the learner: frequent words of the current tier they do not know yet.

    lang is the language being learned (de, en, ...). Work each target into the next reading at least
    three times and pass them as targets to add_reading.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    return vocab_brief(lesson, lang, n)


@mcp.tool()
async def add_reading(
    lesson_id: int, title: str, text: str, lang: str, glossary: list[Gloss], targets: list[str] = [], names: list[str] = []
) -> str:
    """Show a reading text in the language being learned.

    text: plain text, paragraphs separated by blank lines. lang: its BCP 47 code, such as de-DE,
    used to read it aloud. glossary: the words or phrases above the learner's level, each exactly
    as it appears in the text, with a short meaning in the learner's own language. targets: the
    vocabulary targets (from next_targets) the text works in, each at least three times. names:
    people and places named in the text. The text is refused when too many of its words lie outside
    the learner's vocabulary; the refusal lists them so you can rewrite.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if stray := [g.word for g in glossary if g.word not in text]:
        return f"error: glossary words {stray} do not appear in the text exactly as written"
    if len(glossary) > vocab.MAX_GLOSSARY:
        return f"error: at most {vocab.MAX_GLOSSARY} glossary words; a text that needs more is above the learner's level"
    v = _vocab(lesson, lang)
    # Glossed words are the learner's few words above level; they count as in scope, like names.
    check = vocab.check_reading(text, v["lang"], v["tier"], v["known"], targets, [*names, *(g.word for g in glossary)])
    if not check["ok"]:
        problems = []
        if check["coverage"] < vocab.COVERAGE:
            problems.append(
                f"only {check['coverage']:.0%} of the words are inside the learner's vocabulary (need {vocab.COVERAGE:.0%}); "
                f"outside it: {', '.join(check['unknown'][:15])}"
            )
        if check["missing_targets"]:
            problems.append(f"targets used fewer than {vocab.REPEATS} times: {', '.join(check['missing_targets'])}")
        return "rewrite: " + "; ".join(problems) + ". Keep the glossary for the words you must keep."
    db.course_lang(lesson["course_id"], v["lang"])
    # Function words need no tracking; count the rest of the ranked words the learner met.
    counts = Counter(l.lower() for l in check["lemmas"] if (vocab.rank(l, v["lang"]) or 0) >= vocab.FUNCTION_WORDS)
    db.add_exposures(lesson["profile_id"], v["lang"], counts, vocab.EXPOSURES_TO_KNOW)
    for target in targets:
        db.set_vocab(lesson["profile_id"], v["lang"], simplemma.lemmatize(target, lang=v["lang"]), "learning", "target")
    advance_tier(lesson["profile_id"], v["lang"], v["tier"])
    data = {"title": title, "lang": lang, "glossary": [g.model_dump() for g in glossary], "added": [],
            "targets": targets, "known": []}
    _show(lesson, db.add_block(lesson_id, "reading", text, data))
    return f"shown; coverage {check['coverage']:.0%}"


def advance_tier(profile_id: int, lang: str, tier: int) -> None:
    if tier < vocab.max_tier(lang) and vocab.tier_progress(lang, tier, db.vocab_lemmas(profile_id, lang, ("known",)))["complete"]:
        db.set_vocab_tier(profile_id, lang, tier + 1)


@mcp.tool()
async def pose_vocab_check(lesson_id: int, lang: str) -> str:
    """Measure the learner's vocabulary tier with a yes/no word check the server runs on its own.

    lang: the language being learned (de, en, ...). The card samples words tier by tier until the
    learner's tier is bracketed; you get an [event] with the result and a few claimed words to verify
    in context. End your turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    base = lang.split("-")[0].lower()
    db.course_lang(lesson["course_id"], base)
    data = {"lang": base, "rounds": [], "current": {"tier": 1, "words": vocab.sample_tier(base, 1)}, "tier": None}
    block = db.add_block(lesson_id, "vocab", "Which of these words do you know?", data)
    _show(lesson, block)
    return f"shown as vocabulary check {block['id']}; end the turn and wait for the event"


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


@mcp.tool()
async def pose_writing(lesson_id: int, prompt: str, fluency: bool = False) -> str:
    """Ask the learner to write in the language being learned.

    The card works like a challenge: each submission is an attempt, your correction prompts go
    through give_hint (with marks on the faulty pieces), and the corrected text goes through
    reveal, which opens after the second attempt or a give-up. fluency: an easy, fast task on
    known language where speed matters and you do not correct details. End your turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    data = {**challenge.new(reveal_after=2), "writing": True, "fluency": fluency, "marks": []}
    block = db.add_block(lesson_id, "challenge", prompt, data)
    _show(lesson, block)
    return f"shown as challenge {block['id']}; end the turn and wait for the learner"


@mcp.tool()
async def reveal(challenge_id: int, solution: str) -> str:
    """Show the full solution of a challenge. The server refuses while the solution is locked."""
    data = _open_challenge(challenge_id)
    if isinstance(data, str):
        return data
    if problem := challenge.reveal_blocker(data):
        return f"refused: {problem}"
    _update_challenge(challenge_id, {"solution": solution})
    return "shown"


@mcp.tool()
async def pose_quiz(
    lesson_id: int,
    question: str,
    kind: Literal["choice", "open"],
    options: list[str],
    answer_key: str,
    explanation: str,
    lemma: str = "",
) -> str:
    """Show a quick check that the learner answers together with how sure they are.

    choice: 2 to 5 options, and answer_key is exactly the right option; the server grades it.
    open: options is empty and answer_key is the model answer; you grade it with grade_quiz
    when the answer arrives. The learner sees answer_key and explanation only after grading.
    The question comes back later in spaced reviews, so it must make sense on its own.
    lemma: in a language course, the vocabulary word the question tests; the grade sets its ledger state.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if kind == "choice" and not (2 <= len(options) <= 5 and answer_key in options):
        return "error: a choice quiz needs 2 to 5 options, one of them exactly equal to answer_key"
    if lemma and not lesson["lang"]:
        return "error: lemma needs a language course; pose_vocab_check or add_reading sets the language"
    if kind == "open":
        options = []
    card_id = db.add_card(
        lesson["course_id"], lesson["concept_id"], question, kind, options, answer_key, explanation,
        scheduled=lesson["phase"] != "placement",
    )
    if lemma:
        lemma = simplemma.lemmatize(lemma, lang=lesson["lang"]).lower()
        db.conn.execute("UPDATE cards SET lemma = ?, lang = ? WHERE id = ?", (lemma, lesson["lang"], card_id))
    block = db.add_block(lesson_id, "quiz", question, {"card_id": card_id, "kind": kind, "options": options, "answer": None})
    _show(lesson, block)
    return f"shown as quiz {block['id']}; end the turn and wait for the answer"


@mcp.tool()
async def grade_quiz(quiz_id: int, correct: bool, feedback: str) -> str:
    """Grade the learner's answer to an open quiz. Judge the substance against the model answer, not the wording."""
    block = db.block(quiz_id)
    if not block or block["kind"] != "quiz":
        return f"error: no quiz with id {quiz_id}"
    data = block["data"]
    if data["answer"] is None:
        return "refused: the learner has not answered yet"
    if data.get("correct") is not None:
        return "refused: this quiz is already graded"
    result = quiz.grade(data["answer_id"], correct)
    block = db.set_block_data(quiz_id, {**data, **result, "feedback": feedback})
    lesson = db.lesson(block["lesson_id"])
    _show(lesson, block, "block.updated")
    reteach = result["confident_miss"] and lesson["phase"] != "placement"
    return "graded; a confident miss: re-teach it now" if reteach else "graded"


@mcp.tool()
async def set_placement(course_id: int, level: str, summary: str) -> str:
    """Record the result of the placement check.

    level: a short label of where the learner starts. For a natural language use the
    CEFR level (A1, A2, B1, B2, C1, C2). summary: two or three sentences to the learner
    on what the check showed they have and what it showed they lack.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    db.conn.execute("UPDATE courses SET level = ?, placement = ? WHERE id = ?", (level, summary, course_id))
    hub.publish(course_id, {"type": "placement.set", "level": level, "placement": summary})
    return "recorded"


@mcp.tool()
async def mark_solved(challenge_id: int) -> str:
    """Mark a challenge as solved after the learner's own attempt was right."""
    data = _open_challenge(challenge_id)
    if isinstance(data, str):
        return data
    if not data["attempts"]:
        return "refused: the learner has not submitted an attempt on the card"
    _update_challenge(challenge_id, {"solved": True})
    return "marked"
