import asyncio
import shutil
from collections import Counter
from functools import partial
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from wise_scholar import app as application
from wise_scholar import db, lexicon, resources
from wise_scholar.tools import language as language_tools

LEXICON = "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl"
AUDIO = "https://downloads.tatoeba.org/exports/per_language/deu/deu_sentences_with_audio.tsv.bz2"
FILES = {
    LEXICON: b'{"word": "Haus"}\n',
    "https://downloads.tatoeba.org/exports/per_language/deu/deu_sentences.tsv.bz2": b"de" * 10,
    AUDIO: b"au",
    "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2": b"en" * 5,
    "https://downloads.tatoeba.org/exports/per_language/deu/deu-eng_links.tsv.bz2": b"li",
}


@pytest.fixture
def web(tmp_path, monkeypatch):
    """Stands in for kaikki and Tatoeba: serves FILES and 404 for anything else; fails the URLs in `broken`, fails only
    the downloads (not the size checks) of those in `cut`, answers those in `missing` with 404, and counts each GET."""
    broken, missing, gets, cut = set(), set(), Counter(), set()

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in broken or (url in cut and request.method == "GET"):
            raise httpx.ConnectError("down", request=request)
        body = None if url in missing else FILES.get(url)
        if body is None:
            return httpx.Response(404)
        if request.method == "GET":
            gets[url] += 1
        return httpx.Response(200, headers={"content-length": str(len(body))}, content=b"" if request.method == "HEAD" else body)

    monkeypatch.setattr(resources, "ROOT", tmp_path / "resources")
    monkeypatch.setattr(resources.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(answer)))
    return broken, missing, gets, cut


def _course(locale: str = "en") -> int:
    profile = db.conn.execute("INSERT INTO profiles (name, locale) VALUES (?, ?)", (f"P {uuid4()}", locale)).lastrowid
    return db.create_course("German", profile)["id"]


def _row(course: int, kind: str) -> dict:
    return db.row("SELECT * FROM course_resources WHERE course_id = ? AND kind = ?", course, kind)


async def _settle() -> None:
    while resources._running:
        await asyncio.gather(*resources._running.values())


def test_the_catalog_names_each_source_by_language():
    assert resources.CATALOG["lexicon"].files("pt-BR", "en")[0].url == "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl"
    assert resources.CATALOG["sentences"].key("de-AT", "fr") == "de-fr"
    assert [s.name for s in resources.CATALOG["sentences"].files("fr", "fr")] == ["sentences.tsv.bz2", "audio.tsv.bz2"]
    # Tatoeba files Chinese under Mandarin and Persian under Iranian Persian
    assert resources.CATALOG["sentences"].files("zh", "fa")[0].url.endswith("/cmn/cmn_sentences.tsv.bz2")
    assert resources.CATALOG["sentences"].files("zh", "fa")[-1].url.endswith("/cmn/cmn-pes_links.tsv.bz2")


def test_offering_records_sizes_and_says_why_a_kind_is_not_offered(web):
    broken, missing, _, _ = web
    course = _course()
    assert asyncio.run(resources.offer(course, "de", "en")) == {"lexicon": "asked", "sentences": "asked"}
    assert _row(course, "lexicon")["size"] == 17 and _row(course, "sentences")["size"] == 34
    assert asyncio.run(resources.offer(_course(), "tlh", "en")) == {"lexicon": resources.MISSING, "sentences": resources.MISSING}
    broken.add(LEXICON)
    assert asyncio.run(resources.offer(_course(), "de", "en"))["lexicon"] == resources.UNREACHABLE
    missing.add(AUDIO)
    without_audio = _course()
    assert asyncio.run(resources.offer(without_audio, "de", "en"))["sentences"] == "asked"
    assert _row(without_audio, "sentences")["size"] == 32


def test_one_download_serves_every_course_waiting_on_it(web):
    _, _, gets, _ = web
    first, second = _course(), _course()

    async def run():
        await resources.offer(first, "de", "en")
        await resources.offer(second, "de", "en")
        resources.decide(first, "sentences", True)
        resources.decide(second, "sentences", True)
        await _settle()

    asyncio.run(run())
    assert _row(first, "sentences")["status"] == _row(second, "sentences")["status"] == "ready"
    assert set(gets.values()) == {1} and len(gets) == 4
    path = resources.course_resource(first, "sentences")
    assert path == resources.ROOT / "sentences" / "de-en" and (path / "links.tsv.bz2").read_bytes() == b"li"
    assert resources.course_resource(first, "sentences", "fr") is None and resources.course_resource(first, "lexicon") is None
    assert asyncio.run(resources.offer(_course(), "de-DE", "en"))["sentences"] == "ready"


