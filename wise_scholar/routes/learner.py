import asyncio
import sqlite3
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

from .. import app as core
from .. import book, crafted, db, history, hub, quiz, review, sandbox, settings, speech, tutor
from ..tools import language as language_tools, practice as practice_tools, side_turns as side_tools
from ..backends import AGENT
from ..app import LOCALE_NAMES, SITTING_GAP, SelfGrade, _due, _hostname, _lesson, _lesson_view, _map_outline, _now, _profile, _untrusted, _warmed, app, log


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=60)


Locale = Literal["en", "fr", "ar"]


class NewProfile(Name):
    locale: Locale = "en"


class ProfileLocale(BaseModel):
    locale: Locale


Mode = Literal["learner", "teacher"]


class ProfileMode(BaseModel):
    mode: Mode


class ProfileSketch(BaseModel):
    sketch: bool


class SettingChanges(BaseModel):
    values: dict[str, str | None]


class ReviewAnswer(BaseModel):
    """A choice picked, or nothing for an open card whose answer the learner shows and then grades themselves."""
    answer: str = Field(default="", max_length=8000)


class ErrorPatch(BaseModel):
    note: str | None = None
    pinned: bool | None = None
    resolved: bool | None = None


PRACTICE_TASK_CHARS = 600
PRACTICE_TASKS = (4, 6)


def _practice_tasks(concept_id: int) -> list[str]:
    """The solved tasks of the units a practice unit covers, not yet varied, as lines for the tutor."""
    lines = []
    scope = db.practice_scope(concept_id)
    done = practice_tools.varied(scope[0]["course_id"]) if scope else set()
    for unit in scope:
        blocks = [b for r in db.rows("SELECT id FROM lessons WHERE concept_id = ? ORDER BY id", unit["id"]) for b in db.blocks(r["id"])]
        lines += [
            f"- {unit['title']}, task {b['id']}: {_untrusted(b['markdown'][:PRACTICE_TASK_CHARS])}"
            for b in blocks
            if practice_tools.variable(b) and b["id"] not in done
        ]
    return lines


def _practice_size(tasks: list[str]) -> int:
    """How many tasks the practice poses: one per solved task, within PRACTICE_TASKS; the fewest when none was solved."""
    return min(max(len(tasks), PRACTICE_TASKS[0]), PRACTICE_TASKS[1])


def _practice_brief(tasks: list[str]) -> str:
    size = f"Pose exactly {_practice_size(tasks)} tasks: the learner's cards are numbered against that count."
    if not tasks:
        return f"No task of the units before this one was solved: pose fresh tasks on their concepts instead, without variant_of. {size}"
    pick = " Pick them from the list below." if len(tasks) > _practice_size(tasks) else ""
    return (
        f"{size}{pick}\nTasks the learner solved in the units since the last practice; pose a variant of each (new numbers or a new "
        "situation, same idea), mixed across units, with variant_of set to the task id:\n" + "\n".join(tasks)
    )


NEEDED_CLAIMS = 10
BRIDGES = 5
PRACTICE_CLAIMS = 10
STATE_ORDER = {"shaky": 0, "fading": 1, "held": 2, "unseen": 3}


def _claim_line(claim: dict, state: str) -> str:
    return f"- [{state}] {_untrusted(claim['text'])}"


def _claims_brief(lesson: dict) -> str:
    """What the learner's graph says about the units this one builds on, shaky first, and claims from their other
    courses that may bridge to it."""
    states = db.claim_states(lesson["profile_id"], _now())
    needed = db.needs(lesson["course_id"]).get(lesson["concept_id"], [])
    held = sorted(
        (c for c in db.unit_claims(needed) if c["id"] in states), key=lambda c: (STATE_ORDER[states[c["id"]]], c["id"])
    )[:NEEDED_CLAIMS]
    lines = []
    if held:
        lines.append("Claims from the units this one builds on, with where the learner stands on each (shaky first):")
        lines += [_claim_line(c, states[c["id"]]) for c in held]
    bridges = db.bridges(lesson["profile_id"], lesson["course_id"], lesson["concept"], BRIDGES)
    if bridges:
        lines.append("Claims from the learner's other courses that may bridge to this unit; build on the held ones, and warn where one looks alike but differs:")
        lines += [
            f"{_claim_line(c, states.get(c['id'], 'unseen'))} (from {', '.join(c['courses'])})"
            + (f"; looks like but differs from: {'; '.join(c['contrasts'])}" if c["contrasts"] else "")
            for c in bridges
        ]
    return "\n" + "\n".join(lines) if lines else ""


