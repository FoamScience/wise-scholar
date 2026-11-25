import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path

from . import challenge

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("WISE_SCHOLAR_DB", ROOT / "data" / "wise-scholar.db"))
WORKSPACE = Path(os.environ.get("WISE_SCHOLAR_WORKSPACE", ROOT / "workspace"))

def _rebuild(connection, table: str, create: str, columns: str) -> None:
    """SQLite cannot widen a CHECK, so the table is rebuilt (the 12-step ALTER of its manual): the columns are named so
    nothing misaligns, and a rerun after a crash before the version bump is harmless."""
    connection.executescript(f"""
    PRAGMA foreign_keys = OFF;
    DROP TABLE IF EXISTS {table}_new;
    BEGIN;
    CREATE TABLE {table}_new {create};
    INSERT INTO {table}_new ({columns}) SELECT {columns} FROM {table};
    DROP TABLE {table};
    ALTER TABLE {table}_new RENAME TO {table};
    COMMIT;
    PRAGMA foreign_keys = ON;
    """)


def _rebuild_cards(connection) -> None:
    """A sort card. A lang column an earlier upgrade missed is added first."""
    present = {r["name"] for r in connection.execute("PRAGMA table_info(cards)").fetchall()}
    if "lang" not in present:
        connection.execute("ALTER TABLE cards ADD COLUMN lang TEXT")
    _rebuild(connection, "cards", """(
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        concept_id INTEGER REFERENCES concepts(id),
        question TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('choice', 'open', 'sort')),
        options TEXT NOT NULL,
        answer_key TEXT NOT NULL,
        explanation TEXT NOT NULL,
        fsrs TEXT,
        due TEXT,
        confident_miss INTEGER NOT NULL DEFAULT 0,
        scheduled INTEGER NOT NULL DEFAULT 1,
        vocab INTEGER NOT NULL DEFAULT 0,
        lemma TEXT,
        lang TEXT,
        translation TEXT NOT NULL DEFAULT '',
        relearn_after INTEGER NOT NULL DEFAULT 0
    )""", CARD_COLUMNS)


def _add_missed_columns(connection) -> None:
    """A database that ran an early draft of the versions migration lacks three of its columns; one that ran the
    final migration has them and is left as it is."""
    for table, column in (("concepts", "unwritten"), ("versions", "written"), ("versions", "units")):
        if column not in {r["name"] for r in connection.execute(f"PRAGMA table_info({table})").fetchall()}:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")


def _rebuild_errors(connection) -> None:
    """A miss in a practice unit is a notebook entry of its own kind."""
    _rebuild(connection, "errors", """(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
        kind TEXT NOT NULL CHECK (kind IN ('quiz', 'writing', 'practice')),
        prompt TEXT NOT NULL,
        said TEXT NOT NULL,
        correct TEXT NOT NULL,
        explanation TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        pinned INTEGER NOT NULL DEFAULT 0,
        resolved INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""", "id, profile_id, course_id, card_id, kind, prompt, said, correct, explanation, note, pinned, resolved, created")


USAGE_TOTALS = ("input", "output", "cache_read", "cache_write", "cost")


def _usage_per_turn(connection) -> None:
    """Rows of a resumed lesson session held the session's running totals; each becomes its turn's own share. The rows
    never named their session, so it is guessed: a row lower than the one before in any total starts a new session,
    and a new session whose first turn is no lower in all five passes for a continuation. The open session of each
    lesson is named, so its next turn is charged only its own share."""
    connection.execute("ALTER TABLE usage ADD COLUMN session TEXT")
    connection.execute("CREATE INDEX usage_session ON usage(session)")
    chains: dict[tuple, list] = {}
    # Background kinds start a fresh session every turn and already hold one turn each.
    for r in connection.execute(
        "SELECT u.id, u.lesson_id, u.kind, u.backend, u.input, u.output, u.cache_read, u.cache_write, COALESCE(u.cost, 0) AS cost, "
        "l.session_id, l.session_started, l.backend AS lesson_backend FROM usage u JOIN lessons l ON l.id = u.lesson_id "
        "WHERE u.kind NOT IN ('graph', 'cards', 'cleanup', 'explore', 'recap') ORDER BY u.id"
    ).fetchall():
        chains.setdefault((r["lesson_id"], r["kind"]), []).append(r)
    for chain in chains.values():
        before, current = None, []
        for r in chain:
            if before is not None and all(r[k] >= before[k] for k in USAGE_TOTALS):
                connection.execute(
                    "UPDATE usage SET " + ", ".join(f"{k} = ?" for k in USAGE_TOTALS) + " WHERE id = ?",
                    (*(r[k] - before[k] for k in USAGE_TOTALS), r["id"]),
                )
                current.append(r["id"])
            else:
                current = [r["id"]]
            before = r
        last = chain[-1]
        if last["session_started"] and last["lesson_backend"] == last["backend"] == "claude":
            connection.executemany("UPDATE usage SET session = ? WHERE id = ?", [(last["session_id"], i) for i in current])


def lock(data: dict) -> dict | None:
    """Take the hints and solution a task came with out of its data, where they would close it and show at once; returns
    them for the gate to give. The ladder is as long as the author's, but for the tasks that never have one. Also run by
    the migration _lock_imported."""
    hints, solution = data.get("hints"), data.get("solution")
    files = challenge.solution_files(data, data.pop("solution_files", None))
    data.update({"hints": [], "solution": None})
    data.update({k: d for k, d in challenge.new().items() if k in ("max_hints", "reveal_after") and not isinstance(data.get(k), int)})
    hints = [h for h in hints if isinstance(h, str) and h.strip()] if isinstance(hints, list) else []
    solution = solution if isinstance(solution, str) and solution.strip() else None
    if not hints and not solution and not files:
        return None
    locked = {"hints": hints, "solution": solution, "max_hints": data["max_hints"]} | ({"solution_files": files} if files else {})
    if data.get("pretest"):
        data["reveal_after"] = 1
    elif not data.get("transfer"):
        data["max_hints"] = max(data["max_hints"], len(hints))
    return locked


def _lock_imported(connection) -> None:
    """locked: the hints and solution the author of an imported task wrote, kept out of its data until the learner reaches
    them. Tasks imported before this column held them in the open, which closed the task, so it has no work on it."""
    if "locked" not in {r["name"] for r in connection.execute("PRAGMA table_info(blocks)").fetchall()}:
        connection.execute("ALTER TABLE blocks ADD COLUMN locked TEXT")
    for r in connection.execute(
        "SELECT b.id, b.data FROM blocks b JOIN lessons l ON l.id = b.lesson_id JOIN courses c ON c.id = l.course_id "
        "WHERE c.mode = 'replay' AND b.kind IN ('challenge', 'exercise') AND b.data IS NOT NULL"
    ).fetchall():
        data = json.loads(r["data"])
        if not data.get("imported") or data.get("attempts") or data.get("gave_up") or data.get("solved"):
            continue
        if data.get("solution") is None and not data.get("hints"):
            continue
        locked = lock(data)
        connection.execute("UPDATE blocks SET data = ?, locked = ? WHERE id = ?", (json.dumps(data), json.dumps(locked) if locked else None, r["id"]))


def _retire_crafted(connection) -> None:
    """Crafted figures are retired and the web app no longer styles them: one goes back to the drawing it replaced when
    that was a plain one, else stays as it is drawn; a crafted drawing kept to go back to is dropped."""
    for r in connection.execute("SELECT id, markdown, data FROM blocks WHERE kind = 'figure' AND data LIKE '%\"crafted\"%'").fetchall():
        data, markdown = json.loads(r["data"]), r["markdown"]
        previous = data.get("previous") or {}
        if "crafted" in data and previous and "crafted" not in previous:
            markdown, data = previous.pop("caption"), previous
        else:
            data.pop("crafted", None)
            if "crafted" in previous:
                data.pop("previous")
                data.pop("restored", None)
        connection.execute("UPDATE blocks SET markdown = ?, data = ? WHERE id = ?", (markdown, json.dumps(data), r["id"]))


