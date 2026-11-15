import asyncio
import json
import tarfile
from functools import partial
from uuid import uuid4

import httpx
import pytest

from wise_scholar import db, morphology, resources

spacy = pytest.importorskip("spacy")
from wise_scholar.tools import language as language_tools


def _pack(tmp_path, licence: str | None = "MIT", name: str = "de_core_news_sm-3.8.0", sources: list | None = None, extra_config: bool = False):
    """A release archive as spaCy publishes one: a sentencizer and rules that tag a few German words."""
    nlp = spacy.blank("de")
    nlp.add_pipe("sentencizer")
    ruler = nlp.add_pipe("attribute_ruler")
    ruler.add([[{"LOWER": "ich"}]], {"POS": "PRON", "MORPH": "Case=Nom|Person=1"})
    ruler.add([[{"LOWER": "hätte"}]], {"POS": "AUX", "MORPH": "Mood=Sub|Tense=Past"})
    ruler.add([[{"LOWER": "zeit"}]], {"POS": "NOUN", "MORPH": "Case=Acc|Gender=Fem"})
    if licence is not None:
        nlp.meta["license"] = licence
    nlp.meta["sources"] = sources or [{"name": "Corpus", "license": "commercial (licensed by Explosion)"}]
    model = tmp_path / "build" / name / "de_core_news_sm" / name
    model.parent.mkdir(parents=True)
    nlp.to_disk(model)
    if extra_config:
        # a config deeper in the pipeline's own folders must not be taken for the pipeline
        (model / "tok2vec").mkdir(exist_ok=True)
        (model / "tok2vec" / "config.cfg").write_text("[nonsense]")
    folder = tmp_path / "folder"
    folder.mkdir()
    with tarfile.open(folder / morphology.ARCHIVE, "w:gz") as tar:
        tar.add(tmp_path / "build" / name, arcname=name)
    return folder


def test_preparing_unpacks_the_pipeline_and_loads_it(tmp_path):
    folder = _pack(tmp_path)
    morphology.prepare(folder)
    assert sorted(p.name for p in folder.iterdir()) == [morphology.MODEL]
    assert (folder / morphology.MODEL / "config.cfg").exists()


@pytest.mark.parametrize("licence, sources, problem", [
    ("CC BY-NC-SA 4.0", None, "does not allow any use"),
    (None, None, "none given"),
    ("Custom", None, "does not allow any use"),
    ("MIT", [{"name": "Treebank", "license": "CC BY-NC-SA 4.0"}], "forbids commercial use: Treebank"),
    ("MIT", [{"name": "Corpus", "license": "for non-commercial research only"}], "forbids commercial use: Corpus"),
])
def test_a_pipeline_that_does_not_allow_any_use_is_refused(tmp_path, licence, sources, problem):
    folder = _pack(tmp_path, licence=licence, sources=sources)
    with pytest.raises(ValueError, match=problem):
        morphology.prepare(folder)
    assert not (folder / morphology.MODEL).exists()


def test_the_pipeline_is_the_shallowest_config_in_the_archive(tmp_path):
    folder = _pack(tmp_path, extra_config=True)
    morphology.prepare(folder)
    assert (folder / morphology.MODEL / "tok2vec" / "config.cfg").exists()


def test_a_pipeline_installed_again_is_loaded_again(tmp_path):
    folder = _pack(tmp_path)
    morphology.prepare(folder)
    first, _ = morphology._model(folder / morphology.MODEL)
    assert morphology._model(folder / morphology.MODEL)[0] is first
    config = folder / morphology.MODEL / "config.cfg"
    stat = config.stat()
    import os
    os.utime(config, (stat.st_atime, stat.st_mtime + 10))
    assert morphology._model(folder / morphology.MODEL)[0] is not first


def test_an_archive_without_a_pipeline_is_refused(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (tmp_path / "x.txt").write_text("not a model")
    with tarfile.open(folder / morphology.ARCHIVE, "w:gz") as tar:
        tar.add(tmp_path / "x.txt", arcname="x.txt")
    with pytest.raises(ValueError, match="no spaCy pipeline"):
        morphology.prepare(folder)


def test_analysis_gives_each_word_its_features_sentence_by_sentence(tmp_path):
    folder = _pack(tmp_path)
    morphology.prepare(folder)
    sentences, cut = morphology.analyze(folder, "Ich hätte Zeit. Ich hätte Zeit.")
    assert len(sentences) == 2 and not cut
    assert morphology.analyze(folder, "Ich " * morphology.TEXT)[1]
    assert morphology.describe([[sentences[0][0]]], cut=True).endswith(f"(only the first {morphology.TEXT} characters were analysed)")
    assert sentences[0][1] == {"text": "hätte", "lemma": "", "pos": "AUX", "features": "Mood=Sub|Tense=Past", "dep": ""}
    text = morphology.describe(sentences)
    assert text.startswith("sentence 1:\n  Ich\t\tPRON\tCase=Nom|Person=1\t") and "sentence 2:" in text
    assert morphology.describe([[sentences[0][0]] * (morphology.TOKENS + 1)]).endswith(f"analyze at most {morphology.TOKENS} words at a time)")
    counts = morphology.features(folder, ["Ich hätte Zeit.", "Ich"])
    assert counts["Case=Nom"] == 2 and counts["Mood=Sub"] == 1 and counts["pos=NOUN"] == 1 and "pos=PUNCT" not in counts


def test_the_catalog_picks_the_small_pipeline_for_the_installed_spacy(monkeypatch):
    table = {"spacy": {morphology._spacy_version(): {"de_core_news_sm": ["3.8.0"], "en_core_web_sm": ["3.8.0"], "de_core_news_lg": ["3.8.0"]}}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=table))
    monkeypatch.setattr(resources.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=transport))
    assert asyncio.run(resources._morphology("de-AT", "en"))[0].url.endswith("/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0.tar.gz")
    assert asyncio.run(resources._morphology("en", "fr"))[0].url.endswith("/en_core_web_sm-3.8.0.tar.gz")
    assert asyncio.run(resources._morphology("is", "en")) == resources.MISSING
    monkeypatch.setattr(morphology, "available", lambda: False)
    assert asyncio.run(resources._morphology("de", "en")) == resources.NOT_INSTALLED


