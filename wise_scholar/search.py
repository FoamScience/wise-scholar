"""Search of one course by its words and by meaning: its sources, lesson cards, chats and the learner's code. Each
passage is kept with its text and, once `make search` installed model2vec, a vector; a search brings the course's
passages up to date first, so nothing has to be told when a card, a message or a file changes. Without model2vec
the search goes by the words alone."""
import importlib.util
import os
import re
import threading
from pathlib import Path

from wordfreq import zipf_frequency

from . import db

MODEL = os.environ.get("WISE_SCHOLAR_SEARCH_MODEL", "minishlab/potion-multilingual-128M")
KINDS = ("source", "card", "chat", "code")
MEANING = 0.4  # cosine a passage needs to come up by meaning alone; unrelated text sits near 0.3 with this model
CANDIDATES = 50  # taken from each of the two rankings before they are fused
FUSION = 60  # the k of reciprocal rank fusion
SNIPPET = 200
CODE_SUFFIXES = {
    ".py", ".lean", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt",
    ".sh", ".sql", ".r", ".jl", ".hs", ".ml", ".rb", ".lua", ".m", ".tex", ".md", ".toml", ".yaml", ".yml",
}
# Folders of installed or generated files: a toolchain unpacked into tools/, build output, dependencies.
SKIPPED = {"tools", "out", "build", "dist", "target", "node_modules", "__pycache__"}
CODE_BYTES = 200_000
CODE_LINES = 60
COMMON = 5.9  # Zipf frequency from which a word (how, the, de, à) is left out of the keyword half
COMMON_IN = ("en", "fr", "ar", "de")
MARK = ("\ue000", "\ue001")  # around matched words in a snippet; callers swap them for their own marks

_model = None
_loading = threading.Lock()
_writing = threading.Lock()


def available() -> bool:
    return importlib.util.find_spec("model2vec") is not None


def encode(texts: list[str]):
    """Unit vectors for the texts, as a numpy array. The model loads on the first call."""
    import numpy as np

    global _model
    with _loading:
        if _model is None:
            from model2vec import StaticModel

            _model = StaticModel.from_pretrained(MODEL)
    vectors = _model.encode(texts)
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)


def _code(slug: str) -> dict[tuple[str, str], tuple[None, str, str]]:
    root = db.WORKSPACE / slug
    found = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIPPED)
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix.lower() not in CODE_SUFFIXES or path.is_symlink() or path.stat().st_size > CODE_BYTES:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(root).as_posix()
            for start in range(0, len(lines), CODE_LINES):
                chunk = "\n".join(lines[start:start + CODE_LINES])
                if chunk.strip():
                    ref = f"{relative}:{start + 1}-{min(start + CODE_LINES, len(lines))}"
                    found["code", ref] = (None, ref, chunk)
    return found


def _wanted(course: dict) -> dict[tuple[str, str], tuple[int | None, str, str]]:
    """Every passage the course has now: (kind, ref) to (lesson id, title, text)."""
    wanted = {
        ("source", str(s["id"])): (None, s["title"], s["text"])
        for s in db.rows(
            "SELECT s.id, s.title, s.text FROM source_sections s JOIN sources src ON src.id = s.source_id "
            "WHERE src.course_id = ? AND src.status = 'ready'",
            course["id"],
        )
    }
    for b in db.rows(
        "SELECT b.id, b.kind, b.markdown, l.id AS lesson_id, l.title FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
        "WHERE l.course_id = ? AND trim(b.markdown) != ''",
        course["id"],
    ):
        wanted["card", str(b["id"])] = (b["lesson_id"], f"{b['title']} · {b['kind']}", b["markdown"])
    for m in db.rows(
        "SELECT m.id, m.role, m.text, l.id AS lesson_id, l.title FROM messages m JOIN lessons l ON l.id = m.lesson_id "
        "WHERE l.course_id = ? AND trim(m.text) != ''",
        course["id"],
    ):
        wanted["chat", str(m["id"])] = (m["lesson_id"], f"{m['title']} · {m['role']}", m["text"])
    return wanted | _code(course["slug"])


def _vectors(texts: list[str]) -> list[bytes | None]:
    if not texts or not available():
        return [None] * len(texts)
    return [v.astype("float32").tobytes() for v in encode(texts)]


