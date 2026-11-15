"""Tatoeba sentences in one language with their translation into the learner's language, reduced from Tatoeba's
per-language exports to a SQLite file with a full-text index. The trigram index finds words in any script."""
import bz2
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

DB = "sentences.db"
RAW = ("sentences.tsv.bz2", "translations.tsv.bz2", "links.tsv.bz2", "audio.tsv.bz2")
AUDIO_URL = "https://tatoeba.org/audio/download/{id}"
CREDIT = "Sentences from Tatoeba (tatoeba.org), CC BY 2.0 FR"
# Recordings are kept only under a licence that allows any use, commercial included: CC0, CC BY and CC BY-SA. Anything
# else, an NC licence or none at all, keeps a recording out.
OPEN_LICENCE = re.compile(r"CC(0| BY(-SA)?)( \d\.\d)?", re.IGNORECASE)
# the trigram index needs this many characters; shorter words are found by a scan
TRIGRAM = 3
CANDIDATES = 400
# each form of a word gets at least this many of the candidates
PER_FORM = 50
TEXT = 300
BATCH = 5000
SCHEMA = """
CREATE TABLE sentences (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    folded TEXT NOT NULL,
    translation TEXT,
    audio INTEGER,
    audio_by TEXT,
    audio_license TEXT
);
CREATE TEMP TABLE links (id INTEGER NOT NULL, other INTEGER NOT NULL);
CREATE TEMP TABLE translations (id INTEGER PRIMARY KEY, text TEXT NOT NULL);
CREATE TEMP TABLE audio (id INTEGER PRIMARY KEY, audio INTEGER NOT NULL, audio_by TEXT, audio_license TEXT);
"""
# a sentence takes the translation of any sentence it is linked to that the learner's language has
JOIN = """
INSERT INTO sentences
SELECT s.id, s.text, s.folded,
       (SELECT t.text FROM links l JOIN translations t ON t.id = l.other WHERE l.id = s.id ORDER BY t.id LIMIT 1),
       a.audio, a.audio_by, a.audio_license
FROM staged s LEFT JOIN audio a ON a.id = s.id
"""


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _rows(path: Path) -> Iterator[list[str]]:
    """The tab-separated fields of each line of a bz2 export, with Tatoeba's \\N for a missing value made empty; a
    missing file has none."""
    if not path.exists():
        return
    with bz2.open(path, "rt", encoding="utf-8", errors="replace") as lines:
        for line in lines:
            yield ["" if f == "\\N" else f for f in line.rstrip("\n").split("\t")]


def _load(connection: sqlite3.Connection, table: str, rows: Iterator[tuple]) -> int:
    marks = ", ".join("?" * len(connection.execute(f"SELECT * FROM {table} LIMIT 0").description))
    count, batch = 0, []
    for row in rows:
        batch.append(row)
        if len(batch) >= BATCH:
            connection.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({marks})", batch)
            count += len(batch)
            batch.clear()
    connection.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({marks})", batch)
    return count + len(batch)


def prepare(folder: Path) -> None:
    """Builds the sentence database from the downloaded exports and drops them. The exports are staged in SQLite and
    joined there, so a large language pair never sits in memory. Fails when the sentences file holds none, as an
    error page or a cut download would."""
    target = folder / DB
    target.unlink(missing_ok=True)
    with closing(sqlite3.connect(target)) as connection:
        connection.executescript(
            "PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;" + SCHEMA
            + "CREATE TEMP TABLE staged (id INTEGER PRIMARY KEY, text TEXT NOT NULL, folded TEXT NOT NULL);"
        )
        staged = _load(connection, "staged", (
            (int(f[0]), text, fold(text)) for f in _rows(folder / "sentences.tsv.bz2")
            if len(f) >= 3 and f[0].isdigit() and (text := unicodedata.normalize("NFC", f[2].strip()[:TEXT]))
        ))
        if not staged:
            raise ValueError("the sentences file held no sentences")
        _load(connection, "links", ((int(f[0]), int(f[1])) for f in _rows(folder / "links.tsv.bz2")
                                    if len(f) >= 2 and f[0].isdigit() and f[1].isdigit()))
        connection.execute("CREATE INDEX temp.links_id ON links(id)")
        _load(connection, "translations", ((int(f[0]), f[2][:TEXT]) for f in _rows(folder / "translations.tsv.bz2")
                                           if len(f) >= 3 and f[0].isdigit() and f[2].strip()))
        _load(connection, "audio", ((int(f[0]), int(f[1]), f[2], f[3]) for f in _rows(folder / "audio.tsv.bz2")
                                    if len(f) >= 4 and f[0].isdigit() and f[1].isdigit() and OPEN_LICENCE.fullmatch(f[3].strip())))
        connection.execute(JOIN)
        connection.executescript(
            "CREATE VIRTUAL TABLE sentence_text USING fts5(folded, content='sentences', content_rowid='id', tokenize='trigram');"
            "INSERT INTO sentence_text(sentence_text) VALUES ('rebuild');"
        )
        connection.commit()
    for name in RAW:
        (folder / name).unlink(missing_ok=True)


# the most useful sentences first among the matches: translated, recorded, short
ORDER = "ORDER BY s.translation IS NULL, s.audio IS NULL, length(s.text) LIMIT ?"


def find(folder: Path, words: list[str]) -> list[dict]:
    """Sentences holding any of the words, as a substring in any case; at most CANDIDATES of them, shared among the
    words so each form of a word is looked for."""
    forms = list(dict.fromkeys(fold(w).strip() for w in words if w.strip()))
    if not forms:
        return []
    share = max(PER_FORM, CANDIDATES // len(forms))
    found: dict[int, dict] = {}
    with closing(sqlite3.connect(f"{(folder / DB).resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        for form in forms:
            if len(form) >= TRIGRAM:
                rows = connection.execute(
                    "SELECT s.* FROM sentence_text JOIN sentences s ON s.id = sentence_text.rowid WHERE sentence_text MATCH ? " + ORDER,
                    ('"' + form.replace('"', '""') + '"', share),
                ).fetchall()
            else:
                rows = connection.execute("SELECT s.* FROM sentences s WHERE instr(s.folded, ?) " + ORDER, (form, share)).fetchall()
            for r in rows:
                found.setdefault(r["id"], {k: r[k] for k in r.keys() if k != "folded"})
    return list(found.values())[:CANDIDATES]


def describe(n: int, sentence: dict) -> str:
    lines = [f"{n}. {sentence['text']}"]
    if sentence["translation"]:
        lines.append(f"   = {sentence['translation']}")
    if sentence["audio"]:
        lines.append(f"   audio: {AUDIO_URL.format(id=sentence['audio'])} (by {sentence['audio_by']}, {sentence['audio_license']})")
    return "\n".join(lines)
