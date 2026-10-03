from . import db, review


def public(card: dict) -> dict:
    """The part of a card the browser may see before the answer is graded."""
    return {
        "id": card["id"],
        "topic": card.get("topic"),
        "question": card["question"],
        "kind": card["kind"],
        "options": card["options"],
        "confident_miss": bool(card["confident_miss"]),
    }


def submit(card: dict, answer: str, confidence: float) -> int:
    """Store an answer before anything about the key is disclosed; returns the answer id."""
    return db.conn.execute(
        "INSERT INTO answers (card_id, answer, confidence) VALUES (?, ?, ?)", (card["id"], answer, confidence)
    ).lastrowid


def auto_correct(card: dict, answer: str) -> bool | None:
    """Choice cards are graded here; open cards need a judge and return None."""
    return answer == card["answer_key"] if card["kind"] == "choice" else None


def grade(answer_id: int, correct: bool) -> dict:
    """Finalize a stored answer: record correctness, reschedule the card, disclose the key."""
    answer = db.row("SELECT * FROM answers WHERE id = ?", answer_id)
    card = db.card(answer["card_id"])
    miss = review.is_confident_miss(correct, answer["confidence"])
    db.conn.execute("UPDATE answers SET correct = ? WHERE id = ?", (int(correct), answer_id))
    profile = db.row("SELECT profile_id FROM courses WHERE id = ?", card["course_id"])["profile_id"]
    if card.get("lemma"):
        db.set_vocab(profile, card["lang"], card["lemma"], "known" if correct else "learning", "review", force=True)
    # Pretests and placement cards are unscheduled: their misses measure, they are not errors to fix.
    if miss and card["scheduled"]:
        db.add_error(profile, card["course_id"], "quiz", card["question"], answer["answer"], card["answer_key"],
                     card["explanation"], card_id=card["id"])
    due = None
    if card["scheduled"]:
        fsrs, due = review.schedule(card["fsrs"], correct, answer["confidence"])
        db.conn.execute(
            "UPDATE cards SET fsrs = ?, due = ?, confident_miss = ? WHERE id = ?", (fsrs, due, int(miss), card["id"])
        )
    return {
        "correct": correct,
        "confident_miss": miss,
        "answer_key": card["answer_key"],
        "explanation": card["explanation"],
        "due": due,
    }