def _practice_claims(concept_id: int, profile_id: int) -> str:
    """The shaky and fading claims of the units a practice unit covers."""
    states = db.claim_states(profile_id, _now())
    weak = sorted(
        (c for c in db.unit_claims([u["id"] for u in db.practice_scope(concept_id)]) if states.get(c["id"]) in ("shaky", "fading")),
        key=lambda c: (STATE_ORDER[states[c["id"]]], c["id"]),
    )[:PRACTICE_CLAIMS]
    if not weak:
        return ""
    return "\nClaims of these units the learner is shaky on or due to review; aim tasks at them first:\n" + "\n".join(
        _claim_line(c, states[c["id"]]) for c in weak
    )


@app.get("/api/meta")
def meta() -> dict:
    return {"agent": AGENT, "speech": speech.available(), "pdf": book.available(), "commands": sandbox.commands(), "crafted": crafted.available()}


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _from_this_machine(request: Request) -> bool:
    """A request made on this machine to its loopback address. One a local proxy forwards names the proxied host or
    carries a forwarding header, so it does not count."""
    forwarded = any(h in request.headers for h in ("forwarded", "x-forwarded-for", "x-real-ip"))
    client = request.client.host if request.client else ""
    return not forwarded and client in LOOPBACK and _hostname(request.headers.get("host", "")) in LOOPBACK


@app.get("/api/settings")
def get_settings(request: Request) -> dict:
    return {"settings": settings.view(), "editable": _from_this_machine(request), "restart": settings.restarter is not None}


@app.post("/api/settings")
def save_settings(body: SettingChanges, request: Request) -> dict:
    if not _from_this_machine(request):
        raise HTTPException(403, "settings can be changed only from this machine, at 127.0.0.1 or localhost")
    for name, value in body.values.items():
        if problem := settings.check(name, value):
            raise HTTPException(422, problem)
    settings.write(body.values)
    log.info("settings saved to .env: %s", ", ".join(sorted(body.values)))
    return get_settings(request)


@app.post("/api/settings/restart", status_code=202)
async def restart_server(request: Request) -> None:
    if not _from_this_machine(request):
        raise HTTPException(403, "settings can be changed only from this machine, at 127.0.0.1 or localhost")
    if settings.restarter is None:
        raise HTTPException(409, "this server cannot restart itself; stop it and start it again")
    log.warning("restarting at the owner's request")
    asyncio.get_running_loop().call_later(0.5, settings.restarter)


def _save_profile(sql: str, *args) -> int:
    try:
        return db.conn.execute(sql, args).lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "a profile with that name already exists") from None


@app.get("/api/profiles")
def list_profiles() -> list[dict]:
    return db.profiles()


@app.post("/api/profiles")
def create_profile(body: NewProfile) -> dict:
    return db.profile(_save_profile("INSERT INTO profiles (name, locale) VALUES (?, ?)", body.name.strip(), body.locale))


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int) -> dict:
    return {**_profile(profile_id), "facts": db.learner_facts(profile_id)}


@app.post("/api/profiles/{profile_id}")
def rename_profile(profile_id: int, body: Name) -> dict:
    _profile(profile_id)
    _save_profile("UPDATE profiles SET name = ? WHERE id = ?", body.name.strip(), profile_id)
    return db.profile(profile_id)