CARD_COLUMNS = "id, course_id, concept_id, question, kind, options, answer_key, explanation, fsrs, due, confident_miss, scheduled, vocab, lemma, lang, translation, relearn_after"
MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        topic TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        title TEXT NOT NULL,
        session_id TEXT NOT NULL,
        session_started INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        role TEXT NOT NULL CHECK (role IN ('learner', 'tutor')),
        text TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY,
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        kind TEXT NOT NULL,
        markdown TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE lessons ADD COLUMN phase TEXT NOT NULL DEFAULT 'lesson';
    UPDATE lessons SET phase = 'interview' WHERE title = 'Interview';
    ALTER TABLE blocks ADD COLUMN data TEXT;
    ALTER TABLE courses ADD COLUMN ranking TEXT;
    ALTER TABLE courses ADD COLUMN mechanism TEXT;
    CREATE TABLE facts (
        id INTEGER PRIMARY KEY,
        course_id INTEGER REFERENCES courses(id),
        text TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE concepts (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        module TEXT NOT NULL,
        title TEXT NOT NULL
    );
    ALTER TABLE lessons ADD COLUMN concept_id INTEGER REFERENCES concepts(id);
    """,
    """
    CREATE TABLE cards (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        concept_id INTEGER REFERENCES concepts(id),
        question TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('choice', 'open')),
        options TEXT NOT NULL,
        answer_key TEXT NOT NULL,
        explanation TEXT NOT NULL,
        fsrs TEXT,
        due TEXT,
        confident_miss INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE answers (
        id INTEGER PRIMARY KEY,
        card_id INTEGER NOT NULL REFERENCES cards(id),
        answer TEXT NOT NULL,
        confidence REAL NOT NULL,
        correct INTEGER,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE courses ADD COLUMN level TEXT;
    ALTER TABLE courses ADD COLUMN placement TEXT;
    ALTER TABLE concepts ADD COLUMN known INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE cards ADD COLUMN scheduled INTEGER NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE cards ADD COLUMN vocab INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE lessons ADD COLUMN backend TEXT;
    UPDATE lessons SET backend = 'claude' WHERE session_started = 1;
    """,
    """
    CREATE TABLE profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO profiles (name) SELECT 'Me' WHERE EXISTS (SELECT 1 FROM courses) OR EXISTS (SELECT 1 FROM facts);
    ALTER TABLE courses ADD COLUMN profile_id INTEGER REFERENCES profiles(id);
    UPDATE courses SET profile_id = (SELECT MIN(id) FROM profiles);
    ALTER TABLE facts ADD COLUMN profile_id INTEGER REFERENCES profiles(id);
    UPDATE facts SET profile_id = (SELECT MIN(id) FROM profiles) WHERE course_id IS NULL;
    """,
    """
    ALTER TABLE courses ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
    """,
    """
    CREATE TABLE vocab_knowledge (
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        lang TEXT NOT NULL,
        lemma TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('known', 'learning')),
        exposures INTEGER NOT NULL DEFAULT 0,
        source TEXT,
        updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (profile_id, lang, lemma)
    );
    CREATE TABLE vocab_tiers (
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        lang TEXT NOT NULL,
        tier INTEGER NOT NULL,
        PRIMARY KEY (profile_id, lang)
    );
    ALTER TABLE courses ADD COLUMN lang TEXT;
    ALTER TABLE cards ADD COLUMN lemma TEXT;
    ALTER TABLE cards ADD COLUMN lang TEXT;
    """,
    """
    CREATE TABLE errors (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
        kind TEXT NOT NULL CHECK (kind IN ('quiz', 'writing')),
        prompt TEXT NOT NULL,
        said TEXT NOT NULL,
        correct TEXT NOT NULL,
        explanation TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        pinned INTEGER NOT NULL DEFAULT 0,
        resolved INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE series (
        course_id INTEGER PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        characters TEXT NOT NULL,
        synopsis TEXT NOT NULL DEFAULT '',
        episodes INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE sources (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        size INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'ready', 'failed')),
        error TEXT,
        sections INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE source_sections (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        text TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE source_fts USING fts5(title, text, content='source_sections', content_rowid='id');
    CREATE TRIGGER source_sections_ai AFTER INSERT ON source_sections BEGIN
        INSERT INTO source_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
    END;
    CREATE TRIGGER source_sections_ad AFTER DELETE ON source_sections BEGIN
        INSERT INTO source_fts(source_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
    END;
    """,
    """
    CREATE TABLE capstones (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        module TEXT NOT NULL,
        title TEXT NOT NULL,
        brief TEXT NOT NULL,
        folder TEXT NOT NULL,
        UNIQUE (course_id, module)
    );
    CREATE TABLE milestones (
        id INTEGER PRIMARY KEY,
        capstone_id INTEGER NOT NULL REFERENCES capstones(id) ON DELETE CASCADE,
        concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        deliverable TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    ALTER TABLE profiles ADD COLUMN locale TEXT NOT NULL DEFAULT 'en';
    """,
    """
    ALTER TABLE courses ADD COLUMN details TEXT NOT NULL DEFAULT '';
    ALTER TABLE courses ADD COLUMN hours INTEGER;
    ALTER TABLE courses ADD COLUMN started INTEGER NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE concepts ADD COLUMN position INTEGER;
    UPDATE concepts SET position = id;
    """,
    """
    CREATE TABLE commands (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        origin TEXT NOT NULL CHECK (origin IN ('tutor', 'learner', 'network')),
        command TEXT NOT NULL,
        consent TEXT NOT NULL CHECK (consent IN ('none', 'allowed', 'refused') AND (origin = 'network') = (consent != 'none')),
        exit_code INTEGER,
        output TEXT NOT NULL DEFAULT '',
        started TEXT NOT NULL,
        seconds REAL
    );
    CREATE INDEX commands_profile ON commands(profile_id, id);
    """,
    "ALTER TABLE courses ADD COLUMN cleaned TEXT;",
    """
    ALTER TABLE profiles ADD COLUMN mode TEXT NOT NULL DEFAULT 'learner';
    ALTER TABLE courses ADD COLUMN mode TEXT NOT NULL DEFAULT 'learner';
    """,
    """
    ALTER TABLE blocks ADD COLUMN position INTEGER;
    UPDATE blocks SET position = id;
    """,
    "ALTER TABLE profiles ADD COLUMN sketch INTEGER NOT NULL DEFAULT 1;",
    "ALTER TABLE cards ADD COLUMN translation TEXT NOT NULL DEFAULT '';",
    "ALTER TABLE cards ADD COLUMN relearn_after INTEGER NOT NULL DEFAULT 0;",
    _rebuild_cards,
    "ALTER TABLE concepts ADD COLUMN kind TEXT NOT NULL DEFAULT 'concept';",
    _rebuild_errors,
    "ALTER TABLE lessons ADD COLUMN batch INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE courses ADD COLUMN pace TEXT NOT NULL DEFAULT 'momentum';",
    """
    CREATE TABLE placement_areas (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        title TEXT NOT NULL,
        holds TEXT NOT NULL,
        lacks TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE concept_needs (
        concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        needs_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        PRIMARY KEY (concept_id, needs_id)
    );
    ALTER TABLE courses ADD COLUMN prerequisites INTEGER NOT NULL DEFAULT 0;
    """,
    """
    CREATE TABLE claims (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        wrong INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE VIRTUAL TABLE claim_fts USING fts5(text, content='claims', content_rowid='id');
    CREATE TRIGGER claims_ai AFTER INSERT ON claims BEGIN
        INSERT INTO claim_fts(rowid, text) VALUES (new.id, new.text);
    END;
    CREATE TRIGGER claims_ad AFTER DELETE ON claims BEGIN
        INSERT INTO claim_fts(claim_fts, rowid, text) VALUES ('delete', old.id, old.text);
    END;
    CREATE TRIGGER claims_au AFTER UPDATE OF text ON claims BEGIN
        INSERT INTO claim_fts(claim_fts, rowid, text) VALUES ('delete', old.id, old.text);
        INSERT INTO claim_fts(rowid, text) VALUES (new.id, new.text);
    END;
    CREATE TABLE claim_edges (
        from_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        to_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('follows', 'supports', 'contrasts')),
        PRIMARY KEY (from_id, to_id, kind)
    );
    CREATE TABLE claim_sources (
        claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
        PRIMARY KEY (claim_id, lesson_id)
    );
    CREATE TABLE claim_evidence (
        claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
        PRIMARY KEY (claim_id, block_id)
    );
    ALTER TABLE lessons ADD COLUMN extracted TEXT;
    """,
    """
    ALTER TABLE courses ADD COLUMN cover TEXT;
    ALTER TABLE courses ADD COLUMN cover_alt TEXT;
    """,
    """
    DROP TRIGGER source_sections_ai;
    DROP TRIGGER source_sections_ad;
    DROP TABLE source_fts;
    CREATE TABLE passages (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('source', 'card', 'chat', 'code')),
        ref TEXT NOT NULL,
        lesson_id INTEGER,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        vector BLOB,
        UNIQUE (course_id, kind, ref)
    );
    CREATE VIRTUAL TABLE passage_fts USING fts5(title, text, content='passages', content_rowid='id');
    CREATE TRIGGER passages_ai AFTER INSERT ON passages BEGIN
        INSERT INTO passage_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
    END;
    CREATE TRIGGER passages_ad AFTER DELETE ON passages BEGIN
        INSERT INTO passage_fts(passage_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
    END;
    """,
    "ALTER TABLE lessons ADD COLUMN questions INTEGER;",
    """
    ALTER TABLE cards ADD COLUMN parent_id INTEGER REFERENCES cards(id);
    ALTER TABLE cards ADD COLUMN origin TEXT;
    ALTER TABLE cards ADD COLUMN retired INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE answers ADD COLUMN stated INTEGER NOT NULL DEFAULT 1;
    """,
    """
    CREATE TABLE usage (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        lesson_id INTEGER REFERENCES lessons(id),
        kind TEXT NOT NULL,
        backend TEXT NOT NULL,
        model TEXT NOT NULL,
        input INTEGER NOT NULL,
        output INTEGER NOT NULL,
        cache_read INTEGER NOT NULL,
        cache_write INTEGER NOT NULL,
        cost REAL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX usage_course ON usage(course_id, lesson_id);
    """,
    """
    ALTER TABLE concepts ADD COLUMN key TEXT;
    UPDATE concepts SET key = lower(hex(randomblob(16)));
    CREATE TRIGGER concepts_key AFTER INSERT ON concepts WHEN new.key IS NULL BEGIN
        UPDATE concepts SET key = lower(hex(randomblob(16))) WHERE id = new.id;
    END;
    ALTER TABLE lessons ADD COLUMN key TEXT;
    UPDATE lessons SET key = lower(hex(randomblob(16)));
    CREATE TRIGGER lessons_key AFTER INSERT ON lessons WHEN new.key IS NULL BEGIN
        UPDATE lessons SET key = lower(hex(randomblob(16))) WHERE id = new.id;
    END;
    ALTER TABLE blocks ADD COLUMN key TEXT;
    UPDATE blocks SET key = lower(hex(randomblob(16)));
    CREATE TRIGGER blocks_key AFTER INSERT ON blocks WHEN new.key IS NULL BEGIN
        UPDATE blocks SET key = lower(hex(randomblob(16))) WHERE id = new.id;
    END;
    ALTER TABLE cards ADD COLUMN key TEXT;
    UPDATE cards SET key = lower(hex(randomblob(16)));
    CREATE TRIGGER cards_key AFTER INSERT ON cards WHEN new.key IS NULL BEGIN
        UPDATE cards SET key = lower(hex(randomblob(16))) WHERE id = new.id;
    END;
    ALTER TABLE courses ADD COLUMN source_version TEXT;
    ALTER TABLE concepts ADD COLUMN unwritten INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE versions (
        hash TEXT PRIMARY KEY,
        course_id INTEGER REFERENCES courses(id),
        number INTEGER NOT NULL,
        topic TEXT NOT NULL,
        notes TEXT NOT NULL,
        licence TEXT NOT NULL,
        forkable INTEGER NOT NULL,
        credits TEXT NOT NULL,
        setup TEXT NOT NULL,
        written INTEGER NOT NULL,
        units INTEGER NOT NULL,
        published TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE courses ADD COLUMN setup TEXT;
    ALTER TABLE lessons ADD COLUMN summary TEXT;
    """,
    """
    CREATE TABLE publish_edits (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        target TEXT NOT NULL CHECK (target IN ('block', 'card', 'file', 'course', 'summary')),
        ref TEXT NOT NULL,
        old TEXT NOT NULL,
        new TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'accepted', 'rejected')),
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE courses ADD COLUMN checked TEXT;
    """,
    """
    ALTER TABLE courses ADD COLUMN key TEXT;
    UPDATE courses SET key = lower(hex(randomblob(16)));
    CREATE TRIGGER courses_key AFTER INSERT ON courses WHEN new.key IS NULL BEGIN
        UPDATE courses SET key = lower(hex(randomblob(16))) WHERE id = new.id;
    END;
    ALTER TABLE courses ADD COLUMN skipped_version TEXT;
    ALTER TABLE versions ADD COLUMN lineage TEXT;
    UPDATE versions SET lineage = (SELECT key FROM courses WHERE courses.id = versions.course_id);
    CREATE INDEX versions_lineage ON versions(lineage, number);
    """,
    """
    ALTER TABLE cards ADD COLUMN misconceptions TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE errors ADD COLUMN misconception TEXT NOT NULL DEFAULT '';
    """,
    _add_missed_columns,
    """
    CREATE TABLE suggestions (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id),
        title TEXT NOT NULL,
        pitch TEXT NOT NULL,
        kind TEXT NOT NULL,
        builds_on TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open'
    );
    CREATE INDEX suggestions_profile ON suggestions(profile_id, status);
    ALTER TABLE profiles ADD COLUMN suggested_courses INTEGER;
    ALTER TABLE profiles ADD COLUMN suggested_lessons INTEGER;
    """,
    """
    ALTER TABLE courses ADD COLUMN sitting INTEGER;
    """,
    """
    ALTER TABLE usage ADD COLUMN seconds REAL;
    """,
    """
    CREATE TABLE recaps (
        course_id INTEGER PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
        finished TEXT,
        seen INTEGER NOT NULL DEFAULT 0,
        narrative TEXT,
        positions TEXT
    );
    """,
    """
    ALTER TABLE lessons ADD COLUMN cards INTEGER;
    UPDATE lessons SET cards = (
        SELECT CASE WHEN SUM(b.kind = 'done') > 0 THEN COUNT(*) ELSE MAX(COUNT(*) + 1, 5) END
        FROM blocks b WHERE b.lesson_id = lessons.id AND b.kind != 'outline'
    ) WHERE phase = 'practice';
    """,
    _usage_per_turn,
    # Parts of a card made short before it was answered took no schedule, and the answer scheduled the retired card:
    # they take the schedule it was given.
    """
    UPDATE cards SET
        fsrs = (SELECT p.fsrs FROM cards p WHERE p.id = cards.parent_id),
        due = (SELECT p.due FROM cards p WHERE p.id = cards.parent_id)
    WHERE origin = 'short' AND retired = 0 AND due IS NULL
        AND NOT EXISTS (SELECT 1 FROM answers a WHERE a.card_id = cards.id)
        AND (SELECT p.due FROM cards p WHERE p.id = cards.parent_id) IS NOT NULL;
    """,
    """
    CREATE TABLE contributions (
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES courses(id),
        repo TEXT NOT NULL,
        title TEXT NOT NULL,
        size TEXT NOT NULL CHECK (size IN ('small', 'project')),
        gap TEXT NOT NULL,
        uses TEXT NOT NULL,
        first_step TEXT NOT NULL,
        issue TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        lesson_id INTEGER REFERENCES lessons(id)
    );
    CREATE INDEX contributions_course ON contributions(course_id, status);
    ALTER TABLE courses ADD COLUMN contributions_for TEXT;
    """,
    # reminded: the profile's local date of the last day the reminder was settled, sent or not
    """
    ALTER TABLE profiles ADD COLUMN remind_at TEXT;
    ALTER TABLE profiles ADD COLUMN remind_tz TEXT;
    ALTER TABLE profiles ADD COLUMN reminded TEXT;
    CREATE TABLE push_subscriptions (
        endpoint TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        keys TEXT NOT NULL,
        origin TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # own: the learner's language, which sentence pairs are paired with; key: the shared folder under data/resources
    """
    CREATE TABLE course_resources (
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        lang TEXT NOT NULL,
        own TEXT NOT NULL,
        key TEXT NOT NULL,
        size INTEGER,
        status TEXT NOT NULL CHECK (status IN ('asked', 'refused', 'downloading', 'ready', 'failed')),
        done INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        PRIMARY KEY (course_id, kind)
    );
    """,
    # prepared_offline: the tutor finished writing the unit for offline study, so it publishes like a finished one;
    # the lessons taken offline before this column were prepared in full
    """
    ALTER TABLE lessons ADD COLUMN prepared_offline INTEGER NOT NULL DEFAULT 0;
    UPDATE lessons SET prepared_offline = 1 WHERE batch = 1;
    """,
    # gist_tries: how many times a gist turn was started for the finished lesson's board; a failed one goes again once
    "ALTER TABLE lessons ADD COLUMN gist_tries INTEGER NOT NULL DEFAULT 0;",
    # context: the sentence a saved word was met in; it stays in this database, in no bundle and no copy
    "ALTER TABLE cards ADD COLUMN context TEXT NOT NULL DEFAULT '';",
    _lock_imported,
    _retire_crafted,
]

DB_PATH.parent.mkdir(exist_ok=True)


class _PerThread:
    """One SQLite connection per thread behind the single name `conn`. Sync endpoints run in worker threads beside
    the event loop; one connection shared between them trips over its own statement cache (InterfaceError), and a
    BEGIN in one thread would swallow the statements of another."""

    def __init__(self, path: Path):
        self._path = path
        self._local = threading.local()

    def __getattr__(self, name: str):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._path, isolation_level=None, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # Write-ahead log: a thread that writes does not hold up the threads that read.
            connection.execute("PRAGMA journal_mode = WAL")
            self._local.connection = connection
        return getattr(connection, name)


conn = _PerThread(DB_PATH)
_version = conn.execute("PRAGMA user_version").fetchone()[0]
if 0 < _version < len(MIGRATIONS):
    # Keep the database as it was before this upgrade, in case a migration goes wrong. The checkpoint moves what
    # still sits in the write-ahead log into the file that is copied.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy(DB_PATH, DB_PATH.with_name(f"{DB_PATH.name}.v{_version}.bak"))
for _n, _script in enumerate(MIGRATIONS[_version:], start=_version + 1):
    if callable(_script):
        _script(conn)
    else:
        conn.executescript(_script)
    conn.execute(f"PRAGMA user_version = {_n}")


def workspace(slug: str) -> Path:
    """The course's folder for exercise files; also the working directory of its agent sessions."""
    path = WORKSPACE / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def rows(sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def row(sql: str, *args) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def profiles() -> list[dict]:
    return [
        _profile_view(p)
        for p in rows("SELECT p.*, (SELECT COUNT(*) FROM courses c WHERE c.profile_id = p.id) AS courses FROM profiles p ORDER BY p.id")
    ]


def profile(profile_id: int) -> dict | None:
    p = row("SELECT * FROM profiles WHERE id = ?", profile_id)
    return _profile_view(p) if p else None


def _profile_view(p: dict) -> dict:
    return {**p, "sketch": bool(p["sketch"])}


def _free_slug(topic: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "course"
    slug, n = base, 2
    while row("SELECT 1 FROM courses WHERE slug = ?", slug):
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_course(topic: str, profile_id: int) -> dict:
    slug = _free_slug(topic)
    # A course keeps the mode its profile had when it was made.
    mode = (profile(profile_id) or {}).get("mode", "learner")
    course_id = conn.execute(
        "INSERT INTO courses (topic, slug, profile_id, started, mode) VALUES (?, ?, ?, 0, ?)", (topic, slug, profile_id, mode)
    ).lastrowid
    create_lesson(course_id, "Interview", "interview")
    return course(course_id)


# What a copied block leaves behind: the record of whoever worked on the original.
_RECORD = ("attempts", "marks", "gave_up", "solved", "last_run", "files_kept", "answer", "answer_id", "confidence", "correct",
           "confident_miss", "feedback", "unknown", "scores", "saved", "photos", "transcripts", "misplaced", "misconception",
           "due", "unheard", "tried", "told")


def _fresh(data: dict, authored: bool = False) -> dict:
    """A block's data without the record made on the original: the material stays, the work on it does not. Hints and
    a solution answer the learner's own attempts, so they stay only when authored, in a prepared course."""
    kept = {k: v for k, v in data.items() if k not in _RECORD}
    if "attempts" in data:
        kept.update({"attempts": [], "gave_up": False, "solved": False})
    if not authored:
        kept.update({k: empty for k, empty in (("hints", []), ("solution", None)) if k in data})
        kept.pop("solution_files", None)
    if "answer" in data:
        kept["answer"] = None
    if "last_run" in data:
        kept["last_run"] = None
    kept.update({k: [] for k in ("added", "known", "non_goals") if k in data})
    if "steps" in data:
        kept.update({"at": 0, "added": None})  # the added step stays in steps; the reason for it is about the learner
    if data.get("rounds"):  # a vocabulary check starts over from the words it opened with
        first = data["rounds"][0]
        kept.update({"rounds": [], "current": {"tier": first["tier"], "words": first["words"]}, "tier": None})
    return kept


def keyless(data: dict) -> dict:
    """A quiz's data without what gives its answer away: the key, the explanation, the beliefs behind the wrong options
    and, in a sort, where each item goes."""
    shown = {k: v for k, v in data.items() if k not in ("answer_key", "explanation", "misconceptions")}
    if isinstance(data.get("options"), list):
        shown["options"] = [{k: v for k, v in o.items() if k != "category"} if isinstance(o, dict) else o for o in data["options"]]
    return shown


TICK = " ✓"


def outline_text(steps: list, at: int) -> str:
    """The Markdown copy of an outline, which exports and the book show, its steps ticked up to at."""
    return "\n".join(f"{i}. {step}{TICK if i <= at else ''}" for i, step in enumerate(steps, 1))


def ticked_as_at(markdown: str, data: dict) -> str:
    """An outline's text ticked as far as its data says; text that is not its steps', as a teacher may write, stays."""
    steps, at = data.get("steps"), data.get("at")
    if not isinstance(steps, list) or not isinstance(at, int):
        return markdown
    ticks = (len(markdown) - len(outline_text(steps, 0))) // len(TICK)
    return outline_text(steps, at) if markdown == outline_text(steps, ticks) else markdown


def _copy_concepts(course_id: int, new_id: int) -> dict[int, int]:
    concept_map = {}
    for c in concepts(course_id):
        concept_map[c["id"]] = conn.execute(
            "INSERT INTO concepts (course_id, module, title, known, position, kind, key, unwritten) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, c["module"], c["title"], c["known"], c["position"], c["kind"], c["key"], c["unwritten"]),
        ).lastrowid
    conn.executemany(
        "INSERT INTO concept_needs (concept_id, needs_id) VALUES (?, ?)",
        [(concept_map[c], concept_map[n]) for c, ids in needs(course_id).items() for n in ids],
    )
    return concept_map


def _copy_capstones(course_id: int, new_id: int, concept_map: dict[int, int]) -> None:
    for k in capstones(course_id):
        capstone_id = conn.execute(
            "INSERT INTO capstones (course_id, module, title, brief, folder) VALUES (?, ?, ?, ?, ?)",
            (new_id, k["module"], k["title"], k["brief"], k["folder"]),
        ).lastrowid
        conn.executemany(
            "INSERT INTO milestones (capstone_id, concept_id, deliverable) VALUES (?, ?, ?)",
            [(capstone_id, concept_map[m["concept_id"]], m["deliverable"]) for m in k["milestones"] if m["concept_id"] in concept_map],
        )


def _copy_cards(course_id: int, new_id: int, concept_map: dict[int, int]) -> dict[int, int]:
    card_map = {}
    private = private_cards(course_id)
    # a copy starts its reviews afresh from the lesson cards; the short parts made for reviews stay behind
    for k in rows("SELECT * FROM cards WHERE course_id = ? AND parent_id IS NULL ORDER BY id", course_id):
        if k["id"] in private:
            continue
        card_map[k["id"]] = conn.execute(
            "INSERT INTO cards (course_id, concept_id, question, kind, options, answer_key, explanation, scheduled, vocab, lemma, lang, translation, misconceptions, key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, concept_map.get(k["concept_id"]), k["question"], k["kind"], k["options"], k["answer_key"], k["explanation"],
             k["scheduled"], k["vocab"], k["lemma"], k["lang"], k["translation"], k["misconceptions"], k["key"]),
        ).lastrowid
    return card_map


def _copy_blocks(old_lesson: int, lesson_id: int, concept_map: dict[int, int], card_map: dict[int, int], authored: bool) -> dict[int, int]:
    """The map of old to new block ids. A variant's original is left out: _copy_lessons sets it once every block is copied.
    So is what a revisit's check is on: the mistakes and claims stay with the learner."""
    from . import board  # it draws with art, which reads this module

    block_map = {}
    for b in rows("SELECT * FROM blocks WHERE lesson_id = ? ORDER BY position, id", old_lesson):
        if b["kind"] in ("podcast", "network"):
            continue  # audio and consent belong to the original
        data = _fresh(json.loads(b["data"]), authored) if b["data"] else None
        if b["kind"] == "outline" and data:
            if "items" in data:
                continue  # a revisit's outline is the learner's open mistakes and shaky claims
            b["markdown"] = ticked_as_at(b["markdown"], data)
        if b["kind"] == "quiz" and data and not authored:
            data = keyless(data)
        if b["kind"] in ("figure", "board") and data:
            data = board.without_answers(data, authored)
        if data and data.get("card_id") is not None:
            if data["card_id"] not in card_map:
                continue  # a block on a card that stays behind
            data = {**data, "card_id": card_map[data["card_id"]]}
        if data:
            for field in ("variant_of", "revisit_error", "revisit_claim"):
                data.pop(field, None)
            if b["kind"] == "quiz" and (unit := data.pop("unit", None)) in concept_map:
                data["unit"] = concept_map[unit]
        copied = conn.execute(
            "INSERT INTO blocks (lesson_id, kind, markdown, data, created, key) VALUES (?, ?, ?, ?, ?, ?)",
            (lesson_id, b["kind"], b["markdown"], json.dumps(data) if data else None, b["created"], b["key"]),
        ).lastrowid
        conn.execute("UPDATE blocks SET position = ? WHERE id = ?", (copied, copied))
        block_map[b["id"]] = copied
    return block_map


def _copy_lessons(course_id: int, new_id: int, concept_map: dict[int, int], card_map: dict[int, int], authored: bool) -> None:
    block_map = {}
    for lesson_row in rows("SELECT * FROM lessons WHERE course_id = ? ORDER BY id", course_id):
        if lesson_row["concept_id"] and lesson_row["concept_id"] not in concept_map:
            continue
        lesson_id = conn.execute(
            "INSERT INTO lessons (course_id, title, phase, concept_id, session_id, key) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id, lesson_row["title"], lesson_row["phase"], concept_map.get(lesson_row["concept_id"]), str(uuid.uuid4()), lesson_row["key"]),
        ).lastrowid
        block_map |= _copy_blocks(lesson_row["id"], lesson_id, concept_map, card_map, authored)
        conn.executemany(
            "INSERT INTO messages (lesson_id, role, text, created) VALUES (?, ?, ?, ?)",
            [(lesson_id, m["role"], m["text"], m["created"]) for m in rows("SELECT * FROM messages WHERE lesson_id = ? ORDER BY id", lesson_row["id"])],
        )
    for v in variants(course_id):
        if v["id"] in block_map and v["original"] in block_map:
            set_original(block_map[v["id"]], block_map[v["original"]])


def _copy_sources(course_id: int, new_id: int) -> dict[int, int]:
    source_map = {}
    for s in rows("SELECT * FROM sources WHERE course_id = ? AND status = 'ready' ORDER BY id", course_id):
        source_map[s["id"]] = conn.execute(
            "INSERT INTO sources (course_id, name, size, status, error, sections) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id, s["name"], s["size"], s["status"], s["error"], s["sections"]),
        ).lastrowid
        conn.executemany(
            "INSERT INTO source_sections (source_id, title, text) VALUES (?, ?, ?)",
            [(source_map[s["id"]], x["title"], x["text"]) for x in rows("SELECT title, text FROM source_sections WHERE source_id = ? ORDER BY id", s["id"])],
        )
    return source_map


def copy_course(course_id: int, topic: str) -> dict:
    """A new course with the same plan: scope, map, projects, lessons with their cards, blocks and chat, materials
    and course facts. Nothing of the record that measures a learner comes along: answers, reviews, mistakes, the
    command log; and every lesson gets a fresh agent session. Returns the new course with a map of old to new source ids."""
    conn.execute("BEGIN")
    try:
        old = course(course_id)
        if not old:
            raise ValueError("no such course")
        slug = _free_slug(topic)
        new_id = conn.execute(
            "INSERT INTO courses (topic, slug, profile_id, mechanism, level, lang, ranking, details, hours, started, mode, placement, prerequisites, cover, cover_alt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (topic, slug, old["profile_id"], old["mechanism"], old["level"], old["lang"], json.dumps(old["ranking"]) if old["ranking"] else None,
             old["details"], old["hours"], old["started"], old["mode"], old["placement"], old["prerequisites"], old["cover"], old["cover_alt"]),
        ).lastrowid
        conn.execute(
            "INSERT INTO placement_areas (course_id, position, title, holds, lacks) "
            "SELECT ?, position, title, holds, lacks FROM placement_areas WHERE course_id = ?", (new_id, course_id),
        )
        concept_map = _copy_concepts(course_id, new_id)
        _copy_capstones(course_id, new_id, concept_map)
        card_map = _copy_cards(course_id, new_id, concept_map)
        _copy_lessons(course_id, new_id, concept_map, card_map, old["mode"] == "teacher")
        conn.executemany(
            "INSERT INTO facts (course_id, text, profile_id) VALUES (?, ?, ?)",
            [(new_id, f["text"], f["profile_id"]) for f in rows("SELECT * FROM facts WHERE course_id = ?", course_id)],
        )
        source_map = _copy_sources(course_id, new_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {**course(new_id), "sources": source_map}


# What the log keeps of a command's output: the tail the tutor is shown.
COMMAND_OUTPUT = 4000


def log_command(lesson: dict, origin: str, command: str, consent: str = "none") -> int:
    """A command is logged before it runs, whoever asked for it, so a stopped one leaves a row too;
    finish_command adds its result. A refused request is logged and never finished."""
    return conn.execute(
        "INSERT INTO commands (course_id, profile_id, lesson_id, origin, command, consent, started) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lesson["course_id"], lesson["profile_id"], lesson["id"], origin, command, consent, datetime.now(timezone.utc).isoformat()),
    ).lastrowid


def finish_command(command_id: int, result: dict | None, seconds: float) -> None:
    """result None: the command was stopped or could not be run."""
    output = result["output"] if result else "stopped before it ended"
    conn.execute(
        "UPDATE commands SET exit_code = ?, output = ?, seconds = ? WHERE id = ?",
        (result["exit_code"] if result else None, output[-COMMAND_OUTPUT:], seconds, command_id),
    )


def commands(profile_id: int) -> list[dict]:
    """Every command run for the profile's courses, newest first, with the course and lesson it ran for."""
    return rows(
        "SELECT c.*, k.topic, l.title AS lesson FROM commands c JOIN courses k ON k.id = c.course_id "
        "JOIN lessons l ON l.id = c.lesson_id WHERE c.profile_id = ? ORDER BY c.id DESC",
        profile_id,
    )


def add_usage(course_id: int, lesson_id: int | None, kind: str, backend: str, used: dict, seconds: float | None = None) -> None:
    """A usage that names its session carries that session's running cost; the turn is charged what the session's
    earlier turns have not."""
    cost, session = used["cost"], used.get("session")
    if session and cost is not None:
        cost -= row("SELECT COALESCE(SUM(cost), 0) AS spent FROM usage WHERE session = ?", session)["spent"]
    conn.execute(
        "INSERT INTO usage (course_id, lesson_id, kind, backend, model, input, output, cache_read, cache_write, cost, seconds, session) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (course_id, lesson_id, kind, backend, used["model"], used["input"], used["output"], used["cache_read"],
         used["cache_write"], cost, seconds, session),
    )


USAGE_SUMS = (
    "COUNT(u.id) AS turns, COALESCE(SUM(u.input), 0) AS input, COALESCE(SUM(u.output), 0) AS output, "
    "COALESCE(SUM(u.cache_read), 0) AS cache_read, COALESCE(SUM(u.cache_write), 0) AS cache_write, "
    "SUM(u.cost) AS cost, MAX(u.created) AS last"
)


def usage(profile_id: int) -> list[dict]:
    """The profile's courses that used an agent, costliest first, each with its lessons and the turns no lesson
    owns."""
    courses = rows(
        f"SELECT k.id, k.topic, k.archived, {USAGE_SUMS} FROM courses k JOIN usage u ON u.course_id = k.id "
        "WHERE k.profile_id = ? GROUP BY k.id ORDER BY COALESCE(SUM(u.cost), 0) DESC, k.id",
        profile_id,
    )
    for c in courses:
        c["lessons"] = rows(
            f"SELECT u.lesson_id AS id, l.title, l.phase, {USAGE_SUMS} FROM usage u LEFT JOIN lessons l ON l.id = u.lesson_id "
            "WHERE u.course_id = ? GROUP BY u.lesson_id ORDER BY MIN(u.id)",
            c["id"],
        )
        c["kinds"] = rows(
            f"SELECT u.kind, {USAGE_SUMS} FROM usage u WHERE u.course_id = ? GROUP BY u.kind ORDER BY COALESCE(SUM(u.cost), 0) DESC",
            c["id"],
        )
    return courses


def drop_content(lesson_ids: list[int], card_ids: list[int]) -> None:
    """Lessons and cards gone with everything recorded on them, the short cards split from them too; the caller holds
    the transaction."""
    lessons, cards = ",".join(map(str, lesson_ids)) or "NULL", ",".join(map(str, card_ids)) or "NULL"
    split = f"WITH RECURSIVE tree(id) AS (SELECT id FROM cards WHERE id IN ({cards}) UNION SELECT c.id FROM cards c JOIN tree ON c.parent_id = tree.id) SELECT id FROM tree"
    family = [r["id"] for r in rows(split)]
    family_ids = ",".join(map(str, family)) or "NULL"
    for sql in (
        f"DELETE FROM answers WHERE card_id IN ({family_ids})",
        f"DELETE FROM cards WHERE id IN ({family_ids})",
        f"DELETE FROM commands WHERE lesson_id IN ({lessons})",
        f"UPDATE usage SET lesson_id = NULL WHERE lesson_id IN ({lessons})",
        f"DELETE FROM blocks WHERE lesson_id IN ({lessons})",
        f"DELETE FROM messages WHERE lesson_id IN ({lessons})",
        f"DELETE FROM lessons WHERE id IN ({lessons})",
    ):
        conn.execute(sql)


def delete_course(course_id: int) -> None:
    """Remove a course and everything stored under it, all or nothing."""
    lessons = "SELECT id FROM lessons WHERE course_id = ?"
    conn.execute("BEGIN")
    try:
        for sql in (
            "DELETE FROM commands WHERE course_id = ?",
            "DELETE FROM usage WHERE course_id = ?",
            "DELETE FROM publish_edits WHERE course_id = ?",
            "DELETE FROM contributions WHERE course_id = ?",
            "UPDATE versions SET course_id = NULL WHERE course_id = ?",
            "DELETE FROM answers WHERE card_id IN (SELECT id FROM cards WHERE course_id = ?)",
            "DELETE FROM cards WHERE course_id = ?",
            f"DELETE FROM blocks WHERE lesson_id IN ({lessons})",
            f"DELETE FROM messages WHERE lesson_id IN ({lessons})",
            "DELETE FROM lessons WHERE course_id = ?",
            "DELETE FROM concepts WHERE course_id = ?",
            "DELETE FROM facts WHERE course_id = ?",
            "DELETE FROM recaps WHERE course_id = ?",
            "DELETE FROM courses WHERE id = ?",
        ):
            conn.execute(sql, (course_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def course(course_id: int) -> dict | None:
    c = row("SELECT * FROM courses WHERE id = ?", course_id)
    if c:
        c["ranking"] = json.loads(c["ranking"]) if c["ranking"] else []
    return c


def placement_areas(course_id: int) -> list[dict]:
    return rows("SELECT title, holds, lacks FROM placement_areas WHERE course_id = ? ORDER BY position", course_id)


def set_placement(course_id: int, level: str, summary: str, areas: list[dict]) -> None:
    """A placement result replaces the one before it, areas and all."""
    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE courses SET level = ?, placement = ? WHERE id = ?", (level, summary, course_id))
        conn.execute("DELETE FROM placement_areas WHERE course_id = ?", (course_id,))
        conn.executemany(
            "INSERT INTO placement_areas (course_id, position, title, holds, lacks) VALUES (?, ?, ?, ?, ?)",
            [(course_id, n, a["title"], a["holds"], a["lacks"]) for n, a in enumerate(areas, start=1)],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def set_ranking(course_id: int, ranking: list[dict]) -> None:
    conn.execute(
        "UPDATE courses SET ranking = ?, mechanism = ? WHERE id = ?",
        (json.dumps(ranking), ranking[0]["mechanism"], course_id),
    )


def create_lesson(
    course_id: int, title: str, phase: str, concept_id: int | None = None, questions: int | None = None, cards: int | None = None
) -> int:
    return conn.execute(
        "INSERT INTO lessons (course_id, title, phase, concept_id, session_id, questions, cards) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (course_id, title, phase, concept_id, str(uuid.uuid4()), questions, cards),
    ).lastrowid


def concepts(course_id: int) -> list[dict]:
    return rows("SELECT * FROM concepts WHERE course_id = ? ORDER BY position, id", course_id)


def concept_view(course_id: int) -> list[dict]:
    """Concepts with their mastery: the share of right latest answers, or full for a concept placed out; a practice
    unit is full once its lesson is finished. due counts the concept's review cards due now."""
    mastery = concept_mastery(course_id)
    due = {r["concept_id"]: r["n"] for r in rows(
        "SELECT concept_id, COUNT(*) AS n FROM cards WHERE course_id = ? AND due <= ? GROUP BY concept_id",
        course_id, datetime.now(timezone.utc).isoformat(),
    )}
    finished = {r["concept_id"] for r in rows(
        "SELECT DISTINCT l.concept_id FROM lessons l JOIN blocks b ON b.lesson_id = l.id WHERE l.course_id = ? AND b.kind = 'done'", course_id
    )}
    edges = needs(course_id)
    return [
        {**c, "mastery": (1.0 if c["id"] in finished else None) if c["kind"] == "practice" else mastery.get(c["id"], 1.0 if c["known"] else None),
         "due": due.get(c["id"], 0), "needs": edges.get(c["id"], [])}
        for c in concepts(course_id)
    ]


def needs(course_id: int) -> dict[int, list[int]]:
    """Each unit's prerequisites, as unit ids in map order."""
    edges: dict[int, list[int]] = {}
    for r in rows(
        "SELECT n.concept_id, n.needs_id FROM concept_needs n JOIN concepts k ON k.id = n.needs_id "
        "WHERE k.course_id = ? ORDER BY k.position, k.id", course_id,
    ):
        edges.setdefault(r["concept_id"], []).append(r["needs_id"])
    return edges


def set_needs(course_id: int, given: dict[str, list[str]], replace: bool, linked: bool) -> None:
    """Record prerequisites by unit title. replace drops every edge first; otherwise only the units given get new
    lists, and an edge the map's order no longer allows (a unit needing one placed after it) is dropped.
    linked marks the map as having its prerequisites worked out."""
    ids = {c["title"]: c["id"] for c in concepts(course_id) if c["kind"] == "concept"}
    course_units = "SELECT id FROM concepts WHERE course_id = ?"
    conn.execute("BEGIN")
    try:
        if replace:
            conn.execute(f"DELETE FROM concept_needs WHERE concept_id IN ({course_units})", (course_id,))
        else:
            conn.executemany("DELETE FROM concept_needs WHERE concept_id = ?", [(ids[t],) for t in given])
            conn.execute(
                f"DELETE FROM concept_needs WHERE concept_id IN ({course_units}) "
                "AND (SELECT position FROM concepts WHERE id = needs_id) >= (SELECT position FROM concepts WHERE id = concept_id)",
                (course_id,),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO concept_needs (concept_id, needs_id) VALUES (?, ?)",
            [(ids[t], ids[n]) for t, ns in given.items() for n in ns],
        )
        if linked:
            conn.execute("UPDATE courses SET prerequisites = 1 WHERE id = ?", (course_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _is_replay(course_id: int) -> bool:
    return row("SELECT mode FROM courses WHERE id = ?", course_id)["mode"] == "replay"


def set_known(course_id: int, known: list[str], unknown: list[str]) -> None:
    for flag, titles in ((1, known), (0, unknown)):
        conn.executemany("UPDATE concepts SET known = ? WHERE course_id = ? AND title = ? AND kind = 'concept'", [(flag, course_id, t) for t in titles])
    if not _is_replay(course_id):
        place_practice(course_id)


def set_concepts(course_id: int, modules: list[dict]) -> None:
    units = [(m, title) for m in modules for title in m["concepts"]]
    conn.executemany(
        "INSERT INTO concepts (course_id, module, title, known, position) VALUES (?, ?, ?, ?, ?)",
        [(course_id, m["title"], title, int(title in m["known"]), n) for n, (m, title) in enumerate(units, start=1)],
    )
    place_practice(course_id)


# A practice unit follows every PRACTICE_EVERY concept units the learner has to study.
PRACTICE_EVERY = 3


def practice_title(n: int) -> str:
    return f"Practice {n}"


def _card_due(card_id: int | None, now: str) -> bool:
    """Whether the card, or a live card split from it, is due for review."""
    return bool(card_id and row(_CARD_LINE + "SELECT 1 FROM cards k JOIN line ON line.id = k.id WHERE k.retired = 0 AND k.due <= ?", card_id, now))


def _place_unit(course_id: int, kept: list[dict], order: list[int], n: int, module: str) -> None:
    if kept:
        unit = kept.pop(0)
        conn.execute("UPDATE concepts SET module = ?, title = ? WHERE id = ?", (module, practice_title(n), unit["id"]))
        conn.execute("UPDATE lessons SET title = ? WHERE concept_id = ?", (practice_title(n), unit["id"]))
        order.append(unit["id"])
    else:
        order.append(conn.execute(
            "INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, ?, ?, 0, 0, 'practice')",
            (course_id, module, practice_title(n)),
        ).lastrowid)


def place_practice(course_id: int) -> None:
    """Lay the practice units of a learner's course out again: one after every PRACTICE_EVERY units not placed out,
    in the module of the unit before it. A practice unit that already has a lesson is kept, in map order and
    renumbered, at the end of the map when the rule no longer places it; one without a lesson is re-made."""
    if row("SELECT mode FROM courses WHERE id = ?", course_id)["mode"] == "teacher":
        return
    conn.execute(
        "DELETE FROM concepts WHERE course_id = ? AND kind = 'practice' "
        "AND id NOT IN (SELECT concept_id FROM lessons WHERE concept_id IS NOT NULL)", (course_id,)
    )
    kept = [c for c in concepts(course_id) if c["kind"] == "practice"]  # in map order, each with a lesson
    studied = [c for c in concepts(course_id) if c["kind"] == "concept"]
    order, to_study, n = [], 0, 0
    for c in studied:
        order.append(c["id"])
        to_study += not c["known"]
        if to_study and to_study % PRACTICE_EVERY == 0:
            n += 1
            _place_unit(course_id, kept, order, n, c["module"])
    while kept:  # kept units the rule no longer places close the map
        n += 1
        _place_unit(course_id, kept, order, n, studied[-1]["module"] if studied else kept[0]["module"])
    conn.executemany("UPDATE concepts SET position = ? WHERE id = ?", [(pos, cid) for pos, cid in enumerate(order, start=1)])


def _practice_scopes(units: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Each practice unit of a map, with the concept units since the one before it."""
    found, covered = [], []
    for unit in units:
        if unit["kind"] == "concept":
            covered.append(unit)
        else:
            found.append((unit, covered))
            covered = []
    return found


def _keep_practice(course_id: int, before: list[dict]) -> None:
    """Put a replay's practice units, which came with its version, in its revised map: each after the last of the units
    it covered in the map before and the new units that follow it in its module, in that unit's module if it shared
    one. One without a lesson goes when the new map left out every unit it covered."""
    studied = [c for c in concepts(course_id) if c["kind"] == "concept"]
    place = {c["id"]: n for n, c in enumerate(studied)}
    order = [((n, 0), c["id"]) for n, c in enumerate(studied)]
    had = {c["id"] for c in before}
    after = -1
    for n, (unit, covered) in enumerate(_practice_scopes(before), start=1):
        left = [c for c in covered if c["id"] in place]
        if covered and not left and not row("SELECT 1 FROM lessons WHERE concept_id = ?", unit["id"]):
            _drop_units({unit["title"]: unit}, {unit["title"]})
            continue
        if left:
            last = max(left, key=lambda c: place[c["id"]])
            after = place[last["id"]]
            while after + 1 < len(studied) and studied[after + 1]["id"] not in had and studied[after + 1]["module"] == studied[after]["module"]:
                after += 1
            if last["module"] == unit["module"]:
                conn.execute("UPDATE concepts SET module = ? WHERE id = ?", (studied[after]["module"], unit["id"]))
        order.append(((after, n), unit["id"]))
    conn.executemany("UPDATE concepts SET position = ? WHERE id = ?", [(pos, cid) for pos, (_, cid) in enumerate(sorted(order), start=1)])


def practice_scope(concept_id: int) -> list[dict]:
    """The concept units a practice unit covers: those between the previous practice unit and this one."""
    unit = row("SELECT * FROM concepts WHERE id = ?", concept_id)
    before = row(
        "SELECT COALESCE(MAX(position), -1) AS position FROM concepts WHERE course_id = ? AND kind = 'practice' AND position < ?",
        unit["course_id"], unit["position"],
    )["position"]
    return rows(
        "SELECT * FROM concepts WHERE course_id = ? AND kind = 'concept' AND position > ? AND position < ? ORDER BY position",
        unit["course_id"], before, unit["position"],
    )


def pull_forward(concept_id: int, now: str) -> int:
    """Make a concept's scheduled cards due now; returns how many moved."""
    return conn.execute(
        "UPDATE cards SET due = ? WHERE concept_id = ? AND scheduled = 1 AND (due IS NULL OR due > ?)", (now, concept_id, now)
    ).rowcount


def started_concepts(course_id: int) -> set[str]:
    """Titles of the concept units that already have a lesson."""
    return {
        r["title"]
        for r in rows("SELECT DISTINCT k.title FROM concepts k JOIN lessons l ON l.concept_id = k.id WHERE k.course_id = ? AND k.kind = 'concept'", course_id)
    }


def revise_concepts(course_id: int, modules: list[dict], renamed: dict[str, str], hours: int | None = None) -> list[str]:
    """Rewrite a course map in place. A unit that stays, by title, keeps its lessons, cards and progress; a unit
    that is gone is deleted, unless it has a lesson: then nothing changes and ValueError names it. A capstone
    goes to the module that holds most of its remaining units; one left without units, or without a module of
    its own, is removed. Returns the titles of the capstones removed."""
    # IMMEDIATE: this reads before it writes, and must not find the database changed under it in between.
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = concepts(course_id)
        _rename_units(course_id, renamed)
        existing = {c["title"]: c for c in concepts(course_id) if c["kind"] == "concept"}
        kept = _place_units(course_id, modules, existing)
        _drop_units(existing, existing.keys() - kept)
        removed = _rehome_capstones(course_id)
        if _is_replay(course_id):
            _keep_practice(course_id, before)
        else:
            place_practice(course_id)
        if hours:
            conn.execute("UPDATE courses SET hours = ? WHERE id = ?", (hours, course_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return removed


def _rename_units(course_id: int, renamed: dict[str, str]) -> None:
    # All renames are looked up before any is applied, so two units can swap titles.
    ids = {old: row("SELECT id FROM concepts WHERE course_id = ? AND title = ?", course_id, old)["id"] for old in renamed}
    for old, new in renamed.items():
        conn.execute("UPDATE concepts SET title = ? WHERE id = ?", (new, ids[old]))
        conn.execute("UPDATE lessons SET title = ? WHERE concept_id = ?", (new, ids[old]))


def _place_units(course_id: int, modules: list[dict], existing: dict[str, dict]) -> set[str]:
    """Each unit of the new map in its module and place, an existing one updated, a new one added; the titles placed."""
    practice = {c["title"] for c in concepts(course_id) if c["kind"] == "practice"}
    units = [(m, title) for m in modules for title in m["concepts"] if title not in practice]
    for n, (m, title) in enumerate(units, start=1):
        if unit := existing.get(title):
            known = int(title in m["known"] or unit["known"])
            conn.execute("UPDATE concepts SET module = ?, known = ?, position = ? WHERE id = ?", (m["title"], known, n, unit["id"]))
        else:
            conn.execute(
                "INSERT INTO concepts (course_id, module, title, known, position) VALUES (?, ?, ?, ?, ?)",
                (course_id, m["title"], title, int(title in m["known"]), n),
            )
    return {title for _, title in units}


def _drop_units(existing: dict[str, dict], titles: set[str]) -> None:
    """Delete the units the new map left out; a started one stops the revision with ValueError naming them."""
    gone = sorted(titles)
    if started := [t for t in gone if row("SELECT 1 FROM lessons WHERE concept_id = ?", existing[t]["id"])]:
        raise ValueError(started)
    for title in gone:
        conn.execute("UPDATE cards SET concept_id = NULL WHERE concept_id = ?", (existing[title]["id"],))
        conn.execute("DELETE FROM concepts WHERE id = ?", (existing[title]["id"],))


def _rehome_capstones(course_id: int) -> list[str]:
    """After a map revision: each capstone moves to the module with most of its remaining units. A module holds
    one capstone, so of two that claim the same module the one with more finished milestones stays."""
    claims = []
    for capstone in rows("SELECT * FROM capstones WHERE course_id = ?", course_id):
        home = row(
            "SELECT k.module, COUNT(*) AS units, SUM(m.done) AS done FROM milestones m JOIN concepts k ON k.id = m.concept_id "
            "WHERE m.capstone_id = ? GROUP BY k.module ORDER BY units DESC, MIN(k.position) LIMIT 1",
            capstone["id"],
        )
        total = row("SELECT COALESCE(SUM(done), 0) AS done FROM milestones WHERE capstone_id = ?", capstone["id"])["done"]
        claims.append((capstone, home["module"] if home else None, total))
        # Out of the way first: the modules are unique per course, and two capstones may trade places.
        conn.execute("UPDATE capstones SET module = ? WHERE id = ?", (f"\0{capstone['id']}", capstone["id"]))
    removed, taken = [], set()
    for capstone, module, _ in sorted(claims, key=lambda claim: (-claim[2], claim[0]["id"])):
        if module is None or module in taken:
            conn.execute("DELETE FROM capstones WHERE id = ?", (capstone["id"],))
            removed.append(capstone["title"])
        else:
            taken.add(module)
            conn.execute("UPDATE capstones SET module = ? WHERE id = ?", (module, capstone["id"]))
    return sorted(removed)


def lesson(lesson_id: int) -> dict | None:
    return row(
        "SELECT l.*, c.topic, c.slug, c.mechanism, c.level, c.lang, c.profile_id, c.details, c.hours, c.started, c.mode, c.pace, c.sitting, p.name AS profile, p.locale, k.title AS concept, k.module, k.unwritten "
        "FROM lessons l JOIN courses c ON c.id = l.course_id JOIN profiles p ON p.id = c.profile_id "
        "LEFT JOIN concepts k ON k.id = l.concept_id "
        "WHERE l.id = ?",
        lesson_id,
    )


def add_message(lesson_id: int, role: str, text: str) -> dict:
    message_id = conn.execute(
        "INSERT INTO messages (lesson_id, role, text) VALUES (?, ?, ?)", (lesson_id, role, text)
    ).lastrowid
    return row("SELECT * FROM messages WHERE id = ?", message_id)


def _block(b: dict | None) -> dict | None:
    if b:
        b["data"] = json.loads(b["data"]) if b["data"] else None
        b.pop("locked", None)
    return b


def block(block_id: int) -> dict | None:
    return _block(row("SELECT * FROM blocks WHERE id = ?", block_id))


def keyed(lesson: dict) -> bool:
    """Cards carry their key and explanation from the start: a teacher's material, or a lesson the learner takes
    offline and answers without the tutor."""
    return lesson["mode"] == "teacher" or bool(lesson["batch"])


def _shown(b: dict, with_key: bool) -> dict:
    data = b["data"] or {}
    if b["kind"] == "quiz" and data.get("answer") is None and not with_key:
        b["data"] = keyless(data)
    if b["kind"] == "outline":
        b["markdown"] = ticked_as_at(b["markdown"], data)
    if b["kind"] == "reading" and data.get("added"):
        data["added"] = own_words(b)
    return b


def own_words(reading: dict) -> list[str]:
    """The words its learner saved from a reading. An old install or copy also lists those its author saved, whose cards
    were never scheduled here."""
    from . import vocab  # its word lists are slow to load

    lang, added = reading["data"].get("lang"), reading["data"]["added"]
    if not isinstance(lang, str) or not isinstance(added, list):
        return added  # an install checks no shapes
    course, lang = row("SELECT course_id FROM lessons WHERE id = ?", reading["lesson_id"])["course_id"], lang.split("-")[0].lower()

    def waits(word) -> bool:
        card = word_card(course, lang, vocab.word_key(word, lang)) if isinstance(word, str) and word.strip() else None
        return bool(card) and not card["due"]

    return [w for w in added if not waits(w)]


def word_card(course_id: int, lang: str, lemma: str) -> dict | None:
    """The course's vocabulary card of a word, a scheduled one first. One that came with a course or a copy has no due
    until its learner saves the word."""
    return row("SELECT id, due FROM cards WHERE course_id = ? AND lang = ? AND lemma = ? AND vocab = 1 ORDER BY due IS NULL, id",
               course_id, lang, lemma)


def take_word(card_id: int, due: str, context: str) -> None:
    """Schedule a vocabulary card that came with the course for the learner who saves its word."""
    conn.execute("UPDATE cards SET due = ?, context = ? WHERE id = ?", (due, context, card_id))


def blocks(lesson_id: int) -> list[dict]:
    """The lesson's blocks as its reader gets them: a quiz without its key until it is answered, an outline without the
    ticks and a reading without the saved words of whoever it was imported or copied from."""
    found = [_block(b) for b in rows("SELECT * FROM blocks WHERE lesson_id = ? ORDER BY position, id", lesson_id)]
    with_key = bool(found) and keyed(lesson(lesson_id))
    return [_shown(b, with_key) for b in found]


def locked(block_id: int) -> dict:
    """The hints not yet given and the solution an imported task's author wrote, or the key an imported quiz came with;
    empty when there are none."""
    b = row("SELECT locked FROM blocks WHERE id = ?", block_id)
    return json.loads(b["locked"]) if b and b["locked"] else {}


def variants(course_id: int) -> list[dict]:
    """The course's variants whose original it holds too: a variant_of naming a block of another course is not followed."""
    return rows(
        "SELECT v.id, v.lesson_id, o.id AS original, o.key AS original_key, ol.concept_id AS original_concept FROM blocks v "
        "JOIN lessons vl ON vl.id = v.lesson_id JOIN blocks o ON o.id = json_extract(v.data, '$.variant_of') "
        "JOIN lessons ol ON ol.id = o.lesson_id AND ol.course_id = vl.course_id WHERE vl.course_id = ?",
        course_id,
    )


def set_original(variant_id: int, block_id: int | None) -> None:
    """Point a variant at the block it varies; None leaves it a task like any other."""
    if block_id is None:
        conn.execute("UPDATE blocks SET data = json_remove(data, '$.variant_of') WHERE id = ?", (variant_id,))
    else:
        conn.execute("UPDATE blocks SET data = json_set(data, '$.variant_of', ?) WHERE id = ?", (block_id, variant_id))


def set_block_markdown(block_id: int, markdown: str) -> dict:
    conn.execute("UPDATE blocks SET markdown = ? WHERE id = ?", (markdown, block_id))
    return block(block_id)


def delete_block(block_id: int) -> None:
    """The block and, for a quiz, its card; answers on that card go with it."""
    b = block(block_id)
    if not b:
        return
    conn.execute("DELETE FROM blocks WHERE id = ?", (block_id,))
    if b["kind"] == "quiz" and (card_id := (b["data"] or {}).get("card_id")):
        conn.execute("DELETE FROM answers WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM errors WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))


def move_block(block_id: int, direction: int) -> list[dict]:
    """Swap the block with its neighbour above (-1) or below (+1); returns the lesson's blocks in their new order."""
    b = block(block_id)
    order = blocks(b["lesson_id"])
    index = next(i for i, x in enumerate(order) if x["id"] == block_id)
    other = index + direction
    if 0 <= other < len(order):
        a, c = order[index], order[other]
        conn.execute("UPDATE blocks SET position = ? WHERE id = ?", (c["position"], a["id"]))
        conn.execute("UPDATE blocks SET position = ? WHERE id = ?", (a["position"], c["id"]))
    return blocks(b["lesson_id"])


def add_block(lesson_id: int, kind: str, markdown: str, data: dict | None = None) -> dict:
    block_id = conn.execute(
        "INSERT INTO blocks (lesson_id, kind, markdown, data) VALUES (?, ?, ?, ?)",
        (lesson_id, kind, markdown, json.dumps(data) if data else None),
    ).lastrowid
    conn.execute("UPDATE blocks SET position = id WHERE id = ?", (block_id,))
    return block(block_id)


def set_block_data(block_id: int, data: dict, locked: dict | None = None) -> dict:
    """locked: what stays locked once part of it moved into data, in the same write; None leaves it as it is."""
    conn.execute("UPDATE blocks SET data = ?, locked = COALESCE(?, locked) WHERE id = ?", (json.dumps(data), json.dumps(locked) if locked else None, block_id))
    return block(block_id)


def set_block(block_id: int, markdown: str, data: dict) -> dict:
    """Text and data in one write, for changes that must not land half-way."""
    conn.execute("UPDATE blocks SET markdown = ?, data = ? WHERE id = ?", (markdown, json.dumps(data), block_id))
    return block(block_id)


def add_card(course_id: int, concept_id: int | None, question: str, kind: str, options: list[str],
             answer_key: str, explanation: str, scheduled: bool, due: str | None = None, vocab: bool = False,
             translation: str = "", misconceptions: dict[str, str] | None = None, context: str = "", origin: str | None = None) -> int:
    """due makes the card reviewable from that moment without a first answer; vocab marks a vocabulary card;
    translation is the question in the learner's own language when it is written in the one being learned;
    misconceptions names, for a wrong option, the belief that leads to it; context is the sentence a word was met in;
    origin 'word' marks a word the learner saved from any text."""
    return conn.execute(
        "INSERT INTO cards (course_id, concept_id, question, kind, options, answer_key, explanation, scheduled, "
        "vocab, due, translation, misconceptions, context, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (course_id, concept_id, question, kind, json.dumps(options), answer_key, explanation, int(scheduled),
         int(vocab), due, translation, json.dumps(misconceptions or {}), context, origin),
    ).lastrowid


def vocabulary(course_id: int, now: str) -> dict:
    return row(
        "SELECT COUNT(*) AS total, COALESCE(SUM(due <= ?), 0) AS due FROM cards WHERE course_id = ? AND vocab = 1",
        now, course_id,
    )


def strand_counts(course_id: int) -> dict[str, int]:
    """How many lesson-area activities of each language-learning strand the course had in the last 7 days."""
    counts = {"input": 0, "output": 0, "language": 0, "fluency": 0}
    recent = rows(
        "SELECT b.kind, b.data FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
        "WHERE l.course_id = ? AND l.phase IN ('lesson', 'story', 'writing') AND b.created >= datetime('now', '-7 days')",
        course_id,
    )
    for b in recent:
        data = json.loads(b["data"]) if b["data"] else {}
        if b["kind"] == "reading":
            counts["input"] += 1
        elif b["kind"] == "speaking":
            counts["fluency" if data.get("speaking") == "read" else "output"] += 1
        elif data.get("writing"):
            counts["fluency" if data.get("fluency") else "output"] += 1
        else:
            counts["language"] += 1
    counts["output"] += row(
        "SELECT COUNT(DISTINCT l.id) AS n FROM lessons l JOIN messages m ON m.lesson_id = l.id "
        "WHERE l.course_id = ? AND l.phase = 'roleplay' AND m.role = 'learner' AND m.created >= datetime('now', '-7 days')",
        course_id,
    )["n"]
    return counts


def _card(c: dict | None) -> dict | None:
    if c:
        c["options"] = json.loads(c["options"])
        c["misconceptions"] = json.loads(c["misconceptions"])
    return c


def card(card_id: int) -> dict | None:
    return _card(row("SELECT * FROM cards WHERE id = ?", card_id))


def scheduled_cards(course_id: int) -> list[dict]:
    """The course's cards that come back in reviews, vocabulary cards aside."""
    return [_card(c) for c in rows(
        "SELECT * FROM cards WHERE course_id = ? AND scheduled = 1 AND retired = 0 AND vocab = 0 AND lemma IS NULL ORDER BY id", course_id,
    )]


def schedule_parts(card_id: int, fsrs: str, due: str) -> None:
    """A card made short before it was answered hands the schedule its answer gave it to its parts not yet answered."""
    conn.execute(
        _CARD_LINE + "UPDATE cards SET fsrs = ?, due = ? WHERE id IN (SELECT id FROM line) AND id != ? AND retired = 0 "
        "AND origin = 'short' AND NOT EXISTS (SELECT 1 FROM answers a WHERE a.card_id = cards.id)",
        (card_id, fsrs, due, card_id),
    )


def split_card(card_id: int, parts: list[dict], origin: str) -> list[int]:
    """Replace a review card by its parts. A card made short keeps its place in the schedule; the parts of a missed
    card start fresh and are due at once."""
    parent = card(card_id)
    keep = origin == "short"
    conn.execute("BEGIN")
    try:
        ids = [
            conn.execute(
                "INSERT INTO cards (course_id, concept_id, question, kind, options, answer_key, explanation, scheduled, "
                "fsrs, due, translation, parent_id, origin) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, '', ?, ?)",
                (parent["course_id"], parent["concept_id"], p["question"], p["kind"], json.dumps(p["options"]), p["answer_key"],
                 p["explanation"], parent["fsrs"] if keep else None, parent["due"] if keep else datetime.now(timezone.utc).isoformat(),
                 card_id, origin),
            ).lastrowid
            for p in parts
        ]
        conn.execute("UPDATE cards SET retired = 1 WHERE id = ?", (card_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return ids


def recall_days(card_id: int) -> int:
    """On how many separate (local) days the card was answered right since its last miss."""
    return row(
        "SELECT COUNT(DISTINCT date(created, 'localtime')) AS days FROM answers WHERE card_id = ? AND correct = 1 "
        "AND id > (SELECT relearn_after FROM cards WHERE id = ?)",
        card_id, card_id,
    )["days"]


def reset_recall(card_id: int) -> None:
    """A miss: the card's recall days start over from the answers after this point."""
    conn.execute("UPDATE cards SET relearn_after = (SELECT COALESCE(MAX(id), 0) FROM answers) WHERE id = ?", (card_id,))


def due_cards(profile_id: int, now: str) -> list[dict]:
    """A profile's cards whose review is due; confident misses and open notebook errors count as confident_miss, so they lead."""
    cards = rows(
        "SELECT k.*, c.topic, (k.confident_miss OR k.id IN "
        "(SELECT card_id FROM errors WHERE resolved = 0 AND card_id IS NOT NULL)) AS leads "
        "FROM cards k JOIN courses c ON c.id = k.course_id "
        "WHERE c.profile_id = ? AND c.archived = 0 AND k.retired = 0 AND k.due IS NOT NULL AND k.due <= ? "
        "ORDER BY leads DESC, k.due",
        profile_id, now,
    )
    return [_card({**c, "confident_miss": c.pop("leads")}) for c in cards]


def last_activity(profile_id: int) -> datetime | None:
    """When the learner last did something in any of their courses: answered a card, ran a command, or got a tutor
    reply, since every turn follows something the learner did (an attempt, a hint asked, a message, a lesson opened)."""
    last = row(
        "SELECT MAX(t) AS t FROM ("
        "SELECT a.created AS t FROM answers a JOIN cards k ON k.id = a.card_id JOIN courses c ON c.id = k.course_id WHERE c.profile_id = ? "
        "UNION ALL SELECT m.created FROM messages m JOIN lessons l ON l.id = m.lesson_id JOIN courses c ON c.id = l.course_id "
        "WHERE c.profile_id = ? "
        # commands keep an ISO time ('T', offset); cut it to the CURRENT_TIMESTAMP shape so the two compare as text
        "UNION ALL SELECT replace(substr(started, 1, 19), 'T', ' ') FROM commands WHERE profile_id = ? AND origin = 'learner')",
        profile_id, profile_id, profile_id,
    )["t"]
    return datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else None


def add_error(profile_id: int, course_id: int, kind: str, prompt: str, said: str, correct: str, explanation: str = "",
              card_id: int | None = None, misconception: str = "") -> int:
    """One open entry per card: a repeated miss updates what was said, and the belief behind it when one is named,
    instead of adding a row."""
    if card_id is not None:
        existing = row("SELECT id FROM errors WHERE card_id = ? AND resolved = 0", card_id)
        if existing:
            conn.execute(
                "UPDATE errors SET said = ?, misconception = COALESCE(NULLIF(?, ''), misconception), created = CURRENT_TIMESTAMP WHERE id = ?",
                (said, misconception, existing["id"]),
            )
            return existing["id"]
    return conn.execute(
        "INSERT INTO errors (profile_id, course_id, card_id, kind, prompt, said, correct, explanation, misconception) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, course_id, card_id, kind, prompt, said, correct, explanation, misconception),
    ).lastrowid


def errors(profile_id: int, course_id: int | None = None, open_only: bool = False, limit: int | None = None) -> list[dict]:
    where = ["e.profile_id = ?"]
    args: list = [profile_id]
    if course_id is None:
        where.append("c.archived = 0")
    else:
        where.append("e.course_id = ?")
        args.append(course_id)
    if open_only:
        where.append("e.resolved = 0")
    return rows(
        f"SELECT e.*, c.topic FROM errors e JOIN courses c ON c.id = e.course_id WHERE {' AND '.join(where)} "
        f"ORDER BY e.resolved, e.pinned DESC, e.id DESC{f' LIMIT {int(limit)}' if limit else ''}",
        *args,
    )


def correction_cards(course_id: int) -> set[int]:
    """The cards made from the learner's corrected text: they quote the learner, so they never leave the course."""
    return {r["card_id"] for r in rows(
        "SELECT card_id FROM errors WHERE course_id = ? AND kind = 'writing' AND card_id IS NOT NULL", course_id,
    )}


def private_cards(course_id: int) -> set[int]:
    """The cards that stay with the learner: their corrections, and the words they saved, which may come from a chat."""
    return correction_cards(course_id) | {r["id"] for r in rows("SELECT id FROM cards WHERE course_id = ? AND origin = 'word'", course_id)}


def update_error(error_id: int, note: str | None, pinned: bool | None, resolved: bool | None) -> dict | None:
    sets, args = [], []
    for col, val in (("note", note), ("pinned", pinned), ("resolved", resolved)):
        if val is not None:
            sets.append(f"{col} = ?")
            args.append(int(val) if isinstance(val, bool) else val)
    if sets:
        conn.execute(f"UPDATE errors SET {', '.join(sets)} WHERE id = ?", (*args, error_id))
    return row("SELECT e.*, c.topic FROM errors e JOIN courses c ON c.id = e.course_id WHERE e.id = ?", error_id)


def graded_answers(profile_id: int) -> list[dict]:
    return rows(
        "SELECT a.confidence, a.correct, a.created, k.question FROM answers a JOIN cards k ON k.id = a.card_id "
        "JOIN courses c ON c.id = k.course_id WHERE c.profile_id = ? AND a.correct IS NOT NULL AND a.stated = 1 ORDER BY a.created, a.id",
        profile_id,
    )


# A longer gap between two things happening in a lesson is time away from it, not time spent on it; a tutor turn
# the learner waits on counts whatever its length.
IDLE = timedelta(minutes=30)
UNITS_MEASURED = 8


def _covered(spans: list[tuple[datetime, datetime]]) -> timedelta:
    """The time the spans cover, overlaps counted once."""
    total, reach = timedelta(), None
    for start, end in sorted(spans):
        if reach is None or start > reach:
            total += end - start
        elif end > reach:
            total += end - reach
        reach = end if reach is None else max(reach, end)
    return total


def lesson_time(lesson_id: int) -> tuple[timedelta, bool]:
    """The active time of one lesson, time away cut out, the tutor's turns included; and whether the turns were timed
    (turn lengths are recorded only since they were added, so an older lesson is measured by its gaps alone)."""
    times = sorted(datetime.fromisoformat(r["created"]) for r in rows(
        "SELECT created FROM messages WHERE lesson_id = ? UNION ALL SELECT created FROM blocks WHERE lesson_id = ? "
        "UNION ALL SELECT a.created FROM answers a JOIN blocks b ON json_extract(b.data, '$.card_id') = a.card_id "
        "WHERE b.lesson_id = ?", lesson_id, lesson_id, lesson_id,
    ))
    spans = [(a, b) for a, b in pairwise(times) if b - a < IDLE]
    turns = rows("SELECT created, seconds FROM usage WHERE lesson_id = ? AND kind = 'lesson' AND seconds IS NOT NULL", lesson_id)
    for r in turns:
        end = datetime.fromisoformat(r["created"])
        spans.append((end - timedelta(seconds=r["seconds"]), end))
    return _covered(spans), bool(turns)


def unit_pace(profile_id: int) -> dict | None:
    """How long the learner's last UNITS_MEASURED finished units took, in any course, time away cut out: the units
    measured, active minutes per unit and per task (quick check, challenge or exercise), the tutor's turns included.
    None before two are done."""
    lessons = rows(
        "SELECT l.id FROM lessons l JOIN courses c ON c.id = l.course_id WHERE c.profile_id = ? AND c.mode = 'learner' "
        "AND l.phase = 'lesson' AND EXISTS (SELECT 1 FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done') "
        "ORDER BY l.id DESC LIMIT ?", profile_id, UNITS_MEASURED,
    )
    if len(lessons) < 2:
        return None
    spent, tasks = timedelta(), 0
    for lesson in lessons:
        spent += lesson_time(lesson["id"])[0]
        tasks += row(
            f"SELECT COUNT(*) AS n FROM blocks WHERE lesson_id = ? AND kind IN ({', '.join(repr(k) for k in EVIDENCE_KINDS)})", lesson["id"]
        )["n"]
    minutes = spent.total_seconds() / 60
    return {"units": len(lessons), "unit": minutes / len(lessons), "task": minutes / max(tasks, 1)}


def concept_mastery(course_id: int) -> dict[int, float]:
    """Per concept, the share of its cards whose latest graded answer was right. A card made short still counts
    until one of its parts is answered; a missed card replaced by its parts does not."""
    return {
        r["concept_id"]: r["mastery"]
        for r in rows(
            "WITH RECURSIVE answered(id) AS ("
            "SELECT k.parent_id FROM cards k JOIN answers a ON a.card_id = k.id WHERE a.correct IS NOT NULL AND k.parent_id IS NOT NULL "
            "UNION SELECT k.parent_id FROM cards k JOIN answered ON k.id = answered.id WHERE k.parent_id IS NOT NULL) "
            "SELECT k.concept_id, AVG(a.correct) AS mastery FROM cards k JOIN answers a ON a.id = "
            "(SELECT MAX(id) FROM answers WHERE card_id = k.id AND correct IS NOT NULL) "
            "WHERE k.course_id = ? AND k.concept_id IS NOT NULL AND (k.retired = 0 OR ("
            "EXISTS (SELECT 1 FROM cards p WHERE p.parent_id = k.id AND p.origin = 'short') AND k.id NOT IN answered)) "
            "GROUP BY k.concept_id",
            course_id,
        )
    }


def add_fact(course_id: int, text: str, about_learner: bool) -> None:
    """A fact about the learner belongs to the course's profile; any other fact belongs to the course."""
    if about_learner:
        profile_id = row("SELECT profile_id FROM courses WHERE id = ?", course_id)["profile_id"]
        conn.execute("INSERT INTO facts (profile_id, text) VALUES (?, ?)", (profile_id, text))
    else:
        conn.execute("INSERT INTO facts (course_id, text) VALUES (?, ?)", (course_id, text))


def facts(course_id: int) -> list[dict]:
    """Facts about the course's learner (course_id NULL) plus facts for this course."""
    return rows(
        "SELECT * FROM facts WHERE course_id = ? "
        "OR (course_id IS NULL AND profile_id = (SELECT profile_id FROM courses WHERE id = ?)) ORDER BY id",
        course_id, course_id,
    )


def learner_facts(profile_id: int) -> list[dict]:
    return rows("SELECT id, text FROM facts WHERE course_id IS NULL AND profile_id = ? ORDER BY id", profile_id)


def course_lang(course_id: int, lang: str) -> None:
    conn.execute("UPDATE courses SET lang = COALESCE(lang, ?) WHERE id = ?", (lang, course_id))


def vocab_tier(profile_id: int, lang: str, default: int) -> int:
    row_ = row("SELECT tier FROM vocab_tiers WHERE profile_id = ? AND lang = ?", profile_id, lang)
    return row_["tier"] if row_ else default


def set_vocab_tier(profile_id: int, lang: str, tier: int) -> None:
    conn.execute(
        "INSERT INTO vocab_tiers (profile_id, lang, tier) VALUES (?, ?, ?) "
        "ON CONFLICT(profile_id, lang) DO UPDATE SET tier = excluded.tier",
        (profile_id, lang, tier),
    )


def vocab_lemmas(profile_id: int, lang: str, states: tuple[str, ...] = ("known", "learning")) -> set[str]:
    marks = ",".join("?" * len(states))
    return {
        r["lemma"]
        for r in rows(f"SELECT lemma FROM vocab_knowledge WHERE profile_id = ? AND lang = ? AND state IN ({marks})",
                      profile_id, lang, *states)
    }


def vocab_states(profile_id: int, lang: str) -> dict[str, str]:
    """The state of each lemma the learner met: known, learning, or seen, which is only met in texts so far."""
    return {
        r["lemma"]: "seen" if r["state"] == "learning" and r["source"] == "reading" else r["state"]
        for r in rows("SELECT lemma, state, source FROM vocab_knowledge WHERE profile_id = ? AND lang = ?", profile_id, lang)
    }


def set_vocab(profile_id: int, lang: str, lemma: str, state: str, source: str, force: bool = False) -> None:
    """Record a lemma's state; 'known' is only downgraded to 'learning' when forced (a graded miss)."""
    state_sql = (
        "excluded.state" if force
        else "CASE WHEN vocab_knowledge.state = 'known' AND excluded.state = 'learning' THEN 'known' ELSE excluded.state END"
    )
    conn.execute(
        "INSERT INTO vocab_knowledge (profile_id, lang, lemma, state, source) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(profile_id, lang, lemma) DO UPDATE SET "
        f"state = {state_sql}, source = excluded.source, updated = CURRENT_TIMESTAMP",
        (profile_id, lang, lemma.lower(), state, source),
    )


def add_exposures(profile_id: int, lang: str, counts: dict[str, int], promote_at: int) -> None:
    """Count encounters in accepted texts; enough encounters turn a learning lemma into a known one."""
    conn.executemany(
        "INSERT INTO vocab_knowledge (profile_id, lang, lemma, state, exposures, source) VALUES (?, ?, ?, 'learning', ?, 'reading') "
        "ON CONFLICT(profile_id, lang, lemma) DO UPDATE SET exposures = vocab_knowledge.exposures + excluded.exposures, "
        "updated = CURRENT_TIMESTAMP",
        [(profile_id, lang, lemma.lower(), n) for lemma, n in counts.items()],
    )
    conn.execute(
        "UPDATE vocab_knowledge SET state = 'known' WHERE profile_id = ? AND lang = ? AND state = 'learning' AND exposures >= ?",
        (profile_id, lang, promote_at),
    )


def series(course_id: int) -> dict | None:
    return row("SELECT * FROM series WHERE course_id = ?", course_id)


def start_series(course_id: int, title: str, characters: str, synopsis: str) -> None:
    conn.execute("INSERT INTO series (course_id, title, characters, synopsis) VALUES (?, ?, ?, ?)", (course_id, title, characters, synopsis))


def add_episode(course_id: int, recap: str) -> int:
    if not series(course_id):
        raise ValueError("no series for this course")
    conn.execute(
        "UPDATE series SET episodes = episodes + 1, synopsis = synopsis || ? WHERE course_id = ?",
        (f"\n{recap}", course_id),
    )
    return series(course_id)["episodes"]


def add_source(course_id: int, name: str, size: int) -> dict:
    source_id = conn.execute("INSERT INTO sources (course_id, name, size) VALUES (?, ?, ?)", (course_id, name, size)).lastrowid
    return row("SELECT * FROM sources WHERE id = ?", source_id)


def sources(course_id: int) -> list[dict]:
    return rows("SELECT * FROM sources WHERE course_id = ? ORDER BY id", course_id)


def finish_source(source_id: int, sections: list[tuple[str, str]], error: str | None = None) -> dict | None:
    """Store a processed file's sections in one transaction; None when the file was removed meanwhile."""
    if not row("SELECT id FROM sources WHERE id = ?", source_id):
        return None
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM source_sections WHERE source_id = ?", (source_id,))
        conn.executemany("INSERT INTO source_sections (source_id, title, text) VALUES (?, ?, ?)", [(source_id, t, x) for t, x in sections])
        conn.execute(
            "UPDATE sources SET status = ?, error = ?, sections = ? WHERE id = ?",
            ("failed" if error else "ready", error, len(sections), source_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return row("SELECT * FROM sources WHERE id = ?", source_id)


def delete_source(source_id: int) -> None:
    conn.execute("DELETE FROM source_sections WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))


def source_section(section_id: int) -> dict | None:
    return row(
        "SELECT s.*, src.name, src.course_id FROM source_sections s JOIN sources src ON src.id = s.source_id WHERE s.id = ?",
        section_id,
    )


def add_capstone(course_id: int, module: str, title: str, brief: str, folder: str, milestones: list[tuple[int, str]]) -> dict:
    capstone_id = conn.execute(
        "INSERT INTO capstones (course_id, module, title, brief, folder) VALUES (?, ?, ?, ?, ?)", (course_id, module, title, brief, folder)
    ).lastrowid
    conn.executemany(
        "INSERT INTO milestones (capstone_id, concept_id, deliverable) VALUES (?, ?, ?)",
        [(capstone_id, concept_id, deliverable) for concept_id, deliverable in milestones],
    )
    return capstones(course_id, capstone_id)[0]


def capstones(course_id: int, capstone_id: int | None = None) -> list[dict]:
    """A course's capstone projects with their milestones in map order."""
    out = []
    for c in rows("SELECT * FROM capstones WHERE course_id = ?" + (" AND id = ?" if capstone_id else ""), *(course_id, capstone_id) if capstone_id else (course_id,)):
        c["milestones"] = rows(
            "SELECT m.*, k.title AS concept FROM milestones m JOIN concepts k ON k.id = m.concept_id WHERE m.capstone_id = ? ORDER BY k.position, k.id",
            c["id"],
        )
        c["done"] = sum(m["done"] for m in c["milestones"])
        out.append(c)
    return out


def milestone_for(concept_id: int) -> dict | None:
    """The capstone and milestone a concept carries, with its position in the module."""
    m = row(
        "SELECT m.*, c.title AS capstone, c.brief, c.folder, c.module, c.id AS capstone_id FROM milestones m "
        "JOIN capstones c ON c.id = m.capstone_id WHERE m.concept_id = ?",
        concept_id,
    )
    if m:
        order = [x["concept_id"] for x in rows("SELECT m.concept_id FROM milestones m JOIN concepts k ON k.id = m.concept_id WHERE m.capstone_id = ? ORDER BY k.position, k.id", m["capstone_id"])]
        m["position"], m["total"] = order.index(concept_id) + 1, len(order)
    return m


def finish_milestone(milestone_id: int) -> None:
    conn.execute("UPDATE milestones SET done = 1 WHERE id = ?", (milestone_id,))


# --- Claims: what the learner was taught, as true statements, with links and the evidence of how they did ---------
CLAIM_KINDS = ("follows", "supports", "contrasts")
EVIDENCE_KINDS = ("quiz", "challenge", "exercise")


def _match(query: str) -> str:
    """A full-text query that matches any of the words, with nothing in it read as FTS syntax."""
    return " OR ".join(f'"{w}"' for w in re.findall(r"\w+", query.lower()))


def search_claims(profile_id: int, query: str, limit: int) -> list[dict]:
    """The profile's claims best matching the words of query, with the courses they came from."""
    if not (match := _match(query)):
        return []
    return [
        {**c, "courses": [r["topic"] for r in rows(
            "SELECT DISTINCT k.topic FROM claim_sources s JOIN lessons l ON l.id = s.lesson_id JOIN courses k ON k.id = l.course_id "
            "WHERE s.claim_id = ? ORDER BY k.id", c["id"],
        )]}
        for c in rows(
            "SELECT c.id, c.text, c.wrong FROM claim_fts f JOIN claims c ON c.id = f.rowid "
            "WHERE claim_fts MATCH ? AND c.profile_id = ? ORDER BY bm25(claim_fts) LIMIT ?",
            match, profile_id, limit,
        )
    ]


def claim(claim_id: int) -> dict | None:
    return row("SELECT * FROM claims WHERE id = ?", claim_id)


def same_claim(profile_id: int, text: str) -> dict | None:
    """A claim of the profile worded the same, ignoring case and spacing."""
    return row("SELECT * FROM claims WHERE profile_id = ? AND lower(text) = ?", profile_id, " ".join(text.split()).lower())


def record_claims(profile_id: int, lesson_id: int, claims: list[dict], edges: list[tuple[str, str, str]]) -> dict[str, int]:
    """Write one lesson's claims at once. Each entry has a key, then either an existing id or a new text, and the
    evidence block ids; edges join keys. Returns each key's claim id."""
    conn.execute("BEGIN")
    try:
        ids = {}
        for c in claims:
            ids[c["key"]] = c["id"] if c.get("id") else conn.execute(
                "INSERT INTO claims (profile_id, text) VALUES (?, ?)", (profile_id, " ".join(c["text"].split()))
            ).lastrowid
            conn.execute("INSERT OR IGNORE INTO claim_sources (claim_id, lesson_id) VALUES (?, ?)", (ids[c["key"]], lesson_id))
            conn.executemany(
                "INSERT OR IGNORE INTO claim_evidence (claim_id, block_id) VALUES (?, ?)", [(ids[c["key"]], b) for b in c["evidence"]]
            )
        conn.executemany(
            "INSERT OR IGNORE INTO claim_edges (from_id, to_id, kind) VALUES (?, ?, ?)", [(ids[a], ids[b], kind) for a, b, kind in edges]
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return ids


def _verdict(block: dict) -> str | None:
    """What one piece of evidence says: held, shaky, or nothing yet."""
    d = block["data"] or {}
    if block["kind"] == "quiz":
        return _quiz_verdict(d)
    if d.get("solved") and d.get("solution") is None:
        return "held"
    if d.get("solved") or d.get("gave_up") or d.get("solution") is not None:
        return "shaky"
    return None


_CARD_LINE = "WITH RECURSIVE line(id) AS (SELECT ? UNION SELECT k.id FROM cards k JOIN line ON k.parent_id = line.id) "


def _card_verdicts(card_id: int) -> list[tuple[str, str]]:
    """Every graded answer to a card and to the parts it was split into, in the lesson and in review: when, and held or shaky."""
    return [
        (a["created"], "held" if a["correct"] and a["confidence"] >= 0.5 else "shaky")
        for a in rows(_CARD_LINE + "SELECT a.created, a.correct, a.confidence FROM answers a JOIN line ON line.id = a.card_id "
                      "WHERE a.correct IS NOT NULL ORDER BY a.id", card_id)
    ]


def _evidence_verdicts(block: dict) -> list[tuple[str, str]]:
    """(when, verdict) of one piece of evidence: every review of a quiz's card, or the block's own verdict."""
    card_id = (block["data"] or {}).get("card_id")
    if block["kind"] == "quiz" and card_id:
        return _card_verdicts(card_id)
    return [(block["created"], verdict)] if (verdict := _verdict(block)) else []


def _quiz_verdict(d: dict) -> str | None:
    """Held when answered right and sure enough, shaky otherwise; nothing before it is graded."""
    if d.get("correct") is None:
        return None
    return "held" if d["correct"] and not d.get("unknown") and d.get("confidence", 0) >= 0.5 else "shaky"


def _claim_evidence(profile_id: int, now: str) -> tuple[dict[int, tuple[str, str]], set[int]]:
    latest: dict[int, tuple[str, str]] = {}
    due: set[int] = set()
    for e in rows(
        "SELECT e.claim_id, b.* FROM claim_evidence e JOIN blocks b ON b.id = e.block_id JOIN claims c ON c.id = e.claim_id "
        "WHERE c.profile_id = ? AND c.wrong = 0 ORDER BY b.id", profile_id,
    ):
        block = _block({k: v for k, v in e.items() if k != "claim_id"})
        for when, verdict in _evidence_verdicts(block):
            if e["claim_id"] not in latest or when >= latest[e["claim_id"]][0]:
                latest[e["claim_id"]] = (when, verdict)
        if _card_due((block["data"] or {}).get("card_id"), now):
            due.add(e["claim_id"])
    return latest, due


def claim_states(profile_id: int, now: str) -> dict[int, str]:
    """Each claim's state from its latest evidence, in a lesson or in a review of its cards: held (fading once a linked
    review card is due), shaky, or unseen."""
    states = {c["id"]: "unseen" for c in rows("SELECT id FROM claims WHERE profile_id = ? AND wrong = 0", profile_id)}
    latest, due = _claim_evidence(profile_id, now)
    for claim_id, (_, verdict) in latest.items():
        states[claim_id] = "fading" if verdict == "held" and claim_id in due else verdict
    return states


def unextracted(course_id: int) -> list[int]:
    """The course's finished unit and practice lessons whose claims were not taken out yet, or that have a check
    answered since they were, oldest first."""
    return [r["id"] for r in rows(
        "SELECT l.id FROM lessons l JOIN courses c ON c.id = l.course_id WHERE l.course_id = ? AND c.mode = 'learner' "
        "AND l.phase IN ('lesson', 'practice') "
        "AND EXISTS (SELECT 1 FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done') "
        "AND (l.extracted IS NULL OR EXISTS (SELECT 1 FROM blocks b WHERE b.lesson_id = l.id "
        f"AND b.kind IN ({', '.join(repr(k) for k in EVIDENCE_KINDS)}) AND b.created > datetime(l.extracted) "
        "AND json_extract(b.data, '$.pretest') IS NOT 1 AND (json_extract(b.data, '$.correct') IS NOT NULL "
        "OR json_extract(b.data, '$.solved') OR json_extract(b.data, '$.gave_up')))) ORDER BY l.id",
        course_id,
    )]


def extracted_through(lesson_id: int) -> int | None:
    """The last block of a lesson that its claims were taken out of, or None when they never were."""
    return row(
        "SELECT MAX(b.id) AS id FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.id = ? AND b.created <= datetime(l.extracted)",
        lesson_id,
    )["id"]


def mark_extracted(lesson_id: int) -> None:
    conn.execute("UPDATE lessons SET extracted = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), lesson_id))


def unit_claims(concept_ids: list[int]) -> list[dict]:
    """The claims taken out of the lessons of these units, each once, in the order they were first recorded."""
    if not concept_ids:
        return []
    marks = ", ".join("?" * len(concept_ids))
    return rows(
        "SELECT DISTINCT c.id, c.profile_id, c.text FROM claims c JOIN claim_sources s ON s.claim_id = c.id JOIN lessons l ON l.id = s.lesson_id "
        f"WHERE l.concept_id IN ({marks}) AND c.wrong = 0 ORDER BY c.id",
        *concept_ids,
    )


def bridges(profile_id: int, course_id: int, query: str, limit: int) -> list[dict]:
    """Claims from the learner's other courses that match query, none taken from this course; each with the course it
    came from and what it contrasts with."""
    found = []
    for c in search_claims(profile_id, query, limit * 4):
        if c["wrong"] or row(
            "SELECT 1 FROM claim_sources s JOIN lessons l ON l.id = s.lesson_id WHERE s.claim_id = ? AND l.course_id = ?", c["id"], course_id
        ):
            continue
        c["contrasts"] = [r["text"] for r in rows(
            "SELECT k.text FROM claim_edges e JOIN claims k ON k.id = CASE WHEN e.from_id = ? THEN e.to_id ELSE e.from_id END "
            "WHERE e.kind = 'contrasts' AND ? IN (e.from_id, e.to_id) AND k.wrong = 0", c["id"], c["id"],
        )]
        found.append(c)
        if len(found) == limit:
            break
    return found


def graph(profile_id: int, now: str) -> dict:
    """The profile's claims for the graph page: each with its state, courses, source lessons and evidence; and the
    links between them. Claims the learner marked wrong are left out."""
    states = claim_states(profile_id, now)
    sources: dict[int, list[dict]] = {}
    for r in rows(
        "SELECT s.claim_id, l.id, l.title, l.concept_id, k.id AS course_id, k.topic FROM claim_sources s JOIN lessons l ON l.id = s.lesson_id "
        "JOIN courses k ON k.id = l.course_id JOIN claims c ON c.id = s.claim_id WHERE c.profile_id = ? ORDER BY l.id", profile_id,
    ):
        sources.setdefault(r.pop("claim_id"), []).append(r)
    evidence: dict[int, list[dict]] = {}
    for r in rows(
        "SELECT e.claim_id, b.* FROM claim_evidence e JOIN blocks b ON b.id = e.block_id JOIN claims c ON c.id = e.claim_id "
        "WHERE c.profile_id = ? ORDER BY b.id", profile_id,
    ):
        claim_id = r.pop("claim_id")
        block = _block(r)
        evidence.setdefault(claim_id, []).append(
            {"block_id": block["id"], "lesson_id": block["lesson_id"], "kind": block["kind"], "markdown": block["markdown"][:300], "verdict": _verdict(block)}
        )
    claims = [
        {**c, "state": states[c["id"]], "sources": sources.get(c["id"], []), "evidence": evidence.get(c["id"], [])}
        for c in rows("SELECT id, text, created FROM claims WHERE profile_id = ? AND wrong = 0 ORDER BY id", profile_id)
    ]
    edges = rows(
        "SELECT e.from_id, e.to_id, e.kind FROM claim_edges e JOIN claims a ON a.id = e.from_id JOIN claims b ON b.id = e.to_id "
        "WHERE a.profile_id = ? AND a.wrong = 0 AND b.wrong = 0", profile_id,
    )
    return {"claims": claims, "edges": edges}


CONTRIBUTION_COLUMNS = "id, course_id, repo, title, size, gap, uses, first_step, issue, status, lesson_id"


def contributions(course_id: int) -> list[dict]:
    """The course's contribution suggestions still on offer or taken up, the taken ones first."""
    return rows(
        f"SELECT {CONTRIBUTION_COLUMNS} FROM contributions WHERE course_id = ? AND status != 'dismissed' ORDER BY status = 'open', id",
        course_id,
    )


def contribution(contribution_id: int) -> dict | None:
    return row(f"SELECT {CONTRIBUTION_COLUMNS} FROM contributions WHERE id = ?", contribution_id)


def set_contributions(course_id: int, entries: list[dict], written_for: str) -> None:
    """The new suggestions replace the ones on offer; one the learner took up stays. written_for: the course's finish."""
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM contributions WHERE course_id = ? AND status = 'open'", (course_id,))
        conn.executemany(
            "INSERT INTO contributions (course_id, repo, title, size, gap, uses, first_step, issue) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(course_id, e["repo"], e["title"], e["size"], e["gap"], e["uses"], e["first_step"], e["issue"] or None) for e in entries],
        )
        conn.execute("UPDATE courses SET contributions_for = ? WHERE id = ?", (written_for, course_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def suggestions(profile_id: int, status: str = "open") -> list[dict]:
    return rows("SELECT id, title, pitch, kind, builds_on FROM suggestions WHERE profile_id = ? AND status = ? ORDER BY id", profile_id, status)


def suggestion_basis(profile_id: int) -> tuple[int, int]:
    """What suggestions are written from: the learner's mapped courses and their finished lessons."""
    courses = row(
        "SELECT COUNT(*) AS n FROM courses c WHERE c.profile_id = ? AND c.mode = 'learner' AND EXISTS (SELECT 1 FROM concepts k WHERE k.course_id = c.id)",
        profile_id,
    )["n"]
    lessons = row(
        "SELECT COUNT(*) AS n FROM lessons l JOIN courses c ON c.id = l.course_id WHERE c.profile_id = ? AND c.mode = 'learner' "
        "AND l.phase IN ('lesson', 'practice') AND EXISTS (SELECT 1 FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done')",
        profile_id,
    )["n"]
    return courses, lessons


def set_suggestions(profile_id: int, entries: list[dict], retire: bool) -> None:
    """The new suggestions replace the open ones. retire: the learner asked for others, so the old ones are not offered again."""
    conn.execute("BEGIN")
    try:
        if retire:
            conn.execute("UPDATE suggestions SET status = 'dismissed' WHERE profile_id = ? AND status = 'open'", (profile_id,))
        else:
            conn.execute("DELETE FROM suggestions WHERE profile_id = ? AND status = 'open'", (profile_id,))
        conn.executemany(
            "INSERT INTO suggestions (profile_id, title, pitch, kind, builds_on) VALUES (?, ?, ?, ?, ?)",
            [(profile_id, e["title"], e["pitch"], e["kind"], e["builds_on"]) for e in entries],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def update_claim(claim_id: int, text: str | None, wrong: bool | None) -> None:
    if text is not None:
        conn.execute("UPDATE claims SET text = ? WHERE id = ?", (" ".join(text.split()), claim_id))
    if wrong is not None:
        conn.execute("UPDATE claims SET wrong = ? WHERE id = ?", (int(wrong), claim_id))


def merge_claims(claim_id: int, into: int) -> None:
    """Fold a duplicate into another claim: its sources, evidence and links move over, then it is gone."""
    conn.execute("BEGIN")
    try:
        for table, column in (("claim_sources", "claim_id"), ("claim_evidence", "claim_id"), ("claim_edges", "from_id"), ("claim_edges", "to_id")):
            conn.execute(f"UPDATE OR IGNORE {table} SET {column} = ? WHERE {column} = ?", (into, claim_id))
        conn.execute("DELETE FROM claim_edges WHERE from_id = to_id")
        conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- Recap: a finished course told back to the learner ---------------------------------------------------------------
def _module_done(module: str, units: list[dict], finished: dict, begun: set[int], projects: list[dict]) -> bool:
    """Its units finished or placed out, or all its projects built."""
    if all(u["id"] in finished or (u["known"] and u["id"] not in begun) for u in units if u["module"] == module):
        return True
    built = [k for k in projects if k["module"] == module]
    return bool(built) and all(k["done"] == len(k["milestones"]) for k in built)


def course_finished(course_id: int) -> str | None:
    """When a learner's course was finished, or None while it is not: every module is done, its units finished or
    placed out, or all its projects built. The time is when its last unit was finished."""
    course = row("SELECT mode FROM courses WHERE id = ?", course_id)
    units = concepts(course_id)
    if not course or course["mode"] == "teacher" or not units:
        return None
    finished = {r["concept_id"]: r["at"] for r in rows(
        "SELECT l.concept_id, MIN(b.created) AS at FROM lessons l JOIN blocks b ON b.lesson_id = l.id "
        "WHERE l.course_id = ? AND l.concept_id IS NOT NULL AND b.kind = 'done' GROUP BY l.concept_id", course_id,
    )}
    begun = {r["concept_id"] for r in rows("SELECT DISTINCT concept_id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL", course_id)}
    projects = capstones(course_id)
    if not all(_module_done(module, units, finished, begun, projects) for module in dict.fromkeys(u["module"] for u in units)):
        return None
    return max(finished.values(), default=None) or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _recap(r: dict | None) -> dict | None:
    if r:
        r["narrative"] = json.loads(r["narrative"]) if r["narrative"] else None
        r["positions"] = json.loads(r["positions"]) if r["positions"] else None
    return r


def recap(course_id: int) -> dict | None:
    return _recap(row("SELECT * FROM recaps WHERE course_id = ?", course_id))


def sync_recap(course_id: int) -> dict | None:
    """The course's recap brought up to date with the course: finishing gives it its finish time and makes it new
    again; growing past the finish takes the time away, and the narrative stays until the course is finished again.
    None for a course never finished."""
    at = course_finished(course_id)
    current = recap(course_id)
    if at and not current:
        conn.execute("INSERT INTO recaps (course_id, finished) VALUES (?, ?)", (course_id, at))
    elif current and bool(current["finished"]) != bool(at):
        conn.execute("UPDATE recaps SET finished = ?, seen = 0 WHERE course_id = ?", (at, course_id))
    else:
        return current
    return recap(course_id)


def set_recap(course_id: int, **fields) -> None:
    """seen, narrative or positions of a recap; narrative and positions are stored as JSON."""
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = [json.dumps(v) if k in ("narrative", "positions") else v for k, v in fields.items()]
    conn.execute(f"UPDATE recaps SET {sets} WHERE course_id = ?", (*values, course_id))


def fixed_at(card_id: int, after: str) -> str | None:
    """The first right answer to a card or its parts after a time: when a mistake on it was put right."""
    return row(_CARD_LINE + "SELECT MIN(a.created) AS at FROM answers a JOIN line ON line.id = a.card_id WHERE a.correct = 1 AND a.created > ?",
               card_id, after)["at"]