def test_a_failure_fails_every_waiting_course_leaves_nothing_behind_and_can_be_retried(web):
    _, _, _, cut = web
    first, second = _course(), _course()

    async def attempt():
        resources.decide(first, "lexicon", True)
        resources.decide(second, "lexicon", True)
        await _settle()

    asyncio.run(resources.offer(first, "de", "en"))
    asyncio.run(resources.offer(second, "de", "en"))
    cut.add(LEXICON)
    asyncio.run(attempt())
    assert _row(first, "lexicon")["status"] == _row(second, "lexicon")["status"] == "failed"
    assert "down" in _row(second, "lexicon")["error"]
    assert list((resources.ROOT / "lexicon").iterdir()) == []
    cut.discard(LEXICON)
    asyncio.run(attempt())
    assert _row(first, "lexicon")["status"] == _row(second, "lexicon")["status"] == "ready"
    assert [p.name for p in (resources.ROOT / "lexicon").iterdir()] == ["de"]
    # the lexicon is read from its database, made while downloading; the raw file goes
    assert sorted(p.name for p in (resources.ROOT / "lexicon" / "de").iterdir()) == ["lexicon.db", "source.json"]
    assert [e["word"] for e in lexicon.lookup(resources.ROOT / "lexicon" / "de", "haus")] == ["Haus"]


def test_a_source_that_is_not_a_lexicon_fails_the_download(web, monkeypatch):
    monkeypatch.setitem(FILES, LEXICON, b"<html>gateway error</html>")
    course = _course()

    async def run():
        await resources.offer(course, "de", "en")
        resources.decide(course, "lexicon", True)
        await _settle()

    asyncio.run(run())
    assert _row(course, "lexicon")["status"] == "failed" and "no entries" in _row(course, "lexicon")["error"]
    assert list((resources.ROOT / "lexicon").iterdir()) == []


def test_a_course_joining_a_download_takes_its_progress(web):
    first, second = _course(), _course()
    asyncio.run(resources.offer(first, "de", "en"))
    asyncio.run(resources.offer(second, "de", "en"))
    db.conn.execute("UPDATE course_resources SET status = 'downloading', done = 9 WHERE course_id = ? AND kind = 'lexicon'", (first,))
    resources._running[("lexicon", "de")] = None
    try:
        resources.decide(second, "lexicon", True)
    finally:
        resources._running.clear()
    assert _row(second, "lexicon")["done"] == 9


def test_offering_again_keeps_a_refusal_and_a_download_under_way_but_not_a_deleted_folder(web):
    course = _course()
    asyncio.run(resources.offer(course, "de", "en"))
    resources.decide(course, "lexicon", False)
    db.conn.execute("UPDATE course_resources SET status = 'downloading', done = 5 WHERE course_id = ? AND kind = 'sentences'", (course,))
    assert asyncio.run(resources.offer(course, "de", "en")) == {"lexicon": "refused", "sentences": "downloading"}
    assert _row(course, "sentences")["done"] == 5
    (resources.ROOT / "sentences" / "de-en").mkdir(parents=True)
    db.conn.execute("UPDATE course_resources SET status = 'ready' WHERE course_id = ? AND kind = 'sentences'", (course,))
    shutil.rmtree(resources.ROOT / "sentences" / "de-en")
    assert asyncio.run(resources.offer(course, "de", "en"))["sentences"] == "asked"


def test_a_restart_fails_downloads_in_flight_and_clears_their_parts(web):
    course = _course()
    asyncio.run(resources.offer(course, "de", "en"))
    db.conn.execute("UPDATE course_resources SET status = 'downloading' WHERE course_id = ?", (course,))
    (resources.ROOT / "lexicon" / ".de.part").mkdir(parents=True)
    resources.interrupted()
    assert _row(course, "lexicon")["status"] == "failed" and _row(course, "lexicon")["error"] == "the server restarted"
    assert not (resources.ROOT / "lexicon" / ".de.part").exists()


def test_the_learner_decides_once_through_the_api(web, monkeypatch):
    started = []

    async def fetch(*args):
        started.append(args)

    monkeypatch.setattr(resources, "_fetch", fetch)
    client = TestClient(application.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)
    course = _course()
    asyncio.run(resources.offer(course, "de", "en"))
    assert client.post(f"/api/courses/{course}/resources/grammar", json={"allow": True}).status_code == 404
    answer = client.post(f"/api/courses/{course}/resources/lexicon", json={"allow": False})
    assert {r["kind"]: r["status"] for r in answer.json()["resources"]} == {"lexicon": "refused", "sentences": "asked"}
    assert client.post(f"/api/courses/{course}/resources/lexicon", json={"allow": True}).status_code == 409
    allowed = client.post(f"/api/courses/{course}/resources/sentences", json={"allow": True}).json()["resources"]
    assert {r["kind"]: r["status"] for r in allowed}["sentences"] == "downloading"
    assert started == [("sentences", "de-en", "de", "en")]
    resources._running.clear()
    assert {r["kind"] for r in client.get(f"/api/courses/{course}").json()["resources"]} == {"lexicon", "sentences"}


def test_the_tutor_offers_with_a_language_code(web):
    course = _course()
    assert asyncio.run(language_tools.offer_resources(course, "not a language!")).startswith("error:")
    assert asyncio.run(language_tools.offer_resources(course, "de")) == "lexicon: asked; sentences: asked"