@app.post("/api/profiles/{profile_id}/mode")
def set_mode(profile_id: int, body: ProfileMode) -> dict:
    """Learner or teacher: a teacher prepares courses for a class instead of being taught."""
    _profile(profile_id)
    db.conn.execute("UPDATE profiles SET mode = ? WHERE id = ?", (body.mode, profile_id))
    return db.profile(profile_id)


@app.post("/api/profiles/{profile_id}/sketch")
def set_sketch(profile_id: int, body: ProfileSketch) -> dict:
    """Whether the tutor's own figures are shown with a hand-drawn stroke; a display choice, the drawings stay as they are."""
    _profile(profile_id)
    db.conn.execute("UPDATE profiles SET sketch = ? WHERE id = ?", (int(body.sketch), profile_id))
    return db.profile(profile_id)


@app.post("/api/profiles/{profile_id}/locale")
def set_profile_locale(profile_id: int, body: ProfileLocale) -> dict:
    _profile(profile_id)
    # suggestions are written in the profile's language, so a new one calls for new ones
    db.conn.execute("UPDATE profiles SET locale = ?, suggested_courses = NULL WHERE id = ?", (body.locale, profile_id))
    return db.profile(profile_id)


@app.post("/api/facts/{fact_id}/forget", status_code=204)
def forget_fact(fact_id: int) -> None:
    db.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))


# --- Suggested next courses: written from the learner's courses and claims, kept until enough of those changed -----
SUGGEST_AFTER_LESSONS = 3
SUGGEST_REFILL_BELOW = 3
SUGGEST_CLAIMS = 200
SUGGEST_NOT_WANTED = 30
_suggesting: dict[int, asyncio.Task] = {}
_suggest_failed: set[int] = set()  # tried in this process and failed: only the learner's asking tries again before a restart


def _suggestions_due(profile: dict) -> bool:
    courses, lessons = db.suggestion_basis(profile["id"])
    if not courses or profile["mode"] == "teacher":
        return False
    return (
        courses != profile["suggested_courses"]
        or lessons - (profile["suggested_lessons"] or 0) >= SUGGEST_AFTER_LESSONS
        or len(db.suggestions(profile["id"])) < SUGGEST_REFILL_BELOW
    )


def _explore_prompt(profile: dict, host: int, retire: bool) -> str:
    lines = [
        f"[state] course_id={host}",
        f"[language] Write titles and pitches in {LOCALE_NAMES[profile['locale']]}.",
    ]
    for c in db.rows("SELECT id, topic, level, details FROM courses WHERE profile_id = ? AND mode = 'learner' ORDER BY id", profile["id"]):
        units = db.concept_view(c["id"])
        if not units:
            continue
        lines.append(f"[course] {c['topic']} | level at the start: {c['level'] or 'unknown'} | wanted: {_untrusted(c['details'] or '') or 'not said'}")
        lines.append("[units] " + "; ".join(f"{u['title']}: " + ("not started" if u["mastery"] is None else f"{u['mastery']:.0%}") for u in units))
    states = db.claim_states(profile["id"], _now())
    claims = db.rows("SELECT id, text FROM claims WHERE profile_id = ? AND wrong = 0 ORDER BY id DESC LIMIT ?", profile["id"], SUGGEST_CLAIMS)
    kept = {c["id"] for c in claims}
    lines += [f"[claim {c['id']}, {states[c['id']]}] {_untrusted(c['text'])}" for c in reversed(claims)]
    lines += [
        f"[link] {e['from_id']} {e['kind']} {e['to_id']}"
        for e in db.rows("SELECT e.from_id, e.to_id, e.kind FROM claim_edges e JOIN claims c ON c.id = e.from_id WHERE c.profile_id = ?", profile["id"])
        if e["from_id"] in kept and e["to_id"] in kept
    ]
    refused = db.suggestions(profile["id"], "dismissed")[-SUGGEST_NOT_WANTED:]
    lines += [f"[not wanted] {s['title']}" for s in refused + (db.suggestions(profile["id"]) if retire else [])]
    return "\n".join(lines)


