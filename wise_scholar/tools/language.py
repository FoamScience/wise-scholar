import asyncio
from collections import Counter
from typing import Literal

import simplemma
from pydantic import BaseModel

from .. import challenge, db, lexicon, resources, speech, vocab
from ..tutor import _patch_block, _show, _shuffled, log, mcp


class Gloss(BaseModel):
    word: str
    meaning: str


class Line(BaseModel):
    speaker: str
    text: str


class CastQuestion(BaseModel):
    after_line: int
    question: str
    kind: Literal["choice", "open"]
    options: list[str] = []
    answer_key: str
    explanation: str


# A cast of 5 to 8 minutes at the voices' pace of about 155 words a minute; one Chatterbox line stays short.
CAST_WORDS = (750, 1250)
LINE_CHARS = 300
_renders: set[asyncio.Task] = set()


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


def _reading_problems(check: dict) -> list[str]:
    problems = []
    if check["coverage"] < vocab.COVERAGE:
        problems.append(
            f"only {check['coverage']:.0%} of the words are inside the learner's vocabulary (need {vocab.COVERAGE:.0%}); "
            f"outside it: {', '.join(check['unknown'][:15])}"
        )
    if check["missing_targets"]:
        problems.append(f"targets used fewer than {vocab.REPEATS} times: {', '.join(check['missing_targets'])}")
    return problems


def _record_exposures(lesson: dict, v: dict, check: dict) -> None:
    db.course_lang(lesson["course_id"], v["lang"])
    # Function words need no tracking; count the rest of the ranked words the learner met.
    counts = Counter(l.lower() for l in check["lemmas"] if (vocab.rank(l, v["lang"]) or 0) >= vocab.FUNCTION_WORDS)
    db.add_exposures(lesson["profile_id"], v["lang"], counts, vocab.EXPOSURES_TO_KNOW)


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
        return "rewrite: " + "; ".join(_reading_problems(check)) + ". Keep the glossary for the words you must keep."
    _record_exposures(lesson, v, check)
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


@mcp.tool()
async def pose_writing(
    lesson_id: int, prompt: str, fluency: bool = False, min_words: int = 0, max_words: int = 0, structure: str = "",
    milestone: bool = False,
) -> str:
    """Ask the learner to write in the language being learned.

    The card works like a challenge: each submission is an attempt, your correction prompts go
    through give_hint (with marks on the faulty pieces), and the corrected text goes through
    reveal, which opens after the second attempt or a give-up. fluency: an easy, fast task on
    known language where speed matters and you do not correct details. min_words/max_words: the
    length band for the level, shown with a live word count. structure: the one form the text should
    use, named to the learner (e.g. "a Nebensatz mit weil"). End your turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    data = {**challenge.new(reveal_after=2), "writing": True, "fluency": fluency, "marks": [],
            "words": [min_words, max_words] if max_words else None, "structure": structure, "milestone": milestone}
    block = db.add_block(lesson_id, "challenge", prompt, data)
    _show(lesson, block)
    return f"shown as challenge {block['id']}; end the turn and wait for the learner"


@mcp.tool()
async def offer_resources(course_id: int, lang: str) -> str:
    """Offer the learner open data for the natural language this course teaches: a Wiktionary lexicon and
    sentence pairs with their own language. Call it once, for a course that teaches a natural language. The learner
    allows or refuses each one, seeing its download size; you are not told and need not wait. lang: the taught
    language's code, e.g. 'es' or 'pt-BR'."""
    course = db.course(course_id)
    if not course:
        return f"error: no course with id {course_id}"
    try:
        outcome = await resources.offer(course_id, lang, db.profile(course["profile_id"])["locale"])
    except (LookupError, ValueError):
        return f"error: {lang!r} is not a language code"
    return "; ".join(f"{kind}: {status}" for kind, status in outcome.items())


@mcp.tool()
async def lookup_word(course_id: int, word: str) -> str:
    """Look a word of the course's language up in its Wiktionary lexicon: headword line, part of speech, pronunciation,
    meanings in English, and its forms with their grammatical tags; for an inflected form, also the word it is a form
    of. Check a form, gender, plural or conjugation here before you teach or correct it."""
    folder = resources.course_resource(course_id, "lexicon")
    if not folder or not (folder / lexicon.DB).exists():
        return "the lexicon is not set up for this course; work from what you know"
    found = await asyncio.to_thread(lexicon.lookup, folder, word.strip())
    if not found:
        return f"{word!r} is not in the lexicon"
    return lexicon.answer(found)


@mcp.tool()
async def start_series(course_id: int, title: str, characters: list[str], synopsis: str) -> str:
    """Open the course's extensive-reading series: a serial story in the language being learned.

    characters: the recurring people and places, each as 'Name: one line'. synopsis: the setting and
    the thread of the plot in a few sentences; later episodes build on it. One series per course.
    """
    if not db.course(course_id):
        return f"error: no course with id {course_id}"
    if db.series(course_id):
        return "error: this course already has a series; call add_episode"
    db.start_series(course_id, title, "\n".join(characters), synopsis)
    return "started; now write episode 1 with add_episode"


