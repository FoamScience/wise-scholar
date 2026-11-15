"""A Wiktionary lexicon for one language, reduced from kaikki.org's JSONL to a small SQLite file the tutor can look
words up in. Nothing here knows any one language: it keeps the fields Wiktionary gives for every entry."""
import json
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

RAW = "lexicon.jsonl"
DB = "lexicon.db"
GLOSSES = 6
FORMS = 60
# what one lookup hands the tutor, so a common word with many entries does not flood its context
ENTRIES = 8
TEXT = 300
# kaikki's bookkeeping rows among the forms, not word forms
NOT_FORMS = {"table-tags", "inflection-template", "class"}
COLUMNS = "word, folded, pos, head, ipa, tags, glosses, forms, more_forms, form_of"
SCHEMA = """
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,
    folded TEXT NOT NULL,
    pos TEXT NOT NULL,
    head TEXT NOT NULL,
    ipa TEXT NOT NULL,
    tags TEXT NOT NULL,
    glosses TEXT NOT NULL,
    forms TEXT NOT NULL,
    more_forms INTEGER NOT NULL,
    form_of TEXT NOT NULL
);
"""


def fold(word: str) -> str:
    """The key a word is found by: one Unicode composition, any case."""
    return unicodedata.normalize("NFC", word).casefold()


def _text(value) -> str:
    return value[:TEXT] if isinstance(value, str) else ""


def _items(entry: dict, field: str) -> list[dict]:
    value = entry.get(field)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _row(entry) -> tuple | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("word"), str) or not entry["word"].strip():
        return None
    word = unicodedata.normalize("NFC", entry["word"])
    senses = _items(entry, "senses")
    heads = [_text(h.get("expansion")) for h in _items(entry, "head_templates") if _text(h.get("expansion"))]
    ipa = next((_text(s["ipa"]) for s in _items(entry, "sounds") if _text(s.get("ipa"))), "")
    tags = sorted({t for s in senses for t in _strings(s.get("tags")) if t != "form-of"})
    glosses = ["; ".join(_text(g) for g in _strings(s.get("glosses"))) for s in senses if _strings(s.get("glosses"))][:GLOSSES]
    forms, seen = [], set()
    for f in _items(entry, "forms"):
        form, tagged = _text(f.get("form")), tuple(_strings(f.get("tags")))
        if form and not NOT_FORMS & set(tagged) and (form, tagged) not in seen:
            seen.add((form, tagged))
            forms.append([form, list(tagged)])
    form_of = sorted({unicodedata.normalize("NFC", w["word"]) for s in senses for w in _items(s, "form_of") if _text(w.get("word"))})
    return (word, fold(word), _text(entry.get("pos")), heads[-1] if heads else word, ipa, json.dumps(tags, ensure_ascii=False),
            json.dumps(glosses, ensure_ascii=False), json.dumps(forms[:FORMS], ensure_ascii=False), max(0, len(forms) - FORMS),
            json.dumps(form_of, ensure_ascii=False))


def prepare(folder: Path) -> None:
    """Turns the downloaded JSONL in the folder into the lexicon database and drops the JSONL. A line that is not a
    usable entry is skipped; a file with no entries at all (an error page, a cut download) fails the download."""
    raw, target = folder / RAW, folder / DB
    target.unlink(missing_ok=True)
    insert = f"INSERT INTO entries ({COLUMNS}) VALUES ({', '.join('?' * len(COLUMNS.split(', ')))})"
    count = 0
    with closing(sqlite3.connect(target)) as connection:
        # a throwaway build: a crash leaves the .part folder, which is cleared and fetched again
        connection.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;" + SCHEMA)
        with open(raw, encoding="utf-8", errors="replace") as lines:
            batch = []
            for line in lines:
                try:
                    row = _row(json.loads(line))
                except ValueError:
                    continue
                if row:
                    batch.append(row)
                if len(batch) >= 5000:
                    connection.executemany(insert, batch)
                    count += len(batch)
                    batch.clear()
            connection.executemany(insert, batch)
            count += len(batch)
        if not count:
            raise ValueError("the lexicon file held no entries")
        connection.execute("CREATE INDEX entries_folded ON entries(folded)")
        connection.commit()
    raw.unlink()


def _entries(connection: sqlite3.Connection, word: str) -> list[dict]:
    rows = connection.execute("SELECT * FROM entries WHERE folded = ? ORDER BY word = ? DESC, id", (fold(word), word)).fetchall()
    return [{**dict(r), **{k: json.loads(r[k]) for k in ("tags", "glosses", "forms", "form_of")}} for r in rows]


def lookup(folder: Path, word: str) -> list[dict]:
    """The entries for a word, written as given or in another case, and for an inflected form also the entries of the
    words it is a form of; each entry once."""
    with closing(sqlite3.connect(f"{(folder / DB).resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        found = _entries(connection, word)
        for lemma in sorted({lemma for e in found for lemma in e["form_of"]}):
            found += _entries(connection, lemma)
    unique = {}
    for entry in found:
        unique.setdefault(entry["id"], entry)
    return list(unique.values())


def describe(entry: dict) -> str:
    """One entry as the tutor reads it."""
    lines = [f"{entry['head']} [{entry['pos']}]" + (f" {entry['ipa']}" if entry["ipa"] else "")]
    if entry["tags"]:
        lines.append("tags: " + ", ".join(entry["tags"]))
    if entry["form_of"]:
        lines.append("form of: " + ", ".join(entry["form_of"]))
    lines += [f"{n}. {g}" for n, g in enumerate(entry["glosses"], 1)]
    if entry["forms"]:
        more = f" (and {entry['more_forms']} more forms not listed)" if entry["more_forms"] else ""
        lines.append("forms: " + "; ".join(f"{form} ({' '.join(tags)})" if tags else form for form, tags in entry["forms"]) + more)
    return "\n".join(lines)


def answer(entries: list[dict]) -> str:
    """The entries of one lookup for the tutor, at most ENTRIES of them."""
    shown = "\n\n".join(describe(e) for e in entries[:ENTRIES])
    return shown + (f"\n\n({len(entries) - ENTRIES} more entries not shown)" if len(entries) > ENTRIES else "")