async def _suggest(profile: dict, retire: bool) -> None:
    profile_id = profile["id"]
    courses, lessons = db.suggestion_basis(profile_id)
    # the turn runs on, and its cost counts to, the learner's newest mapped course
    host = db.row(
        "SELECT c.id FROM courses c WHERE c.profile_id = ? AND c.mode = 'learner' AND EXISTS (SELECT 1 FROM concepts k WHERE k.course_id = c.id) ORDER BY c.id DESC LIMIT 1",
        profile_id,
    )["id"]
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ? ORDER BY id LIMIT 1", host)["id"])
    topics = [r["topic"] for r in db.rows("SELECT topic FROM courses WHERE profile_id = ?", profile_id)]
    job = {"profile_id": profile_id, "topics": topics, "retire": retire, "done": False}
    side_tools.suggestion_jobs[host] = job
    try:
        prompt = await asyncio.to_thread(_explore_prompt, profile, host, retire)
        ok = await core._background_turn(lesson, prompt, "explore", "suggested courses")
    finally:
        side_tools.suggestion_jobs.pop(host, None)
    if not ok or not job["done"]:
        _suggest_failed.add(profile_id)
        return
    db.conn.execute("UPDATE profiles SET suggested_courses = ?, suggested_lessons = ? WHERE id = ?", (courses, lessons, profile_id))


def _suggestions_state(profile_id: int) -> dict:
    return {"suggestions": db.suggestions(profile_id), "running": profile_id in _suggesting, "failed": profile_id in _suggest_failed}


def _start_suggesting(profile: dict, retire: bool = False) -> None:
    profile_id = profile["id"]

    async def run() -> None:
        try:
            await _suggest(profile, retire)
        except Exception:
            log.exception("suggestions of profile %s", profile_id)
            _suggest_failed.add(profile_id)
        finally:
            _suggesting.pop(profile_id, None)

    _suggesting[profile_id] = asyncio.create_task(run())


class SuggestionAsk(BaseModel):
    profile_id: int
    others: bool = False


@app.get("/api/suggestions")
def list_suggestions(profile: int) -> dict:
    _profile(profile)
    return _suggestions_state(profile)


@app.post("/api/suggestions")
async def ask_suggestions(body: SuggestionAsk) -> dict:
    """Pages call this as they open: the server starts a turn only when suggestions are due. others: the learner asked for new ones."""
    profile = _profile(body.profile_id)
    if body.profile_id not in _suggesting:
        if body.others and profile["mode"] != "teacher" and db.suggestion_basis(body.profile_id)[0]:
            _suggest_failed.discard(body.profile_id)
            _start_suggesting(profile, retire=True)
        elif body.profile_id not in _suggest_failed and _suggestions_due(profile):
            _start_suggesting(profile)
    return _suggestions_state(body.profile_id)


def _open_suggestion(suggestion_id: int) -> dict:
    found = db.row("SELECT * FROM suggestions WHERE id = ? AND status = 'open'", suggestion_id)
    if not found:
        raise HTTPException(409, "this suggestion is no longer on offer")
    return found


