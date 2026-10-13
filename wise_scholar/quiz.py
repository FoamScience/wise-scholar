import json
from . import db, review


def public(card: dict) -> dict:
    """The part of a card the browser may see before the answer is graded."""
    return {
        "id": card["id"],
        "topic": card.get("topic"),
        "question": card["question"],
        "kind": card["kind"],
        "options": shown_options(card),
        "translation": card.get("translation", ""),
        **({"categories": json.loads(card["answer_key"])} if card["kind"] == "sort" else {}),
        "confident_miss": bool(card["confident_miss"]),
    }


def submit(card: dict, answer: str, confidence: float) -> int:
    """Store an answer before anything about the key is disclosed; returns the answer id."""
    return db.conn.execute(
        "INSERT INTO answers (card_id, answer, confidence) VALUES (?, ?, ?)", (card["id"], answer, confidence)
    ).lastrowid


def auto_correct(card: dict, answer: str) -> bool | None:
    """Choice and sort cards are graded here; open cards need a judge and return None."""
    if card["kind"] == "choice":
        return answer == card["answer_key"]
    if card["kind"] == "sort":
        return not misplaced(card, answer)
    return None


def shown_options(card: dict) -> list:
    """The options as the learner sees them: a sort card's items without their category."""
    return [{"text": o["text"]} for o in card["options"]] if card["kind"] == "sort" else card["options"]


def placements(answer: str) -> dict[str, str]:
    """A sort answer: JSON of item text to category; anything else is an empty placement."""
    try:
        placed = json.loads(answer)
    except ValueError:
        return {}
    return placed if isinstance(placed, dict) and all(isinstance(v, str) for v in placed.values()) else {}


def misplaced(card: dict, answer: str) -> list[str]:
    """The items of a sort card that the answer puts in the wrong category, or leaves out."""
    placed = placements(answer)
    return [item["text"] for item in card["options"] if placed.get(item["text"]) != item["category"]]


def said(card: dict, answer: str, only_wrong: bool = False) -> str:
    """An answer as the learner would read it: a sort answer lists its placements, or only the wrong ones."""
    if card["kind"] != "sort":
        return answer
    placed, wrong = placements(answer), misplaced(card, answer)
    return "; ".join(f"{item['text']} → {placed.get(item['text'], '?')}" for item in card["options"] if not only_wrong or item["text"] in wrong)


def key(card: dict, answer: str) -> str:
    """The right answer for the notebook: for a sort, where the misplaced items go."""
    if card["kind"] != "sort":
        return card["answer_key"]
    wrong = misplaced(card, answer)
    return "; ".join(f"{item['text']} → {item['category']}" for item in card["options"] if item["text"] in wrong)


def _profile(card: dict) -> int:
    return db.row("SELECT profile_id FROM courses WHERE id = ?", card["course_id"])["profile_id"]


def dont_know(card: dict) -> dict:
    """The learner chose "I don't know": a miss that states no confidence, so no answer row is stored
    and calibration never sees it."""
    db.reset_recall(card["id"])
    if card.get("lemma"):
        db.set_vocab(_profile(card), card["lang"], card["lemma"], "learning", "review", force=True)
    return {
        "correct": False,
        "confident_miss": False,
        "answer_key": card["answer_key"],
        "explanation": card["explanation"],
        "due": None,
    }


def grade(answer_id: int, correct: bool) -> dict:
    """Finalize a stored answer: record correctness, reschedule the card, disclose the key."""
    answer = db.row("SELECT * FROM answers WHERE id = ?", answer_id)
    card = db.card(answer["card_id"])
    miss = review.is_confident_miss(correct, answer["confidence"])
    db.conn.execute("UPDATE answers SET correct = ? WHERE id = ?", (int(correct), answer_id))
    profile = _profile(card)
    if not correct:
        db.reset_recall(card["id"])
    days = db.recall_days(card["id"])
    # A reviewed word is known once recalled on enough separate days, not after one lucky answer; a placement or
    # pretest card is answered once and measures, so its one right answer counts.
    known = correct and (not card["scheduled"] or review.relearned(days))
    if card.get("lemma"):
        db.set_vocab(profile, card["lang"], card["lemma"], "known" if known else "learning", "review", force=not correct)
    # Pretests and placement cards are unscheduled: their misses measure, they are not errors to fix.
    if miss and card["scheduled"]:
        db.add_error(profile, card["course_id"], "quiz", card["question"], said(card, answer["answer"], only_wrong=True),
                     key(card, answer["answer"]), card["explanation"], card_id=card["id"])
    due = None
    if card["scheduled"]:
        fsrs, due = review.schedule(card["fsrs"], correct, answer["confidence"], days)
        db.conn.execute(
            "UPDATE cards SET fsrs = ?, due = ?, confident_miss = ? WHERE id = ?", (fsrs, due, int(miss), card["id"])
        )
    return {
        "correct": correct,
        "confident_miss": miss,
        "answer_key": card["answer_key"],
        "explanation": card["explanation"],
        "due": due,
        **({"misplaced": misplaced(card, answer["answer"])} if card["kind"] == "sort" else {}),
    }
