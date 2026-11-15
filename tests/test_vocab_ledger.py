import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


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