@app.post("/api/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: int) -> dict:
    found = _open_suggestion(suggestion_id)
    db.conn.execute("UPDATE suggestions SET status = 'dismissed' WHERE id = ?", (suggestion_id,))
    return await ask_suggestions(SuggestionAsk(profile_id=found["profile_id"]))


@app.post("/api/suggestions/{suggestion_id}/start")
async def start_suggestion(suggestion_id: int) -> dict:
    found = _open_suggestion(suggestion_id)
    db.conn.execute("UPDATE suggestions SET status = 'taken' WHERE id = ?", (suggestion_id,))
    return db.create_course(found["title"], found["profile_id"])


def _notebook_brief(profile_id: int, course_id: int) -> str:
    """The open entries of the learner's error notebook, with the beliefs behind them, for a lesson's first turn."""
    open_errors = db.errors(profile_id, course_id, open_only=True, limit=5)
    if not open_errors:
        return ""
    return "\nOpen entries in the learner's error notebook (revisit in new material, do not repeat the item): " + "; ".join(
        f"said {e['said'][:80]!r} for {e['prompt'][:80]!r}, right: {e['correct'][:80]!r}"
        + (f", from the belief {e['misconception'][:120]!r}" if e["misconception"] else "")
        + (f" (learner's note: {e['note'][:80]})" if e["note"] else "")
        for e in open_errors
    )


def _leveled_brief(lesson: dict, course_id: int) -> str:
    counts = db.strand_counts(course_id)
    strands = "\nActivities per strand in the last 7 days: " + ", ".join(f"{k} {v}" for k, v in counts.items())
    strands += "\nSpeaking tasks: " + ("available" if speech.available() else "off on this install, use writing instead")
    if lesson["lang"]:
        strands += "\n" + language_tools.vocab_brief(lesson, lesson["lang"])
    return strands


def _strands_brief(lesson: dict, course_id: int) -> str:
    strands = _leveled_brief(lesson, course_id) if lesson["mechanism"] == "leveled-course" else ""
    if speech.PODCASTS and speech.available():
        strands += "\nCasts (experimental): make_podcast is available when a recap or quiz-cast would serve this lesson"
    strands += tutor.capstone_brief(lesson)
    if ready := [f for f in db.sources(course_id) if f["status"] == "ready"]:
        strands += "\nThe learner's own sources (search_sources, then read_source one section at a time): " + ", ".join(
            f"{f['name']} ({f['sections']} sections)" for f in ready
        )
    strands += _notebook_brief(lesson["profile_id"], course_id)
    return strands


def _earlier_brief(course_id: int, lesson_id: int) -> str:
    earlier = history.digest([
        _lesson_view(row["id"])
        for row in db.rows(
            "SELECT id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL AND id != ? ORDER BY id",
            course_id, lesson_id,
        )
    ])
    if earlier:
        earlier = f"\nEarlier lessons, with what the learner did in each:\n{earlier}"
    return earlier


@app.post("/api/concepts/{concept_id}/lesson")
async def open_concept(concept_id: int) -> dict:
    concept = db.row("SELECT * FROM concepts WHERE id = ?", concept_id)
    if not concept:
        raise HTTPException(404, "no such concept")
    existing = db.row("SELECT id FROM lessons WHERE concept_id = ?", concept_id)
    if existing:
        return _lesson_view(existing["id"])
    practice = concept["kind"] == "practice"
    tasks = _practice_tasks(concept_id) if practice else []
    # a practice has no outline to estimate its cards: its tasks are fixed now, and the closing summary is one more
    cards = _practice_size(tasks) + 1 if practice else None
    lesson_id = db.create_lesson(concept["course_id"], concept["title"], "practice" if practice else "lesson", concept_id, cards=cards)
    view = _lesson_view(lesson_id)
    hub.publish(concept["course_id"], {"type": "lesson.created", "lesson": view})
    outline = _map_outline(concept["course_id"], concept_id)
    lesson = _lesson(lesson_id)
    if practice:
        core._start_turn(lesson, f"[event] The practice begins. Course map:\n{outline}\n{_practice_brief(tasks)}{_practice_claims(concept_id, lesson['profile_id'])}")
        return view
    strands = _strands_brief(lesson, concept["course_id"])
    earlier = _earlier_brief(concept["course_id"], lesson_id)
    core._start_turn(lesson, f"[event] The lesson begins. Course map:\n{outline}{strands}{earlier}{_claims_brief(lesson)}")
    return view


@app.get("/api/errors")
def list_errors(profile: int) -> list[dict]:
    return db.errors(profile)


@app.get("/api/claims")
def list_claims(profile: int) -> dict:
    return db.graph(profile, _now())


class ClaimPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=side_tools.CLAIM_CHARS)
    wrong: bool | None = None


