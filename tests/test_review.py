from datetime import datetime, timedelta, timezone

from fsrs import Rating

from wise_scholar import review


def test_rating_follows_correctness_then_confidence():
    assert review.rating(False, 0.95) is Rating.Again
    assert review.rating(False, 0.2) is Rating.Again
    assert review.rating(True, 0.3) is Rating.Hard
    assert review.rating(True, 0.7) is Rating.Good
    assert review.rating(True, 0.95) is Rating.Easy
    assert review.is_confident_miss(False, 0.8) and not review.is_confident_miss(False, 0.5)
    assert not review.is_confident_miss(True, 0.99)


def test_schedule_round_trips_state_and_spaces_a_sure_correct_answer_further_than_a_miss():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    state, due_miss = review.schedule(None, False, 0.9, now)
    _, due_sure = review.schedule(None, True, 0.95, now)
    assert datetime.fromisoformat(due_miss) - now < timedelta(hours=1)
    assert datetime.fromisoformat(due_sure) - now > timedelta(days=1)
    _, due_next = review.schedule(state, True, 0.7, now + timedelta(minutes=5))
    assert datetime.fromisoformat(due_next) > now


def test_calibration_buckets_and_brier():
    result = review.calibration([(0.9, True), (0.9, False), (0.6, True), (0.2, False)])
    assert result["n"] == 4
    assert abs(result["brier"] - (0.01 + 0.81 + 0.16 + 0.04) / 4) < 1e-9
    by_label = {b["label"]: b for b in result["buckets"]}
    assert by_label["90–100%"] == {"label": "90–100%", "n": 2, "stated": 0.9, "actual": 0.5}
    assert by_label["70–89%"]["n"] == 0 and by_label["70–89%"]["actual"] is None
    assert review.calibration([])["brier"] is None


def test_due_cards_alternate_across_courses_with_confident_misses_first():
    from wise_scholar import review

    cards = [
        {"id": 1, "course_id": 1, "confident_miss": 0},
        {"id": 2, "course_id": 1, "confident_miss": 0},
        {"id": 3, "course_id": 1, "confident_miss": 1},
        {"id": 4, "course_id": 2, "confident_miss": 0},
        {"id": 5, "course_id": 2, "confident_miss": 0},
        {"id": 6, "course_id": 3, "confident_miss": 0},
    ]
    assert [c["id"] for c in review.interleave(cards)] == [3, 1, 4, 6, 2, 5]
    assert review.interleave([]) == []


def test_confident_misses_and_corrected_texts_fill_the_error_notebook():
    import asyncio
    import os
    import tempfile

    os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
    from wise_scholar import challenge, db, quiz, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Err')").lastrowid
    course = db.create_course("German", who)["id"]
    lesson = db.create_lesson(course, "Dativ", "lesson")
    card = db.add_card(course, None, "Dativ von 'der Mann'?", "open", [], "dem Mann", "Dativ masculine: dem", scheduled=True)
    quiz.grade(quiz.submit(db.card(card), "den Mann", 0.9), False)
    quiz.grade(quiz.submit(db.card(card), "dem Mann", 0.3), False)
    entries = db.errors(who)
    assert len(entries) == 1 and entries[0]["kind"] == "quiz" and entries[0]["said"] == "den Mann" and entries[0]["card_id"] == card

    block = db.add_block(lesson, "challenge", "Schreib einen Satz mit Dativ.", {**challenge.new(reveal_after=1), "writing": True, "marks": []})
    db.set_block_data(block["id"], {**block["data"], "attempts": ["Ich helfe den Mann."], "hints": ["Dativ nach helfen"]})
    assert asyncio.run(tutor.reveal(block["id"], "Ich helfe dem Mann.")) == "shown"
    writing = [e for e in db.errors(who) if e["kind"] == "writing"][0]
    assert writing["said"] == "Ich helfe den Mann." and writing["correct"] == "Ich helfe dem Mann." and writing["explanation"] == "Dativ nach helfen"
    assert db.card(writing["card_id"])["due"] is not None

    due = db.due_cards(who, "2999-01-01T00:00:00+00:00")
    assert {c["id"] for c in due[:2]} == {card, writing["card_id"]} and all(c["confident_miss"] for c in due[:2])
    db.update_error(entries[0]["id"], None, None, True)
    assert db.errors(who, open_only=True) == [writing | {"topic": "German"}] or len(db.errors(who, open_only=True)) == 1
    assert db.update_error(writing["id"], "helfen takes the dative", True, None)["pinned"] == 1
