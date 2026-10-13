import os
import tempfile
from datetime import datetime, timedelta, timezone

from fsrs import Rating

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import review  # noqa: E402


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
    state, due_miss = review.schedule(None, False, 0.9, 0, now)
    _, due_sure = review.schedule(None, True, 0.95, 3, now)
    assert datetime.fromisoformat(due_miss) - now < timedelta(hours=1)
    assert datetime.fromisoformat(due_sure) - now > timedelta(days=1)
    _, due_next = review.schedule(state, True, 0.7, 3, now + timedelta(minutes=5))
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


def test_a_card_and_its_word_are_relearned_on_three_separate_days():
    from wise_scholar import db, quiz

    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    _, due = review.schedule(None, True, 0.95, 1, now)
    assert datetime.fromisoformat(due) == now + timedelta(days=1)
    _, due = review.schedule(None, True, 0.95, 3, now)
    assert datetime.fromisoformat(due) > now + timedelta(days=1)

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Relearn')").lastrowid
    course = db.create_course("German", who)["id"]
    card = db.add_card(course, None, "Hund?", "open", [], "dog", "", scheduled=True)
    db.conn.execute("UPDATE cards SET lemma = 'hund', lang = 'de' WHERE id = ?", (card,))
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)

    def state():
        return db.row("SELECT state FROM vocab_knowledge WHERE profile_id = ? AND lemma = 'hund'", who)["state"]

    def answer(correct, day):
        answer_id = quiz.submit(db.card(card), "dog", 0.9)
        db.conn.execute("UPDATE answers SET created = ? WHERE id = ?", (f"2026-10-{day:02d} 10:00:00", answer_id))
        return datetime.fromisoformat(quiz.grade(answer_id, correct)["due"])

    try:
        assert answer(True, 1) <= tomorrow and answer(True, 1) <= tomorrow
        assert db.recall_days(card) == 1 and state() == "learning"
        assert answer(True, 2) <= tomorrow and db.recall_days(card) == 2 and state() == "learning"
        assert answer(True, 3) > tomorrow and db.recall_days(card) == 3 and state() == "known"
        answer(False, 4)
        assert db.recall_days(card) == 0 and state() == "learning"
        assert answer(True, 5) <= tomorrow
        quiz.dont_know(db.card(card))
        assert db.recall_days(card) == 0
        db.set_vocab(who, "de", "hund", "known", "learner")
        answer(True, 6)
        assert state() == "known"  # a right answer never takes a known word back
        once = db.add_card(course, None, "Katze?", "open", [], "cat", "", scheduled=False)
        db.conn.execute("UPDATE cards SET lemma = 'katze', lang = 'de' WHERE id = ?", (once,))
        quiz.grade(quiz.submit(db.card(once), "cat", 0.9), True)
        assert db.row("SELECT state FROM vocab_knowledge WHERE profile_id = ? AND lemma = 'katze'", who)["state"] == "known"
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM vocab_knowledge WHERE profile_id = ?", (who,))
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


def test_the_cards_table_rebuild_keeps_rows_and_their_answers_and_errors(tmp_path):
    import sqlite3

    from wise_scholar import db

    raw = sqlite3.connect(tmp_path / "old.db")
    raw.row_factory = sqlite3.Row
    for script in db.MIGRATIONS[:-1]:
        raw.executescript(script)
    raw.execute("ALTER TABLE cards DROP COLUMN lang")  # as on a database whose earlier upgrade missed it
    raw.execute("INSERT INTO cards (id, course_id, question, kind, options, answer_key, explanation, lemma, translation) VALUES (7, 1, 'q', 'open', '[]', 'a', 'e', 'hund', 't')")
    raw.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (7, 'x', 0.5, 1)")
    raw.execute("INSERT INTO errors (profile_id, course_id, card_id, kind, prompt, said, correct) VALUES (1, 1, 7, 'quiz', 'p', 's', 'c')")
    raw.commit()
    db.MIGRATIONS[-1](raw)
    db.MIGRATIONS[-1](raw)  # a rerun after a crash before the version bump is harmless
    card = [tuple(r) for r in raw.execute("SELECT id, lemma, lang, translation, relearn_after FROM cards").fetchall()]
    assert card == [(7, "hund", None, "t", 0)]
    assert [r[0] for r in raw.execute("SELECT card_id FROM answers")] == [7] and [r[0] for r in raw.execute("SELECT card_id FROM errors")] == [7]
    broken = [tuple(r) for t in ("answers", "errors") for r in raw.execute(f"PRAGMA foreign_key_check({t})") if r[2] == "cards"]
    assert broken == []  # the profile and course rows are missing on purpose; only the card links are under test
    raw.execute("PRAGMA foreign_keys = OFF")
    raw.execute("INSERT INTO cards (course_id, question, kind, options, answer_key, explanation) VALUES (1, 'q', 'sort', '[]', '[]', 'e')")
    raw.close()
