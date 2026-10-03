import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import speech  # noqa: E402


def test_word_match_marks_what_the_recogniser_heard():
    words = speech.word_match("Der Kühlschrank ist voll, wir müssen nicht einkaufen.", "der kühlschrank ist leer wir müssen einkaufen")
    assert [w["word"] for w in words] == ["Der", "Kühlschrank", "ist", "voll", "wir", "müssen", "nicht", "einkaufen"]
    assert [w["score"] for w in words] == [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert all(w["score"] == 0.0 for w in speech.word_match("Guten Morgen", ""))


def test_make_podcast_checks_the_dialogue_before_rendering():
    import asyncio

    from wise_scholar import db, tutor

    profile = db.conn.execute("INSERT INTO profiles (name) VALUES ('Pod')").lastrowid
    lesson = db.create_lesson(db.create_course("Rust", profile)["id"], "Ownership", "lesson")
    line = tutor.Line(speaker="Anna", text="Heute reden wir über Ownership. " * 4)
    other = tutor.Line(speaker="Tom", text="Ja, und über Borrowing. " * 4)
    run = lambda **kw: asyncio.run(tutor.make_podcast(lesson, "Cast", "de-DE", **kw))  # noqa: E731

    assert "exactly two speakers" in run(lines=[line] * 10)
    assert "words" in run(lines=[line, other] * 5)
    assert "split them" in run(lines=[tutor.Line(speaker="Anna", text="x " * 200), other] * 50)
    full = [line, other] * 28
    assert "outside the dialogue" in run(lines=full, questions=[tutor.CastQuestion(after_line=60, question="q", kind="open", answer_key="a", explanation="e")])
    assert "glossary words" in run(lines=full, glossary=[tutor.Gloss(word="Nope", meaning="x")])
    assert sum(len(l.text.split()) for l in full) in range(*tutor.CAST_WORDS)
