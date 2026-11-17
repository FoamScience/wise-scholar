from collections import Counter
from typing import Literal

from pydantic import BaseModel

from .. import db, quiz
from ..tutor import _searched, _shuffled, mcp


PARTS = (1, 4)
card_jobs: dict[int, str] = {}  # card id -> "short" or "miss", the cards the running cards turn may replace


class ShortCard(BaseModel):
    question: str
    kind: Literal["choice", "open"]
    options: list[str] = []
    answer_key: str
    explanation: str = ""


@mcp.tool()
async def split_card(course_id: int, card_id: int, parts: list[ShortCard]) -> str:
    """Replace one review card by 1 to 4 short cards, each asking for one idea of it; the original leaves the reviews.

    question: under 140 characters, readable on its own, with no reference to the original card or to another part.
    choice: 2 or 3 options, each under 80 characters, answer_key exactly one of them; the server shuffles them.
    open: options empty, answer_key the answer in under 160 characters. explanation: under 240 characters, why
    the key is right.
    """
    card = db.card(card_id)
    if not card or card["course_id"] != course_id or card_id not in card_jobs:
        return f"error: card {card_id} is not one of the cards this turn makes short"
    made = [_short(part) for part in parts]
    for n, part in enumerate(made, start=1):
        if problem := _short_error(n, part):
            return problem
    if not PARTS[0] <= len(made) <= PARTS[1]:
        return f"error: give {PARTS[0]} to {PARTS[1]} parts"
    for part in made:
        part["options"] = _shuffled(part["options"])
    ids = db.split_card(card_id, made, card_jobs.pop(card_id))
    return f"card {card_id} replaced by cards {', '.join(map(str, ids))}"


def _short(part: ShortCard) -> dict:
    options = [o.strip() for o in part.options] if part.kind == "choice" else []
    return {"question": part.question.strip(), "kind": part.kind, "options": options,
            "answer_key": part.answer_key.strip(), "explanation": part.explanation.strip()}


def _short_error(n: int, part: dict) -> str | None:
    options = part["options"]
    if part["kind"] == "choice" and not (2 <= len(options) <= quiz.SHORT_OPTIONS and len(set(options)) == len(options) and part["answer_key"] in options):
        return f"error: part {n}: a choice part has 2 to {quiz.SHORT_OPTIONS} distinct options, one of them exactly answer_key"
    if not part["question"] or not part["answer_key"] or quiz.is_long(part) or len(part["explanation"]) > quiz.SHORT_EXPLANATION:
        return f"error: part {n} is too long or empty; keep to the limits above"
    return None


SEARCH_RESULTS = 8
CLAIM_CHARS = 300


class NewClaim(BaseModel):
    key: str
    id: int | None = None
    text: str = ""
    evidence: list[int] = []


class ClaimLink(BaseModel):
    source: str
    target: str
    kind: Literal["follows", "supports", "contrasts"]


@mcp.tool()
async def search_claims(lesson_id: int, queries: list[str]) -> str:
    """Search the learner's claims, from all their courses, for each query (a few words). Search before recording:
    a claim that is already there is reused by its id, not recorded again."""
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    _searched.add(lesson_id)
    out, shown = [], set()
    for query in queries:
        found = db.search_claims(lesson["profile_id"], query, SEARCH_RESULTS)
        out.append(f"{query!r}:")
        out += [
            f"  claim {c['id']} (above)" if c["id"] in shown else
            f"  claim {c['id']}: {c['text']}" + (" (marked wrong by the learner: never record it)" if c["wrong"] else f" (from: {', '.join(c['courses'])})")
            for c in found
        ] or ["  nothing found"]
        shown.update(c["id"] for c in found)
    return "\n".join(out)


def _claim_error(c: NewClaim, text: str, lesson: dict) -> str | None:
    """Why a claim cannot be recorded: neither or both of id and text, a claim that is not the learner's or that they
    marked wrong, one said already, or evidence that is not a check of this lesson."""
    if (c.id is None) == (not text):
        return f"error: claim {c.key!r} needs either id or text, not both"
    problem = _known_claim_error(c.id, lesson) if c.id is not None else _new_claim_error(c.key, text, lesson)
    if problem:
        return problem
    for block_id in c.evidence:
        if not _evidence_of(db.block(block_id), lesson):
            return f"error: block {block_id} is not a quick check, challenge or exercise of this lesson after the pretest"
    return None