@app.post("/api/claims/{claim_id}")
def patch_claim(claim_id: int, body: ClaimPatch) -> dict:
    """Reword a claim, or mark it wrong: it leaves the graph and the extractor never records it again."""
    claim = db.claim(claim_id)
    if not claim:
        raise HTTPException(404, "no such claim")
    if body.text is not None and not body.text.strip():
        raise HTTPException(422, "a claim needs words")
    if body.text is not None and (same := db.same_claim(claim["profile_id"], body.text)) and same["id"] != claim_id:
        raise HTTPException(409, "another claim says this already; merge the two instead")
    db.update_claim(claim_id, body.text, body.wrong)
    return db.claim(claim_id)


class ClaimMerge(BaseModel):
    into: int


@app.post("/api/claims/{claim_id}/merge")
def merge_claim(claim_id: int, body: ClaimMerge) -> dict:
    claim, into = db.claim(claim_id), db.claim(body.into)
    if not claim or not into or claim["profile_id"] != into["profile_id"] or claim_id == body.into:
        raise HTTPException(404, "pick two different claims of the same learner")
    db.merge_claims(claim_id, body.into)
    return db.graph(into["profile_id"], _now())


@app.get("/api/usage")
def list_usage(profile: int) -> list[dict]:
    _profile(profile)
    return db.usage(profile)


@app.get("/api/commands")
def list_commands(profile: int) -> list[dict]:
    return db.commands(profile)


@app.post("/api/errors/{error_id}")
def patch_error(error_id: int, body: ErrorPatch) -> dict:
    entry = db.update_error(error_id, body.note, body.pinned, body.resolved)
    if not entry:
        raise HTTPException(404, "no such entry")
    return entry


@app.get("/api/reviews")
def reviews(profile: int, warmup: bool = False) -> list[dict]:
    """The due cards, mixed across courses; the review page stops when its time box runs out. A long card waits until
    it is made short."""
    if warmup:
        _warmed[profile] = datetime.now(timezone.utc)
    return [quiz.public(c) for c in review.interleave(_due(profile))]


# the review page's time box; the browser keeps it
REVIEW_BOX_MINUTES = 3


# ponytail: a flat half minute per review; fit it to the answer timestamps if the plan is always off.
REVIEW_MINUTES = 0.5


def _today_units(profile: int) -> list[dict]:
    units = []
    for course in db.rows("SELECT id, topic, started FROM courses WHERE profile_id = ? AND archived = 0 ORDER BY id", profile):
        concepts = db.concept_view(course["id"])
        pending = next((c for c in concepts if not c["known"] and (c["mastery"] or 0) < 2 / 3), None)
        if pending:
            units.append({"course_id": course["id"], "topic": course["topic"], "concept_id": pending["id"], "title": pending["title"]})
        elif not concepts:
            title = "Finish the interview" if course["started"] else "Start the interview"
            units.append({"course_id": course["id"], "topic": course["topic"], "concept_id": None, "title": title, "started": bool(course["started"])})
    return units


def _today_extras(profile: int) -> list[dict]:
    extras = []
    for course in db.rows("SELECT id, topic, lang FROM courses WHERE profile_id = ? AND archived = 0 AND mechanism = 'leveled-course'", profile):
        counts = db.strand_counts(course["id"])
        lowest = min(counts, key=counts.get)
        if lowest == "input" and course["lang"]:
            extras.append({"course_id": course["id"], "topic": course["topic"], "kind": "episode"})
        elif lowest == "output":
            extras.append({"course_id": course["id"], "topic": course["topic"], "kind": "writing"})
    return extras


