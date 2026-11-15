"""Open data for the language a course teaches, offered to the learner at course setup. Each resource is downloaded once
into data/resources/<kind>/<key> and shared by every course that needs the same one; a course only records whether
its learner allowed it."""
import asyncio
import json
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
import langcodes

from . import db, hub, lexicon, sentences

log = logging.getLogger("wise_scholar")
ROOT = db.DB_PATH.parent / "resources"
KAIKKI = "https://kaikki.org/dictionary/{dir}/kaikki.org-dictionary-{file}.jsonl"
TATOEBA = "https://downloads.tatoeba.org/exports/per_language/{lang}/{file}"
# Tatoeba files a macrolanguage under its most spoken member
TATOEBA_CODES = {"zho": "cmn", "fas": "pes", "msa": "zsm", "swa": "swh", "lav": "lvs", "nor": "nob"}
CHUNK = 1 << 20
# progress reaches the page at most this often per course
PUBLISH_SECONDS = 1.0
UNREACHABLE = "source unreachable, offer again later"
MISSING = "none for this language"


@dataclass(frozen=True)
class Source:
    url: str
    name: str
    # a resource is offered without the files it can do without
    required: bool = True


@dataclass(frozen=True)
class Kind:
    # the folder a language (and the learner's own language) shares
    key: Callable[[str, str], str]
    files: Callable[[str, str], list[Source]]
    # turns the downloaded files into what the tools read, before the folder counts as installed
    prepare: Callable[[Path], None] | None = None


def code(lang: str) -> str:
    """The base language of a tag: 'de' for 'de-AT'."""
    return langcodes.Language.get(lang).language


def _tatoeba(lang: str) -> str:
    alpha3 = langcodes.Language.get(lang).to_alpha3()
    return TATOEBA_CODES.get(alpha3, alpha3)


def _lexicon(lang: str, own: str) -> list[Source]:
    # kaikki names its folders by the English name of the language and its files by that name without spaces or hyphens
    name = langcodes.Language.get(lang).language_name("en")
    return [Source(KAIKKI.format(dir=quote(name), file=quote(name.replace(" ", "").replace("-", ""))), "lexicon.jsonl")]


def _sentences(lang: str, own: str) -> list[Source]:
    a, b = _tatoeba(lang), _tatoeba(own)
    files = [Source(TATOEBA.format(lang=a, file=f"{a}_sentences.tsv.bz2"), "sentences.tsv.bz2"),
             Source(TATOEBA.format(lang=a, file=f"{a}_sentences_with_audio.tsv.bz2"), "audio.tsv.bz2", required=False)]
    if a != b:
        files += [Source(TATOEBA.format(lang=b, file=f"{b}_sentences.tsv.bz2"), "translations.tsv.bz2"),
                  Source(TATOEBA.format(lang=a, file=f"{a}-{b}_links.tsv.bz2"), "links.tsv.bz2")]
    return files


CATALOG = {
    "lexicon": Kind(lambda lang, own: code(lang), _lexicon, lexicon.prepare),
    "sentences": Kind(lambda lang, own: f"{code(lang)}-{code(own)}", _sentences, sentences.prepare),
}
# one download per shared folder, whichever courses wait on it
_running: dict[tuple[str, str], asyncio.Task] = {}


def folder(kind: str, key: str) -> Path:
    return ROOT / kind / key


def _part(kind: str, key: str) -> Path:
    return ROOT / kind / f".{key}.part"


def course_resource(course_id: int, kind: str, lang: str | None = None) -> Path | None:
    """Where a resource the course's learner allowed is installed, for its language or the one given; None otherwise."""
    row = db.row("SELECT * FROM course_resources WHERE course_id = ? AND kind = ? AND status = 'ready'", course_id, kind)
    if not row or (lang and code(lang) != row["lang"]):
        return None
    path = folder(kind, row["key"])
    return path if path.is_dir() else None


def view(course_id: int) -> list[dict]:
    """The course's resources; `prepares` says the page shows a finished download as being prepared."""
    return [{**r, "prepares": CATALOG[r["kind"]].prepare is not None} for r in db.rows(
        "SELECT kind, lang, size, status, done, error FROM course_resources WHERE course_id = ? ORDER BY kind", course_id)]


def _publish(course_id: int) -> None:
    hub.publish(course_id, {"type": "resources.updated", "resources": view(course_id)})


async def _size(client: httpx.AsyncClient, url: str) -> int | str | None:
    """The download's size in bytes as sent, None when the source does not say, or MISSING or UNREACHABLE."""
    try:
        response = await client.head(url)
    except httpx.HTTPError as e:
        log.warning("resource size of %s: %s", url, e)
        return UNREACHABLE
    if response.status_code == 404:
        return MISSING
    if not response.is_success:
        log.warning("resource size of %s: HTTP %s", url, response.status_code)
        return UNREACHABLE
    length = response.headers.get("content-length")
    return int(length) if length else None


async def _files(client: httpx.AsyncClient, spec: Kind, lang: str, own: str) -> tuple[list[Source], int | None] | str:
    """The files to fetch and their total size (None when a source does not say), or why there are none."""
    files, total = [], 0
    for source in spec.files(lang, own):
        size = await _size(client, source.url)
        if size == MISSING and not source.required:
            continue
        if isinstance(size, str):
            return size
        files.append(source)
        total = None if total is None or size is None else total + size
    return files, total


