import asyncio
import json
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi import HTTPException  # noqa: E402

from wise_scholar import bundle, db, lexicon, quiz, resources  # noqa: E402
from wise_scholar.routes import blocks  # noqa: E402


def _course(name: str, lang: str = "de") -> tuple[int, int]:
    who = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Words {name}",)).lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, lang)
    return who, course


def test_a_word_is_coloured_by_the_profile_s_record_of_its_lemma():
    who, course = _course("Wanda")
    db.add_exposures(who, "de", {"bürgschaft": 1}, promote_at=5)
    db.set_vocab(who, "de", "haus", "learning", "target")
    db.set_vocab(who, "de", "unleserlich", "known", "learner")
    words = ["Bürgschaft", "Häuser", "unleserlich", "und", "Thrombozyten"]
    assert blocks.word_states(course, blocks.Words(words=words)) == {
        "Bürgschaft": "seen", "Häuser": "learning", "unleserlich": "known", "und": "known", "Thrombozyten": "new",
    }
    _, other = _course("Other")
    assert blocks.word_states(other, blocks.Words(words=["unleserlich"])) == {"unleserlich": "new"}
    asyncio.run(blocks.mark_known(other, blocks.TappedWord(word="unleserlich")))
    assert blocks.word_states(other, blocks.Words(words=["unleserlich"])) == {"unleserlich": "known"}


def test_a_word_of_a_course_without_a_language_is_refused():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Words plain')").lastrowid
    course = db.create_course("Algebra", who)["id"]
    with pytest.raises(HTTPException) as refused:
        blocks.word_states(course, blocks.Words(words=["x"]))
    assert refused.value.status_code == 409


def test_a_tapped_word_shows_its_lexicon_entries(tmp_path, monkeypatch):
    _, course = _course("Lexi")
    assert blocks.look_up(course, "Häuser")["entries"] == []
    entry = {"word": "Haus", "pos": "noun", "senses": [{"glosses": ["house"]}]}
    (tmp_path / lexicon.RAW).write_text(json.dumps(entry) + "\n")
    lexicon.prepare(tmp_path)
    monkeypatch.setattr(resources, "course_resource", lambda *_: tmp_path)
    found = blocks.look_up(course, "haus")
    assert [e["glosses"] for e in found["entries"]] == [["house"]] and not found["saved"]


def test_a_saved_word_keeps_its_sentence_and_never_leaves_the_course(tmp_path):
    who, course = _course("Saver")
    sentence = "Ich habe gestern\nmein Haus verkauft."
    saved = blocks.SavedWord(word="Haus", meaning="house", sentence=sentence)
    asyncio.run(blocks.save_word(course, saved))
    [card] = db.rows("SELECT * FROM cards WHERE course_id = ?", course)
    assert card["context"] == "Ich habe gestern mein Haus verkauft." and card["lemma"] == "haus" and card["vocab"] and card["due"]
    assert quiz.public(db.card(card["id"]))["context"] == card["context"]
    assert blocks.word_states(course, blocks.Words(words=["Haus"])) == {"Haus": "learning"}
    with pytest.raises(HTTPException) as again:
        asyncio.run(blocks.save_word(course, saved))
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as blank:
        asyncio.run(blocks.save_word(course, blocks.SavedWord(word="Brot", meaning=" ")))
    assert blank.value.status_code == 422

    assert db.private_cards(course) == {card["id"]}
    assert db._copy_cards(course, db.create_course("Copy", who)["id"], {}) == {}
    manifest = json.dumps(bundle.build(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=tmp_path)[0], default=str)
    assert "verkauft" not in manifest and "What does **Haus**" not in manifest