def _episode_problem(lesson_id: int, text: str, glossary: list[Gloss]) -> str | None:
    if any(b["kind"] == "reading" and (b["data"] or {}).get("story") for b in db.blocks(lesson_id)):
        return "error: this lesson already has its episode"
    words = len(text.split())
    if not 400 <= words <= 800:
        return f"error: {words} words; an episode has 400 to 800"
    if len(glossary) > vocab.STORY_GLOSSARY:
        return f"error: at most {vocab.STORY_GLOSSARY} glossary words in an episode; keep the language easy instead"
    if stray := [g.word for g in glossary if g.word not in text]:
        return f"error: glossary words {stray} do not appear in the text exactly as written"
    return None


@mcp.tool()
async def add_episode(
    lesson_id: int, title: str, text: str, lang: str, recap: str, glossary: list[Gloss] = [], names: list[str] = []
) -> str:
    """Show the next episode of the course's series: 400 to 800 words the learner reads for pleasure.

    The gate is stricter than a lesson reading: 98% of the words inside the learner's vocabulary, at
    most 5 glossary words, no comprehension questions. recap: two sentences on what happened, kept as
    the series memory for the next episode. names: the people and places in it. End your turn after it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    show = db.series(lesson["course_id"])
    if not show:
        return "error: no series yet; call start_series first"
    if problem := _episode_problem(lesson_id, text, glossary):
        return problem
    v = _vocab(lesson, lang)
    known_names = [*names, *show["characters"].split("\n"), *(g.word for g in glossary)]
    known_names = [n.split(":")[0].strip() for n in known_names]
    check = vocab.check_reading(text, v["lang"], v["tier"], v["known"], [], known_names, coverage=vocab.STORY_COVERAGE)
    if not check["ok"]:
        return (
            f"rewrite: only {check['coverage']:.1%} of the words are inside the learner's vocabulary (an episode needs "
            f"{vocab.STORY_COVERAGE:.0%}); outside it: {', '.join(check['unknown'][:20])}. Replace them with easier words."
        )
    _record_exposures(lesson, v, check)
    advance_tier(lesson["profile_id"], v["lang"], v["tier"])
    episode = db.add_episode(lesson["course_id"], recap)
    data = {"title": title, "lang": lang, "glossary": [g.model_dump() for g in glossary], "added": [], "targets": [],
            "known": [], "story": show["title"], "episode": episode}
    _show(lesson, db.add_block(lesson_id, "reading", text, data))
    return f"shown as episode {episode}; coverage {check['coverage']:.1%}"


@mcp.tool()
async def pose_speaking(lesson_id: int, kind: Literal["read", "shadow", "answer"], text: str, lang: str) -> str:
    """Ask the learner to speak in the language being learned. Needs the optional speech setup.

    read: the learner reads text aloud. shadow: the learner hears text spoken and repeats it.
    Both are scored word by word by forced alignment of the recording; you get the weak words and
    comment on them with give_hint (marks on those words, a prompt about the sound, never a spelling
    of it). answer: text is a question the learner hears and answers by speaking; the transcript
    becomes a written attempt and goes through the writing-correction flow. lang: BCP 47 code such as
    de-DE. One or two sentences at a time. End your turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not speech.available():
        return "error: speech is off on this install, so there are no speaking tasks; use pose_writing instead"
    if kind == "answer":
        data = {**challenge.new(reveal_after=2), "writing": True, "spoken": True, "lang": lang, "fluency": False, "marks": []}
        block = db.add_block(lesson_id, "challenge", text, data)
    else:
        data = {**challenge.new(reveal_after=2), "speaking": kind, "lang": lang, "scores": [], "marks": []}
        block = db.add_block(lesson_id, "speaking", text, data)
    _show(lesson, block)
    return f"shown as {block['kind']} {block['id']}; end the turn and wait for the learner"


def _cast_problem(lines: list[Line], speakers: list[str], questions: list[CastQuestion]) -> str | None:
    if len(speakers) != 2:
        return f"error: a cast has exactly two speakers, got {speakers}"
    if long := [i for i, l in enumerate(lines) if len(l.text) > LINE_CHARS]:
        return f"error: lines {long} are over {LINE_CHARS} characters; split them"
    words = sum(len(l.text.split()) for l in lines)
    if not CAST_WORDS[0] <= words <= CAST_WORDS[1]:
        return f"error: {words} words; a 5 to 8 minute cast needs {CAST_WORDS[0]} to {CAST_WORDS[1]}"
    return _cast_questions_problem(len(lines), questions)