async def offer(course_id: int, lang: str, own: str) -> dict[str, str]:
    """Records each resource the catalog has for the language as offered to the course; one already installed is
    ready at once. A download under way or a refusal stands. Returns each kind's outcome."""
    lang, own = code(lang), code(own)
    outcome = {}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for kind, spec in CATALOG.items():
            key = spec.key(lang, own)
            if folder(kind, key).is_dir():
                status, size = "ready", None
            else:
                found = await _files(client, spec, lang, own)
                if isinstance(found, str):
                    outcome[kind] = found
                    continue
                status, size = "asked", found[1]
            db.conn.execute(
                "INSERT INTO course_resources (course_id, kind, lang, own, key, size, status) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(course_id, kind) DO UPDATE SET lang = excluded.lang, own = excluded.own, key = excluded.key, "
                "size = excluded.size, status = excluded.status, done = 0, error = NULL "
                "WHERE NOT (course_resources.key = excluded.key AND course_resources.status IN ('refused', 'downloading'))",
                (course_id, kind, lang, own, key, size, status),
            )
            outcome[kind] = db.row("SELECT status FROM course_resources WHERE course_id = ? AND kind = ?", course_id, kind)["status"]
    _publish(course_id)
    return outcome


def _waiting(kind: str, key: str) -> list[int]:
    return [r["course_id"] for r in db.rows(
        "SELECT course_id FROM course_resources WHERE kind = ? AND key = ? AND status = 'downloading'", kind, key)]


def _set(kind: str, key: str, **values) -> None:
    """Updates every course waiting on this resource and tells their pages."""
    courses = _waiting(kind, key)
    db.conn.execute(
        f"UPDATE course_resources SET {', '.join(f'{k} = ?' for k in values)} WHERE kind = ? AND key = ? AND status = 'downloading'",
        (*values.values(), kind, key),
    )
    for course_id in courses:
        _publish(course_id)


def _all_in(kind: str, key: str) -> None:
    """Every waiting course shows its download complete, while what was downloaded is prepared."""
    db.conn.execute("UPDATE course_resources SET done = COALESCE(size, done) WHERE kind = ? AND key = ? AND status = 'downloading'", (kind, key))
    for course_id in _waiting(kind, key):
        _publish(course_id)


async def _download(kind: str, key: str, files: list[Source]) -> None:
    part = _part(kind, key)
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    done, last = 0, 0.0
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=300)) as client:
        for source in files:
            async with client.stream("GET", source.url) as response:
                response.raise_for_status()
                with open(part / source.name, "wb") as out:
                    async for chunk in response.aiter_bytes(CHUNK):
                        out.write(chunk)
                        if time.monotonic() - last > PUBLISH_SECONDS:
                            last = time.monotonic()
                            # bytes as sent, as the offered size counts them: sources may send them compressed
                            _set(kind, key, done=done + response.num_bytes_downloaded)
                done += response.num_bytes_downloaded
    if prepare := CATALOG[kind].prepare:
        _all_in(kind, key)
        await asyncio.to_thread(prepare, part)
    (part / "source.json").write_text(json.dumps({"files": [s.url for s in files]}))
    part.rename(folder(kind, key))


async def _fetch(kind: str, key: str, lang: str, own: str) -> None:
    try:
        if not folder(kind, key).is_dir():
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                found = await _files(client, CATALOG[kind], lang, own)
            if isinstance(found, str):
                _set(kind, key, status="failed", error=found)
                return
            await _download(kind, key, found[0])
        _set(kind, key, status="ready", done=0)
    except Exception as e:
        log.warning("resource %s/%s failed: %s", kind, key, e)
        shutil.rmtree(_part(kind, key), ignore_errors=True)
        _set(kind, key, status="failed", error=str(e)[:300])
    finally:
        _running.pop((kind, key), None)


def decide(course_id: int, kind: str, allow: bool) -> None:
    """The learner's answer to an offered resource: refused, or downloaded in the background, joining a download of the
    same folder that another course already started."""
    row = db.row("SELECT * FROM course_resources WHERE course_id = ? AND kind = ?", course_id, kind)
    if not allow:
        db.conn.execute("UPDATE course_resources SET status = 'refused' WHERE course_id = ? AND kind = ?", (course_id, kind))
        _publish(course_id)
        return
    # a course joining a download under way takes its progress
    db.conn.execute(
        "UPDATE course_resources SET status = 'downloading', error = NULL, done = COALESCE((SELECT MAX(o.done) FROM course_resources o "
        "WHERE o.kind = course_resources.kind AND o.key = course_resources.key AND o.status = 'downloading'), 0) "
        "WHERE course_id = ? AND kind = ?",
        (course_id, kind),
    )
    _publish(course_id)
    if (kind, row["key"]) not in _running:
        _running[(kind, row["key"])] = asyncio.create_task(_fetch(kind, row["key"], row["lang"], row["own"]))


def interrupted() -> None:
    """A download cut by a server stop never finishes: its rows fail, so the learner can try again, and its
    half-written folder goes."""
    db.conn.execute("UPDATE course_resources SET status = 'failed', error = 'the server restarted' WHERE status = 'downloading'")
    for part in ROOT.glob("*/.*.part"):
        shutil.rmtree(part, ignore_errors=True)
