import asyncio
import json
import sqlite3
import unicodedata
from uuid import uuid4

import pytest

from wise_scholar import db, lexicon, resources
from wise_scholar.tools import language as language_tools

HAUS = {
    "word": "Haus", "pos": "noun", "lang_code": "de",
    "head_templates": [{"name": "de-noun", "expansion": "Haus n (strong, genitive Hauses, plural Häuser)"}],
    "sounds": [{"ipa": "/haʊ̯s/"}, {"audio": "De-Haus.ogg"}],
    "forms": [
        {"form": "Hauses", "tags": ["genitive"]}, {"form": "Häuser", "tags": ["plural"]}, {"form": "Häuser", "tags": ["plural"]},
        {"form": "strong", "tags": ["table-tags"]}, {"form": "de-ndecl", "tags": ["inflection-template"]},
    ],
    "senses": [{"glosses": ["house"], "tags": ["neuter", "strong"]}, {"glosses": ["home", "household"], "tags": ["neuter"]}],
}
HAEUSER = {
    "word": "Häuser", "pos": "noun",
    "senses": [{"glosses": ["nominative plural of Haus"], "form_of": [{"word": "Haus"}], "tags": ["form-of", "nominative", "plural"]}],
}
HAUS_VERB = {"word": "hausen", "pos": "verb", "senses": [{"glosses": ["to dwell"]}]}


# lines a real dump or a broken download can hold, none of them an entry
JUNK = ["not json", "[1, 2]", '"a string"', "42", "null", '{"word": 7}', '{"word": "  "}', '{"pos": "noun"}']
ODD = {"word": "odd", "pos": None, "senses": None, "forms": [None, "x", {"form": 3}], "sounds": "no", "head_templates": [{"expansion": None}]}


def _lexicon(tmp_path, entries=(HAUS, HAEUSER, HAUS_VERB), junk=JUNK):
    folder = tmp_path / "lex"
    folder.mkdir()
    lines = [json.dumps(e, ensure_ascii=False) for e in entries] + junk
    (folder / lexicon.RAW).write_bytes(("\n".join(lines) + "\n").encode() + b"\xff\xfe broken utf-8\n")
    lexicon.prepare(folder)
    return folder


def _count(folder) -> int:
    with sqlite3.connect(folder / lexicon.DB) as connection:
        return connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]


def test_preparing_keeps_each_entrys_wiktionary_fields_and_drops_the_raw_file(tmp_path):
    folder = _lexicon(tmp_path, entries=(HAUS, HAEUSER, HAUS_VERB, ODD))
    assert not (folder / lexicon.RAW).exists()
    assert _count(folder) == 4
    [odd] = lexicon.lookup(folder, "odd")
    assert (odd["pos"], odd["head"], odd["forms"], odd["glosses"]) == ("", "odd", [], [])
    [haus] = lexicon.lookup(folder, "Haus")
    assert haus["head"] == "Haus n (strong, genitive Hauses, plural Häuser)" and haus["ipa"] == "/haʊ̯s/"
    assert haus["tags"] == ["neuter", "strong"] and haus["glosses"] == ["house", "home; household"]
    assert haus["forms"] == [["Hauses", ["genitive"]], ["Häuser", ["plural"]]]


def test_a_form_leads_to_its_word_whatever_its_case(tmp_path):
    folder = _lexicon(tmp_path)
    assert [e["word"] for e in lexicon.lookup(folder, "häuser")] == ["Häuser", "Haus"]
    assert lexicon.lookup(folder, "Hütte") == []


def test_the_tutor_reads_an_entry_whole(tmp_path):
    [haus] = lexicon.lookup(_lexicon(tmp_path), "Haus")
    assert lexicon.describe(haus) == (
        "Haus n (strong, genitive Hauses, plural Häuser) [noun] /haʊ̯s/\n"
        "tags: neuter, strong\n"
        "1. house\n"
        "2. home; household\n"
        "forms: Hauses (genitive); Häuser (plural)"
    )


def test_lookup_word_answers_only_for_a_course_with_its_lexicon(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "ROOT", tmp_path)
    profile = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid
    course = db.create_course("German", profile)["id"]
    assert asyncio.run(language_tools.lookup_word(course, "Haus")).startswith("the lexicon is not set up")
    folder = tmp_path / "lexicon" / "de"
    folder.parent.mkdir()
    _lexicon(tmp_path).rename(folder)
    db.conn.execute(
        "INSERT INTO course_resources (course_id, kind, lang, own, key, status) VALUES (?, 'lexicon', 'de', 'en', 'de', 'ready')", (course,))
    assert asyncio.run(language_tools.lookup_word(course, " häuser ")) == (
        "Häuser [noun]\ntags: nominative, plural\nform of: Haus\n1. nominative plural of Haus\n\n"
        "Haus n (strong, genitive Hauses, plural Häuser) [noun] /haʊ̯s/\ntags: neuter, strong\n1. house\n2. home; household\n"
        "forms: Hauses (genitive); Häuser (plural)"
    )
    assert asyncio.run(language_tools.lookup_word(course, "Hütte")) == "'Hütte' is not in the lexicon"


def test_a_source_with_no_entries_fails_and_leaves_no_database(tmp_path):
    folder = tmp_path / "lex"
    folder.mkdir()
    (folder / lexicon.RAW).write_text("<html>502 Bad Gateway</html>\n")
    with pytest.raises(ValueError, match="no entries"):
        lexicon.prepare(folder)
    assert (folder / lexicon.RAW).exists()


def test_cut_forms_and_long_answers_say_what_they_leave_out(tmp_path):
    many = {"word": "big", "pos": "verb", "forms": [{"form": f"big{n}", "tags": ["x"]} for n in range(lexicon.FORMS + 5)],
            "senses": [{"glosses": ["g" * 1000]}]}
    homographs = [{"word": "set", "pos": f"pos{n}", "senses": [{"glosses": [str(n)]}]} for n in range(lexicon.ENTRIES + 3)]
    folder = _lexicon(tmp_path, entries=(many, *homographs))
    [big] = lexicon.lookup(folder, "big")
    assert len(big["glosses"][0]) == lexicon.TEXT
    assert lexicon.describe(big).endswith("(and 5 more forms not listed)")
    answer = lexicon.answer(lexicon.lookup(folder, "set"))
    assert answer.count("[pos") == lexicon.ENTRIES and answer.endswith("(3 more entries not shown)")


def test_each_entry_comes_once_and_any_unicode_composition_finds_it(tmp_path):
    lower = {"word": "haus", "pos": "noun", "senses": [{"glosses": ["variant"], "form_of": [{"word": "haus"}, {"word": "Haus"}]}]}
    folder = _lexicon(tmp_path, entries=(HAUS, HAEUSER, lower))
    found = lexicon.lookup(folder, "haus")
    assert sorted(e["word"] for e in found) == ["Haus", "haus"]
    decomposed = unicodedata.normalize("NFD", "Häuser")
    assert decomposed != "Häuser" and [e["word"] for e in lexicon.lookup(folder, decomposed)] == ["Häuser", "Haus", "haus"]