def _course(tmp_path, monkeypatch) -> int:
    monkeypatch.setattr(resources, "ROOT", tmp_path / "resources")
    profile = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid
    return db.create_course("German", profile)["id"]


def _install(tmp_path, course: int) -> None:
    folder = _pack(tmp_path)
    morphology.prepare(folder)
    target = resources.ROOT / "morphology" / "de"
    target.parent.mkdir(parents=True)
    folder.rename(target)
    db.conn.execute("INSERT INTO course_resources (course_id, kind, lang, own, key, status) VALUES (?, 'morphology', 'de', 'en', 'de', 'ready')", (course,))


def test_the_tools_answer_only_for_a_course_with_its_analyser(tmp_path, monkeypatch):
    course = _course(tmp_path, monkeypatch)
    assert asyncio.run(language_tools.analyze_text(course, "Ich hätte Zeit.")) == language_tools.NO_ANALYSER
    assert asyncio.run(language_tools.grammar_used(course)) == language_tools.NO_ANALYSER
    _install(tmp_path, course)
    assert "hätte\t\tAUX\tMood=Sub|Tense=Past" in asyncio.run(language_tools.analyze_text(course, "Ich hätte Zeit."))
    monkeypatch.setattr(morphology, "available", lambda: False)
    assert asyncio.run(language_tools.analyze_text(course, "Ich")) == language_tools.NO_ANALYSER


def test_grammar_used_reads_the_final_version_of_the_latest_written_tasks(tmp_path, monkeypatch):
    course = _course(tmp_path, monkeypatch)
    _install(tmp_path, course)
    assert asyncio.run(language_tools.grammar_used(course)) == "the learner has not written anything in this course yet"
    lesson = db.create_lesson(course, "Unit", "lesson")
    # the first draft's subjunctive was corrected away; only the final version counts
    db.add_block(lesson, "challenge", "Schreib!", {"writing": True, "attempts": ["Ich hätte Zeit.", "Ich Zeit."]})
    db.add_block(lesson, "challenge", "Sag!", {"writing": True, "spoken": True, "attempts": ["hätte hätte hätte"]})
    db.add_block(lesson, "challenge", "Code!", {"writing": False, "attempts": ["Zeit Zeit Zeit"]})
    db.add_block(lesson, "challenge", "Leer", {"writing": True, "attempts": []})
    answer = asyncio.run(language_tools.grammar_used(course))
    assert answer.startswith("over the latest 1 written tasks: ")
    counts = dict(item.rsplit(" ", 1) for item in answer.split(": ", 1)[1].split(", "))
    assert counts == {"Case=Nom": "1", "Person=1": "1", "pos=PRON": "1", "Case=Acc": "1", "Gender=Fem": "1", "pos=NOUN": "1"}


def test_only_the_latest_written_tasks_count(tmp_path, monkeypatch):
    monkeypatch.setattr(language_tools, "GRAMMAR_ATTEMPTS", 2)
    course = _course(tmp_path, monkeypatch)
    _install(tmp_path, course)
    lesson = db.create_lesson(course, "Unit", "lesson")
    for text in ("hätte", "Zeit", "Ich"):
        db.add_block(lesson, "challenge", "Schreib!", {"writing": True, "attempts": [text]})
    counts = asyncio.run(language_tools.grammar_used(course))
    assert "Mood=Sub" not in counts and "Case=Acc 1" in counts and "Case=Nom 1" in counts


def test_a_pipeline_that_will_not_load_is_reported(tmp_path, monkeypatch):
    course = _course(tmp_path, monkeypatch)
    _install(tmp_path, course)
    (resources.ROOT / "morphology" / "de" / morphology.MODEL / "config.cfg").write_text("[broken")
    assert asyncio.run(language_tools.analyze_text(course, "Ich")) == language_tools.BROKEN_ANALYSER
