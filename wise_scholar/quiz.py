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
