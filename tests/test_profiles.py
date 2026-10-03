import os
import tempfile

os.environ["WISE_SCHOLAR_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from wise_scholar import db  # noqa: E402


def test_facts_reviews_and_answers_stay_inside_their_profile():
    ada = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ada')").lastrowid
    ben = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ben')").lastrowid
    haskell = db.create_course("Haskell", ada)["id"]
    german = db.create_course("German", ben)["id"]

    db.add_fact(haskell, "Ada writes C++ daily.", about_learner=True)
    db.add_fact(haskell, "Sittings are 30 minutes.", about_learner=False)
    assert [f["text"] for f in db.facts(haskell)] == ["Ada writes C++ daily.", "Sittings are 30 minutes."]
    assert db.facts(german) == []
    assert [f["text"] for f in db.learner_facts(ada)] == ["Ada writes C++ daily."]
    assert db.learner_facts(ben) == []

    second = db.create_course("Rust", ada)["id"]
    assert [f["text"] for f in db.facts(second)] == ["Ada writes C++ daily."]

    card = db.add_card(haskell, None, "q", "open", [], "a", "e", scheduled=True, vocab_due="2026-01-01T00:00:00+00:00")
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'x', 0.8, 1)", (card,))
    now = "2026-10-02T00:00:00+00:00"
    assert [c["id"] for c in db.due_cards(ada, now)] == [card]
    assert db.due_cards(ben, now) == []
    assert len(db.graded_answers(ada)) == 1 and db.graded_answers(ben) == []

    assert db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", german)["id"])["profile"] == "Ben"
    assert {p["name"]: p["courses"] for p in db.profiles()} == {"Ada": 2, "Ben": 1}


def test_archived_courses_leave_the_review_queue_and_deleted_courses_leave_nothing():
    cy = db.conn.execute("INSERT INTO profiles (name) VALUES ('Cy')").lastrowid
    kept = db.create_course("Lean", cy)["id"]
    gone = db.create_course("Go", cy)["id"]
    now = "2026-10-02T00:00:00+00:00"
    for course_id in (kept, gone):
        db.set_concepts(course_id, [{"title": "M", "concepts": ["C"], "known": []}])
        concept = db.concepts(course_id)[0]["id"]
        lesson = db.create_lesson(course_id, "C", "lesson", concept)
        db.add_block(lesson, "prose", "text")
        db.add_message(lesson, "tutor", "hi")
        db.add_fact(course_id, "Sittings are short.", about_learner=False)
        card = db.add_card(course_id, concept, "q", "open", [], "a", "e", scheduled=True, vocab_due="2026-01-01T00:00:00+00:00")
        db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'x', 0.5, 1)", (card,))
    assert len(db.due_cards(cy, now)) == 2

    db.conn.execute("UPDATE courses SET archived = 1 WHERE id = ?", (kept,))
    assert [c["course_id"] for c in db.due_cards(cy, now)] == [gone]

    db.delete_course(gone)
    assert db.course(gone) is None and db.due_cards(cy, now) == []
    for table in ("lessons", "concepts", "cards", "facts"):
        assert db.rows(f"SELECT 1 FROM {table} WHERE course_id = ?", gone) == []
    assert db.course(kept) and len(db.facts(kept)) == 1 and len(db.graded_answers(cy)) == 1
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_vocabulary_ledger_promotes_and_scopes_per_profile_and_language():
    dee = db.conn.execute("INSERT INTO profiles (name) VALUES ('Dee')").lastrowid
    course = db.create_course("German", dee)["id"]
    db.course_lang(course, "de")
    db.course_lang(course, "fr")
    assert db.course(course)["lang"] == "de"

    assert db.vocab_tier(dee, "de", 3) == 3
    db.set_vocab_tier(dee, "de", 4)
    db.set_vocab_tier(dee, "de", 5)
    assert db.vocab_tier(dee, "de", 3) == 5

    db.set_vocab(dee, "de", "Haus", "learning", "target")
    db.set_vocab(dee, "de", "Arzt", "known", "learner")
    db.set_vocab(dee, "de", "Arzt", "learning", "target")
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt"}
    assert db.vocab_lemmas(dee, "de") == {"arzt", "haus"}
    assert db.vocab_lemmas(dee, "fr") == set()

    db.add_exposures(dee, "de", {"haus": 3, "termin": 2}, promote_at=5)
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt"}
    db.add_exposures(dee, "de", {"haus": 2}, promote_at=5)
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt", "haus"}


def test_vocabulary_check_seeds_the_ledger_and_sets_the_tier():
    from wise_scholar import tutor, vocab

    eve = db.conn.execute("INSERT INTO profiles (name) VALUES ('Eve')").lastrowid
    course = db.create_course("German", eve)["id"]
    lesson = {**db.lesson(db.create_lesson(course, "Placement", "placement")), "profile_id": eve}
    data = {"lang": "de", "rounds": [], "current": {"tier": 1, "words": vocab.sample_tier("de", 1)}, "tier": None}

    data, event = tutor.vocab_round(lesson, data, data["current"]["words"])
    assert event is None and data["current"]["tier"] == 2 and data["rounds"][0]["passed"]
    words = data["current"]["words"]
    data, event = tutor.vocab_round(lesson, data, words[:3] + ["notasampledword"])
    assert data["current"] is None and data["tier"] == 2 and not data["rounds"][1]["passed"]
    assert "tier 2" in event and data["rounds"][0]["known"][0] in event and "notasampledword" not in event
    assert db.vocab_tier(eve, "de", 1) == 2
    assert {w.lower() for w in words[:3]} <= db.vocab_lemmas(eve, "de", ("known",))
    assert {w.lower() for w in words[3:]} <= db.vocab_lemmas(eve, "de", ("learning",))

    db.set_vocab(eve, "de", words[0], "learning", "review")
    assert words[0].lower() in db.vocab_lemmas(eve, "de", ("known",))
    db.set_vocab(eve, "de", words[0], "learning", "review", force=True)
    assert words[0].lower() not in db.vocab_lemmas(eve, "de", ("known",))


def test_teachback_grade_counts_toward_concept_mastery():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Tee')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership"], "known": []}])
    concept = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Ownership", "lesson", concept)
    asyncio.run(tutor.pose_teachback(lesson, "Explain ownership", "one owner; moves; drop at scope end"))
    block = db.blocks(lesson)[-1]
    assert db.concept_mastery(course) == {}
    db.set_block_data(block["id"], {**block["data"], "attempts": ["Each value has one owner and is dropped at the end of scope."]})
    assert asyncio.run(tutor.mark_solved(block["id"])) == "marked"
    assert db.concept_mastery(course) == {concept: 1.0}