def _cast_questions_problem(count: int, questions: list[CastQuestion]) -> str | None:
    for q in questions:
        if not 0 <= q.after_line < count:
            return f"error: after_line {q.after_line} is outside the dialogue"
        if q.kind == "choice" and not (2 <= len(q.options) <= 5 and q.answer_key in q.options):
            return "error: a choice question needs 2 to 5 options, one of them exactly equal to answer_key"
    return None


def _cast_coverage_problem(lesson: dict, lang: str, text: str, names: list[str]) -> str | None:
    v = _vocab(lesson, lang)
    check = vocab.check_reading(text, v["lang"], v["tier"], v["known"], [], names)
    if check["coverage"] < vocab.COVERAGE:
        return (
            f"rewrite: only {check['coverage']:.0%} of the words are inside the learner's vocabulary (need {vocab.COVERAGE:.0%}); "
            f"outside it: {', '.join(check['unknown'][:15])}"
        )
    return None


def _add_cues(lesson: dict, questions: list[CastQuestion], data: dict) -> None:
    for q in sorted(questions, key=lambda q: q.after_line):
        options = _shuffled(q.options) if q.kind == "choice" else []
        card_id = db.add_card(
            lesson["course_id"], lesson["concept_id"], q.question, q.kind, options, q.answer_key, q.explanation,
            scheduled=lesson["phase"] != "placement",
        )
        quiz_block = db.add_block(lesson["id"], "quiz", q.question, {"card_id": card_id, "kind": q.kind, "options": options, "answer": None})
        data["cues"].append({"line": q.after_line, "block_id": quiz_block["id"]})


def _cast_data(lang: str, speakers: list[str], lines: list[Line], glossary: list[Gloss]) -> dict:
    return {
        "lang": lang, "speakers": speakers, "lines": [l.model_dump() for l in lines], "glossary": [g.model_dump() for g in glossary],
        "status": "rendering", "done": 0, "audio": None, "starts": [], "duration": None, "cues": [],
    }


def _start_render(block_id: int) -> None:
    task = asyncio.create_task(_render_cast(block_id))
    _renders.add(task)
    task.add_done_callback(_renders.discard)


async def make_podcast(
    lesson_id: int, title: str, lang: str, lines: list[Line], questions: list[CastQuestion] = [],
    glossary: list[Gloss] = [], names: list[str] = [],
) -> str:
    """Turn a two-voice dialogue you wrote into a 5 to 8 minute audio cast in the lesson area. Experimental.

    lines: the dialogue in order, exactly two speakers, each line under 300 characters, 750 to 1250 words
    in all. Write a recap cast (the two hosts talk through what the lesson taught, with examples) or a
    quiz-cast: pass questions, each placed after a line, roughly every two minutes; the cast pauses there
    and the learner answers with a confidence rating before it goes on. lang: BCP 47 code of the dialogue.
    The server shuffles the options of a choice question, so none may refer to another by position.
    In a language course the dialogue passes the reading gate like add_reading (glossary and names count
    as in scope). The audio renders in the background; end your turn after calling this.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    speakers = list(dict.fromkeys(l.speaker for l in lines))
    if problem := _cast_problem(lines, speakers, questions):
        return problem
    text = "\n".join(l.text for l in lines)
    if stray := [g.word for g in glossary if g.word not in text]:
        return f"error: glossary words {stray} do not appear in the dialogue exactly as written"
    if not speech.available():
        return "error: speech is off on this install, so there are no casts"
    if lesson["lang"] and (problem := _cast_coverage_problem(lesson, lang, text, [*names, *speakers, *(g.word for g in glossary)])):
        return problem
    data = _cast_data(lang, speakers, lines, glossary)
    block = db.add_block(lesson_id, "podcast", title, data)
    _add_cues(lesson, questions, data)
    block = db.set_block_data(block["id"], data)
    _show(lesson, block)
    for cue in data["cues"]:
        _show(lesson, db.block(cue["block_id"]))
    _start_render(block["id"])
    return f"shown as podcast {block['id']}, rendering {len(lines)} lines in the background; end the turn"


if speech.PODCASTS:
    mcp.tool()(make_podcast)


async def _render_cast(block_id: int) -> None:
    data = db.block(block_id)["data"]
    voices = dict(zip(data["speakers"], "ab"))
    try:
        parts = []
        for i, line in enumerate(data["lines"]):
            parts.append(await speech.tts(line["text"], data["lang"], voices[line["speaker"]]))
            if (i + 1) % 5 == 0:
                _patch_block(block_id, {"done": i + 1})
        out = speech.AUDIO / "podcasts" / f"{block_id}.opus"
        res = await speech.concat(parts, out)
        _patch_block(block_id, {
            "status": "ready", "done": len(parts), "audio": f"/api/audio/podcasts/{block_id}.opus",
            "starts": res["starts"], "duration": res["duration"],
        })
    except Exception as e:
        log.warning("cast %s failed: %s", block_id, e)
        _patch_block(block_id, {"status": "failed", "error": str(e)})