def _known_claim_error(claim_id: int, lesson: dict) -> str | None:
    known = db.claim(claim_id)
    if not known or known["profile_id"] != lesson["profile_id"]:
        return f"error: there is no claim {claim_id}"
    if known["wrong"]:
        return f"error: claim {claim_id} was marked wrong by the learner; leave it out"
    return None


def _new_claim_error(key: str, text: str, lesson: dict) -> str | None:
    if len(text) > CLAIM_CHARS:
        return f"error: claim {key!r} is too long; one statement, under {CLAIM_CHARS} characters"
    if same := db.same_claim(lesson["profile_id"], text):
        return f"error: claim {key!r} was marked wrong by the learner; leave it out" if same["wrong"] else f"error: claim {same['id']} says {key!r} already; give its id"
    return None


def _evidence_of(block: dict | None, lesson: dict) -> bool:
    """A quick check, challenge or exercise of this lesson, past its pretest."""
    return bool(block) and block["lesson_id"] == lesson["id"] and block["kind"] in db.EVIDENCE_KINDS and not (block["data"] or {}).get("pretest")


@mcp.tool()
async def record_claims(lesson_id: int, claims: list[NewClaim], links: list[ClaimLink] = []) -> str:
    """Record the claims this lesson taught, all in one call, after search_claims.

    claims: each with a key of your choosing (used by links), then either id (a claim search found, reused) or
    text (a new claim: one true statement, worded on its own, under 300 characters), and evidence: the block ids
    of this lesson's quick checks, challenges and exercises that tested it (not the pretest).
    links: between keys. follows: target is derived from source. supports: source grounds target without
    entailing it. contrasts: the two look alike but differ.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if lesson_id not in _searched:
        return "error: call search_claims first, and reuse the claims it finds"
    keys = [c.key for c in claims]
    if not claims or not all(keys) or len(set(keys)) < len(keys):
        return "error: give at least one claim, each with its own key"
    entries = []
    for c in claims:
        text = " ".join(c.text.split())
        if problem := _claim_error(c, text, lesson):
            return problem
        entries.append({"key": c.key, "id": c.id, "text": text, "evidence": c.evidence})
    if bad := next((link for link in links if {link.source, link.target} - set(keys) or link.source == link.target), None):
        return f"error: link {bad.source!r} to {bad.target!r} must join two different keys of this call"
    ids = db.record_claims(lesson["profile_id"], lesson_id, entries, [(l.source, l.target, l.kind) for l in links])
    return "recorded: " + ", ".join(f"{k} = claim {i}" for k, i in ids.items())


EDIT_CHARS = 2000
REASON_CHARS = 300
cleanup_jobs: dict[int, dict[tuple[str, str], str]] = {}  # course id -> (target, ref) -> text the running cleanup turn reads


class Edit(BaseModel):
    target: Literal["block", "card", "file", "course", "summary"]
    ref: str
    old: str
    new: str
    reason: str


@mcp.tool()
async def propose_edits(course_id: int, edits: list[Edit]) -> str:
    """Propose exact replacements in the version about to be published; the author accepts or rejects each one.

    target and ref: as in the header of the piece, e.g. [block 3f…] is target block, ref 3f…; [course details] is
    target course, ref details. old: text copied exactly from that piece, under 2000 characters; every occurrence
    of it in the piece is replaced. new: the replacement, in the same language and register. reason: under 300
    characters, what the old text says about the author.
    """
    pieces = cleanup_jobs.get(course_id)
    if pieces is None:
        return f"error: course {course_id} is not being checked"
    out = [f"{n}: {_propose(course_id, pieces, e)}" for n, e in enumerate(edits, start=1)]
    return "\n".join(out) or "error: give at least one edit"


def _propose(course_id: int, pieces: dict[tuple[str, str], str], e: Edit) -> str:
    """Record one edit, or say why not."""
    if problem := _edit_error(pieces.get((e.target, e.ref)), e):
        return problem
    if db.row("SELECT 1 FROM publish_edits WHERE course_id = ? AND target = ? AND ref = ? AND old = ?", course_id, e.target, e.ref, e.old):
        return "already proposed"
    db.conn.execute(
        "INSERT INTO publish_edits (course_id, target, ref, old, new, reason) VALUES (?, ?, ?, ?, ?, ?)",
        (course_id, e.target, e.ref, e.old, e.new, e.reason.strip()),
    )
    return "proposed"


def _edit_error(text: str | None, e: Edit) -> str | None:
    if text is None:
        return f"error: there is no {e.target} {e.ref!r} in this version"
    if not e.old or e.old not in text:
        return f"error: old is not in that {e.target}; copy it exactly"
    if e.old == e.new or max(len(e.old), len(e.new)) > EDIT_CHARS or not e.reason.strip() or len(e.reason) > REASON_CHARS:
        return f"error: old and new must differ, each under {EDIT_CHARS} characters, with a reason under {REASON_CHARS}"
    return None


SUGGESTIONS = 6
SUGGESTIONS_OF_A_KIND = 2
SUGGESTION_TITLE_CHARS = 70
SUGGESTION_PITCH_CHARS = 260
suggestion_jobs: dict[int, dict] = {}  # course id the turn runs on -> {"profile_id", "topics", "retire", "done"}


class Suggestion(BaseModel):
    title: str
    pitch: str
    kind: Literal["deeper", "adjacent"]
    builds_on: str


@mcp.tool()
async def suggest_courses(course_id: int, suggestions: list[Suggestion]) -> str:
    """Offer the learner their next courses; these replace the ones on offer.

    Exactly 6, at least 2 of each kind. title: the subject as a person would type it to start a course, plain text,
    under 70 characters. pitch: under 260 characters, what the learner will be able to do and what of theirs carries
    over. kind: deeper goes up a level in what they know, adjacent opens a neighbouring field. builds_on: the topic of
    one of the learner's courses, copied exactly from its [course] line.
    """
    job = suggestion_jobs.get(course_id)
    if job is None:
        return f"error: no suggestions are being written on course {course_id}"
    entries = [{k: " ".join(v.split()) for k, v in s.model_dump().items()} for s in suggestions]
    if problem := _suggestions_error(entries, job["topics"]):
        return problem
    db.set_suggestions(job["profile_id"], entries, job["retire"])
    job["done"] = True
    return "recorded"


def _suggestion_mix_error(entries: list[dict]) -> str | None:
    if len(entries) != SUGGESTIONS:
        return f"error: give exactly {SUGGESTIONS} suggestions"
    kinds = Counter(e["kind"] for e in entries)
    if min(kinds["deeper"], kinds["adjacent"]) < SUGGESTIONS_OF_A_KIND:
        return f"error: give at least {SUGGESTIONS_OF_A_KIND} of each kind"
    titles = [e["title"].casefold() for e in entries]
    if len(set(titles)) != len(titles):
        return "error: every suggestion needs its own title"
    return None


def _outside_limits(entry: dict) -> bool:
    return not entry["title"] or not entry["pitch"] or len(entry["title"]) > SUGGESTION_TITLE_CHARS or len(entry["pitch"]) > SUGGESTION_PITCH_CHARS


def _suggestion_fit_error(entries: list[dict], topics: list[str]) -> str | None:
    if taken := [e["title"] for e in entries if e["title"].casefold() in {t.casefold() for t in topics}]:
        return f"error: {taken} are already courses of this learner"
    if bad := [e["title"] for e in entries if _outside_limits(e)]:
        return f"error: {bad} need a title under {SUGGESTION_TITLE_CHARS} characters and a pitch under {SUGGESTION_PITCH_CHARS}"
    return None


def _suggestion_parent_error(entries: list[dict], topics: list[str]) -> str | None:
    if unknown := sorted({e["builds_on"] for e in entries} - set(topics)):
        return f"error: {unknown} are not courses of this learner; copy builds_on from a [course] line"
    return None


def _suggestions_error(entries: list[dict], topics: list[str]) -> str | None:
    """Six, both kinds, distinct new titles within the limits, each building on one of the learner's courses."""
    return _suggestion_mix_error(entries) or _suggestion_fit_error(entries, topics) or _suggestion_parent_error(entries, topics)