@app.get("/api/today")
def today(profile: int) -> dict:
    """What a sitting holds: a warm-up of due reviews, then the next unit of each active course, and a ready cast."""
    due = len(_due(profile))
    units = _today_units(profile)
    extras = _today_extras(profile)
    cast = db.row(
        "SELECT b.id, b.lesson_id, b.markdown AS title, l.course_id FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
        "JOIN courses c ON c.id = l.course_id WHERE c.profile_id = ? AND c.archived = 0 AND b.kind = 'podcast' "
        "AND json_extract(b.data, '$.status') = 'ready' ORDER BY b.id DESC LIMIT 1",
        profile,
    )
    open_errors = len(db.errors(profile, open_only=True))
    # the sitting opens with a warm-up of the cards that fit the review page's time box; the rest wait for later
    warmup = min(due, round(REVIEW_BOX_MINUTES / REVIEW_MINUTES))
    return {"due": due, "warmup": warmup, "review_minutes": round(warmup * REVIEW_MINUTES), "units": units, "cast": cast, "errors": open_errors, "extras": extras}


# A review states no confidence: it counts as a plain recall for the schedule, below a confident miss, and stays out
# of calibration.
REVIEW_CONFIDENCE = 0.6


@app.post("/api/cards/{card_id}/review")
def review_card(card_id: int, body: ReviewAnswer) -> dict:
    card = db.card(card_id)
    if not card or card["retired"]:
        raise HTTPException(404, "no such card")
    answer_id = quiz.submit(card, body.answer, REVIEW_CONFIDENCE, stated=False)
    correct = quiz.auto_correct(card, body.answer)
    if correct is None:
        # ponytail: open answers are self-graded in reviews; route them to a tutor turn if self-grading proves too lenient
        return {"answer_id": answer_id, "answer_key": card["answer_key"], "explanation": card["explanation"]}
    return {"answer_id": answer_id, **_graded_review(card, answer_id, correct)}


def _graded_review(card: dict, answer_id: int, correct: bool) -> dict:
    """A review miss breaks the card into parts, unless it is a part made from a miss already, or a vocabulary card."""
    result = quiz.grade(answer_id, correct)
    if not correct and card["origin"] != "miss" and not card["vocab"] and not card["lemma"]:
        core._queue_cards(("miss", card["id"]))
    return result


@app.post("/api/answers/{answer_id}/grade")
def self_grade(answer_id: int, body: SelfGrade) -> dict:
    answer = db.row("SELECT card_id, correct, stated FROM answers WHERE id = ?", answer_id)
    if not answer:
        raise HTTPException(404, "no such answer")
    if answer["correct"] is not None:
        raise HTTPException(409, "already graded")
    if answer["stated"]:
        return quiz.grade(answer_id, body.correct)
    return _graded_review(db.card(answer["card_id"]), answer_id, body.correct)


@app.get("/api/sitting")
def sitting(profile: int) -> dict:
    """The learner's latest sitting, the graded answers back to the last gap of SITTING_GAP or more: how sure they
    said they were against how often they were right, and the confident misses to look at again. At the start of a
    sitting, before any answer, that is the sitting before."""
    answers = db.graded_answers(profile)
    if not answers:
        return {"answers": 0}
    times = [datetime.fromisoformat(a["created"]).replace(tzinfo=timezone.utc) for a in answers]
    first = len(answers) - 1
    while first > 0 and times[first] - times[first - 1] < SITTING_GAP:
        first -= 1
    group = answers[first:]
    return {
        "answers": len(group),
        "sure": sum(a["confidence"] for a in group) / len(group),
        "right": sum(a["correct"] for a in group) / len(group),
        "misses": [a["question"] for a in group if review.is_confident_miss(bool(a["correct"]), a["confidence"])],
        "ended": group[-1]["created"],
        # still going: the last answer is within the gap; else it is a sitting already over
        "current": datetime.now(timezone.utc) - times[-1] < SITTING_GAP,
    }


@app.get("/api/calibration")
def calibration(profile: int) -> dict:
    return review.calibration([(a["confidence"], bool(a["correct"])) for a in db.graded_answers(profile)])
