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

    card = db.add_card(haskell, None, "q", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00", vocab=True)
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
        card = db.add_card(course_id, concept, "q", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00", vocab=True)
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


def test_set_known_recalibrates_the_map_without_rebuilding_it():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Re')").lastrowid
    course = db.create_course("German", who)["id"]
    db.set_concepts(course, [{"title": "A1", "concepts": ["Greetings", "Numbers"], "known": ["Greetings"]}, {"title": "A2", "concepts": ["Perfekt"], "known": []}])
    assert [c["mastery"] for c in db.concept_view(course)] == [1.0, None, None]
    assert "not concepts" in asyncio.run(tutor.set_known(course, ["Numbers"], ["Nope"]))
    assert asyncio.run(tutor.set_known(course, ["Numbers", "Perfekt"], ["Greetings"])) == "updated"
    assert [(c["title"], c["known"]) for c in db.concepts(course)] == [("Greetings", 0), ("Numbers", 1), ("Perfekt", 1)]


def test_pretest_gates_explanations_and_stays_out_of_reviews_and_mastery():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Pre')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership", "Traits"], "known": ["Traits"]}])
    own, traits = db.concepts(course)
    lesson = db.create_lesson(course, "Ownership", "lesson", own["id"])
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")).startswith("refused: no pretest")
    asyncio.run(tutor.pose_quiz(lesson, "What happens to s after let t = s;?", "open", [], "s is moved", "", pretest=True))
    block = db.blocks(lesson)[-1]
    card = db.card(block["data"]["card_id"])
    assert card["concept_id"] is None and card["scheduled"] == 0 and block["data"]["pretest"]
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")).startswith("refused")
    db.set_block_data(block["id"], {**block["data"], "answer": "it is copied", "answer_id": 1})
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")) == "shown"
    assert db.concept_mastery(course) == {}

    known_lesson = db.create_lesson(course, "Traits", "lesson", traits["id"])
    assert asyncio.run(tutor.add_block(known_lesson, "prose", "Traits are…")) == "shown"


def test_series_episodes_keep_memory_and_pass_a_stricter_gate():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Story')").lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, "de")
    db.set_vocab_tier(who, "de", 30)
    lesson = db.create_lesson(course, "Episode 1", "story")
    gloss = tutor.Gloss
    assert "no series yet" in asyncio.run(tutor.add_episode(lesson, "t", "x " * 500, "de-DE", "r"))
    assert asyncio.run(tutor.start_series(course, "Lena in Köln", ["Lena: Studentin", "Omar: Nachbar"], "Lena zieht nach Köln.")).startswith("started")
    assert "already has a series" in asyncio.run(tutor.start_series(course, "x", [], ""))
    sentence = "Lena geht am Morgen in die Stadt und kauft Brot, dann trifft sie Omar vor dem Haus und sie reden über das Wetter. "
    text = sentence * 20
    assert "words" in asyncio.run(tutor.add_episode(lesson, "Brot", sentence * 5, "de-DE", "r"))
    assert "at most 5 glossary" in asyncio.run(tutor.add_episode(lesson, "Brot", text, "de-DE", "r", glossary=[gloss(word="Brot", meaning="bread")] * 6))
    rare = text + "Die Thrombozytenzahl der Bürgschaftserklärung war unleserlich. " * 8
    assert asyncio.run(tutor.add_episode(lesson, "Brot", rare, "de-DE", "r")).startswith("rewrite")
    assert asyncio.run(tutor.add_episode(lesson, "Brot", text, "de-DE", "Lena kauft Brot und trifft Omar.")).startswith("shown as episode 1")
    show = db.series(course)
    assert show["episodes"] == 1 and "Lena kauft Brot" in show["synopsis"]
    block = db.blocks(lesson)[-1]
    assert block["kind"] == "reading" and block["data"]["story"] == "Lena in Köln" and block["data"]["episode"] == 1