def refresh(course_id: int) -> None:
    """Bring the course's passages in line with its content: gone ones out, new and changed ones in, and a vector
    for each passage that has none while model2vec is installed."""
    course = db.course(course_id)
    with _writing:
        wanted = _wanted(course)
        kept = {
            (p["kind"], p["ref"]): p
            for p in db.rows(
                "SELECT id, kind, ref, lesson_id, title, text, vector IS NULL AS bare FROM passages WHERE course_id = ?", course_id
            )
        }
        stale = [p["id"] for key, p in kept.items() if (p["lesson_id"], p["title"], p["text"]) != wanted.get(key)]
        fresh = [(key, value) for key, value in wanted.items() if key not in kept or kept[key]["id"] in stale]
        bare = [p for p in kept.values() if p["bare"] and p["id"] not in stale] if available() else []
        if not stale and not fresh and not bare:
            return
        vectors = _vectors([f"{title}\n{text}" for _, (_, title, text) in fresh] + [f"{p['title']}\n{p['text']}" for p in bare])
        db.conn.execute("BEGIN")
        try:
            db.conn.executemany("DELETE FROM passages WHERE id = ?", [(i,) for i in stale])
            db.conn.executemany(
                "INSERT INTO passages (course_id, kind, ref, lesson_id, title, text, vector) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (course_id, kind, ref, lesson_id, title, text, vector)
                    for ((kind, ref), (lesson_id, title, text)), vector in zip(fresh, vectors)
                ],
            )
            db.conn.executemany(
                "UPDATE passages SET vector = ? WHERE id = ?", [(vector, p["id"]) for p, vector in zip(bare, vectors[len(fresh):])]
            )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise


def search(course_id: int, query: str, n: int, kinds: tuple[str, ...] = KINDS) -> list[dict]:
    """The course's passages of these kinds best matching the query by its words or its meaning, best first. A
    snippet marks the matched words with MARK when the words matched; otherwise it is the passage's opening."""
    if not query.strip():
        return []
    refresh(course_id)
    among = f"p.course_id = ? AND p.kind IN ({', '.join('?' * len(kinds))})"
    lexical = []
    if words := _keywords(query):
        lexical = db.rows(
            f"SELECT p.id, snippet(passage_fts, 1, ?, ?, '…', 24) AS snippet FROM passage_fts "
            f"JOIN passages p ON p.id = passage_fts.rowid WHERE passage_fts MATCH ? AND {among} ORDER BY rank LIMIT ?",
            *MARK, words, course_id, *kinds, CANDIDATES,
        )
    meaning = _by_meaning(query, among, course_id, kinds) if available() else []
    fused: dict[int, float] = {}
    for ranking in ([p["id"] for p in lexical], meaning):
        for rank, passage_id in enumerate(ranking):
            fused[passage_id] = fused.get(passage_id, 0) + 1 / (FUSION + rank)
    best = sorted(fused, key=fused.get, reverse=True)[:n]
    if not best:
        return []
    snippets = {p["id"]: p["snippet"] for p in lexical}
    found = {
        p["id"]: p
        for p in db.rows(
            f"SELECT p.id, p.kind, p.ref, p.lesson_id, l.concept_id, p.title, p.text FROM passages p "
            f"LEFT JOIN lessons l ON l.id = p.lesson_id WHERE p.id IN ({', '.join('?' * len(best))})",
            *best,
        )
    }
    return [found[i] | {"snippet": snippets.get(i) or _opening(found[i]["text"])} for i in best]


def _by_meaning(query: str, among: str, course_id: int, kinds: tuple[str, ...]) -> list[int]:
    import numpy as np

    stored = db.rows(f"SELECT p.id, p.vector FROM passages p WHERE {among} AND p.vector IS NOT NULL", course_id, *kinds)
    if not stored:
        return []
    scores = np.frombuffer(b"".join(p["vector"] for p in stored), dtype=np.float32).reshape(len(stored), -1) @ encode([query])[0]
    return [stored[i]["id"] for i in np.argsort(-scores)[:CANDIDATES] if scores[i] >= MEANING]


def _keywords(query: str) -> str:
    """A full-text query matching any of the query's uncommon words, with nothing in it read as FTS syntax."""
    words = dict.fromkeys(w for w in re.findall(r"\w+", query.lower()) if max(zipf_frequency(w, lang) for lang in COMMON_IN) < COMMON)
    return " OR ".join(f'"{w}"' for w in words)


def _opening(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET else flat[:SNIPPET] + "…"


if __name__ == "__main__":
    encode(["the model is fetched once and kept in the Hugging Face cache"])
    print(f"search by meaning is ready with {MODEL}")
