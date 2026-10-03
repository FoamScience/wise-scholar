from datetime import datetime

from fsrs import Card, Rating, Scheduler

CONFIDENT = 0.75
BUCKETS = [(0.0, "under 50%"), (0.5, "50–69%"), (0.7, "70–89%"), (0.9, "90–100%")]

scheduler = Scheduler()


def rating(correct: bool, confidence: float) -> Rating:
    # ponytail: fixed confidence cut-offs; fit them to the learner's answer history if reviews feel mis-paced
    if not correct:
        return Rating.Again
    if confidence < 0.5:
        return Rating.Hard
    return Rating.Easy if confidence >= 0.9 else Rating.Good


def schedule(fsrs_json: str | None, correct: bool, confidence: float, now: datetime | None = None) -> tuple[str, str]:
    """Advance a card's FSRS state by one graded answer; return (state json, due as ISO UTC)."""
    card = Card.from_json(fsrs_json) if fsrs_json else Card()
    card, _ = scheduler.review_card(card, rating(correct, confidence), now)
    return card.to_json(), card.due.isoformat()


def is_confident_miss(correct: bool, confidence: float) -> bool:
    return not correct and confidence >= CONFIDENT


def calibration(answers: list[tuple[float, bool]]) -> dict:
    """Brier score and stated-versus-actual accuracy per confidence bucket."""
    buckets = []
    for i, (low, label) in enumerate(BUCKETS):
        high = BUCKETS[i + 1][0] if i + 1 < len(BUCKETS) else 1.01
        inside = [(p, c) for p, c in answers if low <= p < high]
        buckets.append({
            "label": label,
            "n": len(inside),
            "stated": sum(p for p, _ in inside) / len(inside) if inside else None,
            "actual": sum(c for _, c in inside) / len(inside) if inside else None,
        })
    brier = sum((p - c) ** 2 for p, c in answers) / len(answers) if answers else None
    return {"n": len(answers), "brier": brier, "buckets": buckets}


def interleave(cards: list[dict]) -> list[dict]:
    """Alternate due cards across courses instead of grouping them, keeping confident misses in front."""
    out = []
    for front in (True, False):
        queues: dict[int, list[dict]] = {}
        for c in cards:
            if bool(c["confident_miss"]) == front:
                queues.setdefault(c["course_id"], []).append(c)
        while queues:
            for course_id in list(queues):
                out.append(queues[course_id].pop(0))
                if not queues[course_id]:
                    del queues[course_id]
    return out
