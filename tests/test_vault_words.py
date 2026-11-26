import asyncio
import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, obsidian  # noqa: E402
from wise_scholar.routes import blocks  # noqa: E402


def course_with_unit(name: str) -> tuple[int, int]:
    who = db.conn.execute("INSERT INTO profiles (name, locale) VALUES (?, 'en')", (f"Vault words {name}",)).lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, "de")
    db.set_concepts(course, [{"title": "Home", "concepts": ["Rooms"], "known": []}])
    return course, db.concepts(course)[0]["id"]


def notes(course: int) -> tuple[str, list[str]]:
    """The course note and the unit notes of the course's vault."""
    vault = obsidian.Vault(course)
    files = vault.build()
    text = lambda key: files[vault.names[key] + ".md"].decode()  # noqa: E731
    return text(("course",)), [text(("unit", c["id"])) for c in vault.concepts]


def word_card(course: int, unit: int | None, lemma: str, due: str | None) -> int:
    card = db.add_card(course, unit, f"What does **{lemma}** mean?", "open", [], "a meaning", "", scheduled=True, due=due, vocab=True)
    db.conn.execute("UPDATE cards SET lemma = ?, lang = 'de' WHERE id = ?", (lemma, card))
    return card


def test_a_saved_word_is_in_the_course_notes_flashcards():
    course, _ = course_with_unit("saved")
    asyncio.run(blocks.save_word(course, blocks.SavedWord(word="Haus", meaning="house", sentence="Das Haus ist alt.")))
    note, [unit] = notes(course)
    assert "\n#flashcards\n\nWhat does **Haus** mean?\n?\nhouse" in note
    assert "Haus" not in unit


def test_a_word_already_in_a_units_flashcards_is_not_listed_again():
    course, unit = course_with_unit("twice")
    word_card(course, unit, "tisch", "2026-01-01T00:00:00+00:00")
    word_card(course, None, "tisch", "2026-01-02T00:00:00+00:00")
    note, [unit_note] = notes(course)
    assert unit_note.count("What does **tisch** mean?") == 1
    assert "#flashcards" not in note


def test_a_word_its_learner_never_saved_stays_out():
    course, unit = course_with_unit("unsaved")
    word_card(course, None, "stuhl", None)
    word_card(course, unit, "stuhl", None)
    note, [unit_note] = notes(course)
    assert "stuhl" not in note and "stuhl" not in unit_note