def test_a_glossary_word_keeps_its_sentence_only_when_the_reading_holds_it():
    _, course = _course("Gloss")
    lesson = db.create_lesson(course, "Reading", "lesson")
    data = {"title": "Der Markt", "lang": "de-DE", "added": [], "known": [],
            "glossary": [{"word": "Brot", "meaning": "bread"}, {"word": "Markt", "meaning": "market"}]}
    block = db.add_block(lesson, "reading", "Sie kauft Brot.\nDer Markt ist voll.", data)["id"]
    asyncio.run(blocks.add_vocabulary(block, blocks.Word(word="Brot", sentence="Sie kauft Brot.")))
    asyncio.run(blocks.add_vocabulary(block, blocks.Word(word="Markt", sentence="Something I typed myself.")))
    assert [c["context"] for c in db.rows("SELECT context FROM cards WHERE course_id = ? ORDER BY id", course)] == ["Sie kauft Brot.", ""]


def _reading(course: int, word: str) -> int:
    lesson = db.create_lesson(course, "Reading", "lesson")
    data = {"title": "T", "lang": "de-DE", "added": [], "known": [], "glossary": [{"word": word, "meaning": "bicycle"}]}
    return db.add_block(lesson, "reading", f"Das {word} ist neu.", data)["id"]


def test_a_word_saved_by_tapping_gets_no_second_card_from_the_glossary():
    _, course = _course("Twice")
    block = _reading(course, "Fahrrad")
    asyncio.run(blocks.save_word(course, blocks.SavedWord(word="Fahrräder", meaning="bikes", sentence="Zwei Fahrräder.")))
    shown = asyncio.run(blocks.add_vocabulary(block, blocks.Word(word="Fahrrad", sentence="Das Fahrrad ist neu.")))
    [card] = db.rows("SELECT * FROM cards WHERE course_id = ?", course)
    assert (card["answer_key"], card["context"], card["origin"]) == ("bikes", "Zwei Fahrräder.", "word")
    assert shown["data"]["saved"] == ["Fahrrad"] and shown["data"]["added"] == []
    assert "saved" not in db._fresh(shown["data"])
    with pytest.raises(HTTPException) as again:
        asyncio.run(blocks.add_vocabulary(block, blocks.Word(word="Fahrrad")))
    assert again.value.status_code == 409


def test_a_glossary_word_gets_no_second_card_from_a_tap_or_another_reading():
    _, course = _course("Thrice")
    first, second = _reading(course, "Fahrrad"), _reading(course, "Fahrra\u0308der")
    assert asyncio.run(blocks.add_vocabulary(first, blocks.Word(word="Fahrrad")))["data"]["added"] == ["Fahrrad"]
    asyncio.run(blocks.add_vocabulary(second, blocks.Word(word="Fahrra\u0308der")))
    with pytest.raises(HTTPException) as again:
        asyncio.run(blocks.save_word(course, blocks.SavedWord(word="Fahrräder", meaning="bikes")))
    assert again.value.status_code == 409
    assert [c["origin"] for c in db.rows("SELECT origin FROM cards WHERE course_id = ?", course)] == [None]


@pytest.mark.parametrize(("lang", "word"), [("zh", "图书馆"), ("ja", "図書館"), ("th", "หนังสือ")])
def test_a_word_of_an_unspaced_script_is_looked_up_and_saved(tmp_path, monkeypatch, lang, word):
    _, course = _course(f"Unspaced {lang}", lang)
    (tmp_path / lexicon.RAW).write_text(json.dumps({"word": word, "pos": "noun", "senses": [{"glosses": ["a gloss"]}]}) + "\n")
    lexicon.prepare(tmp_path)
    monkeypatch.setattr(resources, "course_resource", lambda *_: tmp_path)
    found = blocks.look_up(course, word)
    assert found["state"] == "new" and [e["glosses"] for e in found["entries"]] == [["a gloss"]]
    asyncio.run(blocks.save_word(course, blocks.SavedWord(word=word, meaning="a gloss")))
    found = blocks.look_up(course, word)
    assert found["saved"] and found["state"] == "learning"
    asyncio.run(blocks.mark_known(course, blocks.TappedWord(word=word)))
    assert blocks.word_states(course, blocks.Words(words=[word])) == {word: "known"}
