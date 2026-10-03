import json
import os
import re
import shutil
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("WISE_SCHOLAR_DB", ROOT / "data" / "wise-scholar.db"))
WORKSPACE = Path(os.environ.get("WISE_SCHOLAR_WORKSPACE", ROOT / "workspace"))

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
]

DB_PATH.parent.mkdir(exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
_version = conn.execute("PRAGMA user_version").fetchone()[0]
if 0 < _version < len(MIGRATIONS):
    # Keep the database as it was before this upgrade, in case a migration goes wrong.
    shutil.copy(DB_PATH, DB_PATH.with_name(f"{DB_PATH.name}.v{_version}.bak"))
for _n, _script in enumerate(MIGRATIONS[_version:], start=_version + 1):
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
    return rows(
        "SELECT p.*, (SELECT COUNT(*) FROM courses c WHERE c.profile_id = p.id) AS courses FROM profiles p ORDER BY p.id"
    )


def profile(profile_id: int) -> dict | None:
    return row("SELECT * FROM profiles WHERE id = ?", profile_id)


def create_course(topic: str, profile_id: int) -> dict:
    base = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "course"
    slug, n = base, 2
    while row("SELECT 1 FROM courses WHERE slug = ?", slug):
        slug, n = f"{base}-{n}", n + 1
    course_id = conn.execute(
        "INSERT INTO courses (topic, slug, profile_id) VALUES (?, ?, ?)", (topic, slug, profile_id)
    ).lastrowid
    create_lesson(course_id, "Interview", "interview")
    return course(course_id)


def delete_course(course_id: int) -> None:
    """Remove a course and everything stored under it, all or nothing."""
    lessons = "SELECT id FROM lessons WHERE course_id = ?"
    conn.execute("BEGIN")
    try:
        for sql in (
            "DELETE FROM answers WHERE card_id IN (SELECT id FROM cards WHERE course_id = ?)",
            "DELETE FROM cards WHERE course_id = ?",
            f"DELETE FROM blocks WHERE lesson_id IN ({lessons})",
            f"DELETE FROM messages WHERE lesson_id IN ({lessons})",
            "DELETE FROM lessons WHERE course_id = ?",
            "DELETE FROM concepts WHERE course_id = ?",
            "DELETE FROM facts WHERE course_id = ?",
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


def set_ranking(course_id: int, ranking: list[dict]) -> None:
    conn.execute(
        "UPDATE courses SET ranking = ?, mechanism = ? WHERE id = ?",
        (json.dumps(ranking), ranking[0]["mechanism"], course_id),
    )


def create_lesson(course_id: int, title: str, phase: str, concept_id: int | None = None) -> int:
    return conn.execute(
        "INSERT INTO lessons (course_id, title, phase, concept_id, session_id) VALUES (?, ?, ?, ?, ?)",
        (course_id, title, phase, concept_id, str(uuid.uuid4())),
    ).lastrowid


def concepts(course_id: int) -> list[dict]:
    return rows("SELECT * FROM concepts WHERE course_id = ? ORDER BY id", course_id)


def concept_view(course_id: int) -> list[dict]:
    """Concepts with their mastery: the share of right latest answers, or full for a concept placed out."""
    mastery = concept_mastery(course_id)
    return [{**c, "mastery": mastery.get(c["id"], 1.0 if c["known"] else None)} for c in concepts(course_id)]


def set_known(course_id: int, known: list[str], unknown: list[str]) -> None:
    for flag, titles in ((1, known), (0, unknown)):
        conn.executemany("UPDATE concepts SET known = ? WHERE course_id = ? AND title = ?", [(flag, course_id, t) for t in titles])


def set_concepts(course_id: int, modules: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO concepts (course_id, module, title, known) VALUES (?, ?, ?, ?)",
        [(course_id, m["title"], title, int(title in m["known"])) for m in modules for title in m["concepts"]],
    )


def lesson(lesson_id: int) -> dict | None:
    return row(
        "SELECT l.*, c.topic, c.slug, c.mechanism, c.level, c.lang, c.profile_id, p.name AS profile, k.title AS concept, k.module "
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
    return b


def block(block_id: int) -> dict | None:
    return _block(row("SELECT * FROM blocks WHERE id = ?", block_id))


def blocks(lesson_id: int) -> list[dict]:
    return [_block(b) for b in rows("SELECT * FROM blocks WHERE lesson_id = ? ORDER BY id", lesson_id)]


def add_block(lesson_id: int, kind: str, markdown: str, data: dict | None = None) -> dict:
    block_id = conn.execute(
        "INSERT INTO blocks (lesson_id, kind, markdown, data) VALUES (?, ?, ?, ?)",
        (lesson_id, kind, markdown, json.dumps(data) if data else None),
    ).lastrowid
    return block(block_id)


def set_block_data(block_id: int, data: dict) -> dict:
    conn.execute("UPDATE blocks SET data = ? WHERE id = ?", (json.dumps(data), block_id))
    return block(block_id)


def add_card(course_id: int, concept_id: int | None, question: str, kind: str, options: list[str],
             answer_key: str, explanation: str, scheduled: bool, due: str | None = None, vocab: bool = False) -> int:
    """due makes the card reviewable from that moment without a first answer; vocab marks a vocabulary card."""
    return conn.execute(
        "INSERT INTO cards (course_id, concept_id, question, kind, options, answer_key, explanation, scheduled, "
        "vocab, due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (course_id, concept_id, question, kind, json.dumps(options), answer_key, explanation, int(scheduled),
         int(vocab), due),
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
        "WHERE l.course_id = ? AND l.phase = 'lesson' AND b.created >= datetime('now', '-7 days')",
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
    return counts


def _card(c: dict | None) -> dict | None:
    if c:
        c["options"] = json.loads(c["options"])
    return c


def card(card_id: int) -> dict | None:
    return _card(row("SELECT * FROM cards WHERE id = ?", card_id))


def due_cards(profile_id: int, now: str) -> list[dict]:
    """A profile's cards whose review is due; confident misses and open notebook errors count as confident_miss, so they lead."""
    cards = rows(
        "SELECT k.*, c.topic, (k.confident_miss OR k.id IN "
        "(SELECT card_id FROM errors WHERE resolved = 0 AND card_id IS NOT NULL)) AS leads "
        "FROM cards k JOIN courses c ON c.id = k.course_id "
        "WHERE c.profile_id = ? AND c.archived = 0 AND k.due IS NOT NULL AND k.due <= ? "
        "ORDER BY leads DESC, k.due",
        profile_id, now,
    )
    return [_card({**c, "confident_miss": c.pop("leads")}) for c in cards]


def add_error(profile_id: int, course_id: int, kind: str, prompt: str, said: str, correct: str, explanation: str = "",
              card_id: int | None = None) -> int:
    """One open entry per card: a repeated miss updates what was said instead of adding a row."""
    if card_id is not None:
        existing = row("SELECT id FROM errors WHERE card_id = ? AND resolved = 0", card_id)
        if existing:
            conn.execute("UPDATE errors SET said = ?, created = CURRENT_TIMESTAMP WHERE id = ?", (said, existing["id"]))
            return existing["id"]
    return conn.execute(
        "INSERT INTO errors (profile_id, course_id, card_id, kind, prompt, said, correct, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, course_id, card_id, kind, prompt, said, correct, explanation),
    ).lastrowid


def errors(profile_id: int, course_id: int | None = None, open_only: bool = False, limit: int | None = None) -> list[dict]:
    where = ["e.profile_id = ?", "c.archived = 0"]
    args: list = [profile_id]
    if course_id is not None:
        where.append("e.course_id = ?")
        args.append(course_id)
    if open_only:
        where.append("e.resolved = 0")
    return rows(
        f"SELECT e.*, c.topic FROM errors e JOIN courses c ON c.id = e.course_id WHERE {' AND '.join(where)} "
        f"ORDER BY e.resolved, e.pinned DESC, e.id DESC{f' LIMIT {int(limit)}' if limit else ''}",
        *args,
    )


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
        "SELECT a.confidence, a.correct FROM answers a JOIN cards k ON k.id = a.card_id "
        "JOIN courses c ON c.id = k.course_id WHERE c.profile_id = ? AND a.correct IS NOT NULL",
        profile_id,
    )


def concept_mastery(course_id: int) -> dict[int, float]:
    """Per concept, the share of its cards whose latest graded answer was right."""
    return {
        r["concept_id"]: r["mastery"]
        for r in rows(
            "SELECT k.concept_id, AVG(a.correct) AS mastery FROM cards k JOIN answers a ON a.id = "
            "(SELECT MAX(id) FROM answers WHERE card_id = k.id AND correct IS NOT NULL) "
            "WHERE k.course_id = ? AND k.concept_id IS NOT NULL GROUP BY k.concept_id",
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