RECAP_INTRO_CHARS = 700
RECAP_CAPTION_CHARS = 220
RECAP_POINT_CHARS = 200
RECAP_CAN_DO = (2, 5)
RECAP_STRENGTHEN = (1, 2)
recap_jobs: dict[int, dict] = {}  # course id -> {"weeks", "locale", "finished", "done"}


class WeekCaption(BaseModel):
    week: str
    caption: str


@mcp.tool()
async def write_recap(course_id: int, intro: str, weeks: list[WeekCaption], can_do: list[str], strengthen: list[str], next_step: str) -> str:
    """Write the narrative of the finished course's recap.

    intro: about 80 words on where the learner started and what the course set out to do, under 700 characters.
    weeks: one caption per [week] line, its week copied exactly, each one sentence under 220 characters on what
    changed that week. can_do: 2 to 5 things the learner can now do that they could not before, each one short
    sentence under 200 characters. strengthen: the 1 or 2 things to strengthen, each one sentence under 200
    characters. next_step: one sentence under 200 characters on what this course opens next.
    Plain text with inline Markdown; no headings, no lists inside an item.
    """
    job = recap_jobs.get(course_id)
    if job is None:
        return f"error: no recap is being written on course {course_id}"
    intro, next_step = " ".join(intro.split()), " ".join(next_step.split())
    can_do = [p for p in (" ".join(p.split()) for p in can_do) if p]
    strengthen = [p for p in (" ".join(p.split()) for p in strengthen) if p]
    captions = {w.week.strip(): " ".join(w.caption.split()) for w in weeks}
    if problem := _points_error(intro, can_do, strengthen, next_step) or _captions_error(captions, job["weeks"]):
        return problem
    db.set_recap(course_id, narrative={
        "intro": intro, "weeks": captions, "can_do": can_do, "strengthen": strengthen, "next_step": next_step,
        "locale": job["locale"], "finished": job["finished"], "revisits": job.get("revisits", 0),
    })
    job["done"] = True
    return "recorded"


