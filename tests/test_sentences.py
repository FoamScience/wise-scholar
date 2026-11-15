import asyncio
import bz2
import json
from uuid import uuid4

import pytest

from wise_scholar import db, lexicon, resources, sentences, vocab
from wise_scholar.tools import language as language_tools

GERMAN = [
    (1, "Das Haus ist alt."),
    (2, "Der Haushalt ist teuer und die Verwaltung der Gemeinde bespricht ihn jede Woche."),
    (3, "Die Häuser sind groß."),
    (4, "Ich bin zu Hause."),
    (5, "Er ist da."),
    (6, "Wir verhandeln über die Unabhängigkeitserklärung des Hauses."),
]


def _write(folder, name, rows):
    folder.joinpath(name).write_bytes(bz2.compress("".join("\t".join(map(str, r)) + "\n" for r in rows).encode()))


def _sentences(folder, german=GERMAN):
    folder.mkdir(parents=True)
    _write(folder, "sentences.tsv.bz2", [(i, "deu", t) for i, t in german] + [("x", "deu", "bad id"), (99, "deu", "")])
    _write(folder, "translations.tsv.bz2", [(101, "eng", "The house is old."), (103, "eng", "The houses are big."), (500, "eng", "unlinked")])
    _write(folder, "links.tsv.bz2", [(1, 101), (3, 103), (1, 999)])
    # only sentence 1's recording allows any use: 3 has no licence (Tatoeba writes \\N), 4 forbids commercial use,
    # 5 is under a licence of its own
    _write(folder, "audio.tsv.bz2", [(1, 77, "anna", "CC BY 4.0", "u"), (3, 78, "ben", "\\N", "\\N"), (4, 79, "cem", "CC BY-NC 4.0", "u"),
                                     (5, 80, "dan", "Attribution NonCommercial", "u")])
    sentences.prepare(folder)
    return folder


def test_preparing_pairs_each_sentence_with_a_translation_and_a_licensed_recording(tmp_path):
    folder = _sentences(tmp_path / "s")
    assert sorted(p.name for p in folder.iterdir()) == [sentences.DB]
    [house] = sentences.find(folder, ["Das Haus"])
    assert house == {"id": 1, "text": "Das Haus ist alt.", "translation": "The house is old.", "audio": 77, "audio_by": "anna", "audio_license": "CC BY 4.0"}
    [houses] = sentences.find(folder, ["häuser"])
    assert houses["translation"] == "The houses are big." and houses["audio"] is None
    assert all(s["audio"] is None for s in sentences.find(folder, ["zu Hause", "Er ist"]))


def test_any_word_is_found_whatever_its_length_or_case(tmp_path):
    folder = _sentences(tmp_path / "s")
    assert {s["id"] for s in sentences.find(folder, ["HAUS"])} == {1, 2, 4, 6}
    assert {s["id"] for s in sentences.find(folder, ["GROSS", "GROß"])} == {3}
    assert {s["id"] for s in sentences.find(folder, ["Ä"])} == {3, 6}
    # a short word goes by a scan, as a substring like the rest
    assert {s["id"] for s in sentences.find(folder, ["da"])} == {1, 5}
    assert sentences.find(folder, ["Katze", "  "]) == []


def test_a_source_with_no_sentences_fails(tmp_path):
    folder = tmp_path / "s"
    folder.mkdir()
    _write(folder, "sentences.tsv.bz2", [("<html>",)])
    with pytest.raises(ValueError, match="no sentences"):
        sentences.prepare(folder)


def _course(tmp_path, monkeypatch, with_lexicon: bool) -> int:
    monkeypatch.setattr(resources, "ROOT", tmp_path)
    profile = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid
    course = db.create_course("German", profile)["id"]
    # at B1 every plain word here is in the learner's range; only the long compounds are not
    db.conn.execute("UPDATE courses SET level = 'B1' WHERE id = ?", (course,))
    _sentences(tmp_path / "sentences" / "de-en")
    db.conn.execute("INSERT INTO course_resources (course_id, kind, lang, own, key, status) VALUES (?, 'sentences', 'de', 'en', 'de-en', 'ready')", (course,))
    if with_lexicon:
        folder = tmp_path / "lexicon" / "de"
        folder.mkdir(parents=True)
        entry = {"word": "Haus", "pos": "noun", "forms": [{"form": "Häuser", "tags": ["plural"]}, {"form": "Hause", "tags": ["dative"]}],
                 "senses": [{"glosses": ["house"]}]}
        (folder / lexicon.RAW).write_text(json.dumps(entry, ensure_ascii=False) + "\n")
        lexicon.prepare(folder)
        db.conn.execute("INSERT INTO course_resources (course_id, kind, lang, own, key, status) VALUES (?, 'lexicon', 'de', 'en', 'de', 'ready')", (course,))
    return course


def _ranked(course: int, word: str) -> list[str]:
    lines = asyncio.run(language_tools.example_sentences(course, word, n=10)).splitlines()
    return [line.split(". ", 1)[1] for line in lines if line[:1].isdigit()]


def test_the_word_as_a_word_comes_before_longer_words_that_hold_it(tmp_path, monkeypatch):
    # no lemmatizer and no word list: only the matching itself decides
    monkeypatch.setattr(vocab, "supported", lambda lang: False)
    course = _course(tmp_path, monkeypatch, with_lexicon=False)
    ranked = _ranked(course, "Haus")
    assert ranked[0] == "Das Haus ist alt." and set(ranked[1:]) == {GERMAN[1][1], GERMAN[3][1], GERMAN[5][1]}
    assert asyncio.run(language_tools.example_sentences(course, "Haus", n=1)) == (
        "1. Das Haus ist alt.\n   = The house is old.\n   audio: https://tatoeba.org/audio/download/77 (by anna, CC BY 4.0)\n" + sentences.CREDIT
    )


def test_with_a_lexicon_the_forms_of_the_word_count_as_the_word(tmp_path, monkeypatch):
    monkeypatch.setattr(vocab, "supported", lambda lang: False)
    course = _course(tmp_path, monkeypatch, with_lexicon=True)
    ranked = _ranked(course, "Haus")
    # Haus and its forms Häuser and Hause as words, the translated one first, then the rest by shortness
    assert ranked[:3] == ["Das Haus ist alt.", "Die Häuser sind groß.", "Ich bin zu Hause."]
    assert set(ranked[3:]) == {GERMAN[1][1], GERMAN[5][1]}


def test_a_translated_sentence_comes_before_one_the_learner_reads_more_easily(tmp_path, monkeypatch):
    course = _course(tmp_path, monkeypatch, with_lexicon=False)
    db.conn.execute("UPDATE courses SET level = 'A1' WHERE id = ?", (course,))
    # Das Haus ist alt (translated) holds a word above A1, Ich bin zu Hause (not translated) does not
    assert _ranked(course, "Haus")[:2] == ["Das Haus ist alt.", "Ich bin zu Hause."]


def test_the_tool_says_when_it_has_nothing(tmp_path, monkeypatch):
    profile = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid
    bare = db.create_course("German", profile)["id"]
    assert asyncio.run(language_tools.example_sentences(bare, "Haus")).startswith("example sentences are not set up")
    course = _course(tmp_path, monkeypatch, with_lexicon=False)
    assert asyncio.run(language_tools.example_sentences(course, "Katze")) == "no sentence uses 'Katze'"