def _points_error(intro: str, can_do: list[str], strengthen: list[str], next_step: str) -> str | None:
    if not intro or len(intro) > RECAP_INTRO_CHARS:
        return f"error: the intro must be under {RECAP_INTRO_CHARS} characters"
    if not RECAP_CAN_DO[0] <= len(can_do) <= RECAP_CAN_DO[1]:
        return f"error: give {RECAP_CAN_DO[0]} to {RECAP_CAN_DO[1]} can_do points"
    if not RECAP_STRENGTHEN[0] <= len(strengthen) <= RECAP_STRENGTHEN[1]:
        return f"error: give {RECAP_STRENGTHEN[0]} or {RECAP_STRENGTHEN[1]} strengthen points"
    if long := [p for p in [*can_do, *strengthen] if len(p) > RECAP_POINT_CHARS]:
        return f"error: {[p[:40] for p in long]} must be one sentence under {RECAP_POINT_CHARS} characters"
    if not next_step or len(next_step) > RECAP_POINT_CHARS:
        return f"error: next_step must be one sentence under {RECAP_POINT_CHARS} characters"
    return None


def _captions_error(captions: dict[str, str], weeks: list[str]) -> str | None:
    """One caption for each week of the course, and none for another, each within the limit."""
    if missing := [w for w in weeks if w not in captions]:
        return f"error: weeks {missing} need a caption"
    if extra := sorted(set(captions) - set(weeks)):
        return f"error: {extra} are not weeks of this course; copy them from the [week] lines"
    if long := [w for w, c in captions.items() if not c or len(c) > RECAP_CAPTION_CHARS]:
        return f"error: the captions of {long} must be one sentence under {RECAP_CAPTION_CHARS} characters"
    return None
