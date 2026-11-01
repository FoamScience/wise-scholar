"""A published course version as a portable bundle: a zip of manifest.json and assets named by their sha256.

The manifest carries the course's content only: map, lessons with their blocks, cards, exercise starter files, the
sources the author chose and the setup commands the author let reach the internet. Nothing of the record that
measures the author comes along: answers, chat, facts, placement, the interview. The version id is the sha256 of
the manifest, which names every asset by hash, so a version cannot change under its id.
"""

import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, ValidationError

from . import course_files, crafted, db, figures

SCHEMA = 1
LICENCES = ("CC-BY-SA-4.0", "CC-BY-4.0", "CC-BY-NC-SA-4.0", "all-rights-reserved")
BLOCK_KINDS = ("prose", "example", "quiz", "challenge", "exercise", "figure", "plot", "outline", "reading", "vocab")
LESSON_PHASES = ("lesson", "practice")
# What a bundle may weigh, packed and unpacked; a source alone may be 50 MB and a course holds 200 MB of them.
BUNDLE_LIMIT = 256 * 1024 * 1024
UNPACKED_LIMIT = 512 * 1024 * 1024
MANIFEST_LIMIT = 32 * 1024 * 1024
ASSETS_LIMIT = 2000
FIGURE_LIMIT = crafted.MAX_SVG * 12
_ASSET = re.compile(r"assets/[0-9a-f]{64}")

KeyStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
HashStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Unit(BaseModel):
    key: KeyStr
    module: str = Field(max_length=300)
    title: str = Field(min_length=1, max_length=300)
    kind: Literal["concept", "practice"]
    written: bool
    needs: list[KeyStr] = Field(default=[], max_length=50)
    hash: HashStr


class Milestone(BaseModel):
    unit: KeyStr
    deliverable: str = Field(max_length=4000)


class Capstone(BaseModel):
    module: str = Field(max_length=300)
    title: str = Field(max_length=300)
    brief: str = Field(max_length=20000)
    folder: str = Field(max_length=200)
    milestones: list[Milestone] = Field(max_length=100)


class Card(BaseModel):
    key: KeyStr
    unit: KeyStr | None = None
    question: str = Field(min_length=1, max_length=20000)
    kind: Literal["choice", "open", "sort"]
    options: list = Field(max_length=50)
    answer_key: str = Field(max_length=20000)
    explanation: str = Field(max_length=20000)
    scheduled: bool
    vocab: bool
    lemma: str | None = Field(default=None, max_length=200)
    lang: str | None = Field(default=None, max_length=20)
    translation: str = Field(default="", max_length=20000)


class Block(BaseModel):
    key: KeyStr
    kind: Literal[BLOCK_KINDS]  # type: ignore[valid-type]
    markdown: str = Field(max_length=200000)
    data: dict | None = None


class Lesson(BaseModel):
    key: KeyStr
    unit: KeyStr | None = None
    title: str = Field(min_length=1, max_length=300)
    phase: Literal[LESSON_PHASES]  # type: ignore[valid-type]
    summary: str = Field(default="", max_length=4000)
    blocks: list[Block] = Field(max_length=500)


class File(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    asset: HashStr


class Section(BaseModel):
    title: str = Field(max_length=1000)
    text: str


class Source(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    asset: HashStr
    sections: list[Section] = Field(max_length=20000)


class Credit(BaseModel):
    topic: str = Field(max_length=300)
    version: HashStr
    number: int


class Version(BaseModel):
    number: int = Field(ge=1)
    notes: str = Field(max_length=4000)
    licence: Literal[LICENCES]  # type: ignore[valid-type]
    forkable: bool
    published: str = Field(max_length=40)
    credits: list[Credit] = Field(max_length=100)


class Course(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    lang: str | None = Field(default=None, max_length=20)
    details: str | None = Field(default=None, max_length=20000)
    hours: float | None = None
    mechanism: str | None = Field(default=None, max_length=100)
    ranking: list = Field(default=[], max_length=50)
    prerequisites: bool = False
    cover: str | None = None
    cover_alt: str | None = Field(default=None, max_length=1000)


class Manifest(BaseModel):
    schema_: Literal[1] = Field(alias="schema")
    course: Course
    version: Version
    units: list[Unit] = Field(max_length=1000)
    capstones: list[Capstone] = Field(max_length=100)
    lessons: list[Lesson] = Field(max_length=2000)
    cards: list[Card] = Field(max_length=20000)
    files: list[File] = Field(max_length=2000)
    sources: list[Source] = Field(max_length=20)
    setup: list[str] = Field(max_length=100)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _block_data(block: dict, card_keys: dict[int, str]) -> dict | None:
    """A block's material without the author's record; a quiz names its card by key, a figure keeps its drawing."""
    if not block["data"]:
        return None
    data = db._fresh(json.loads(block["data"]))
    for gone in ("crafted", "previous", "answer_id", "due", "card_id"):
        data.pop(gone, None)
    raw = json.loads(block["data"])
    if raw.get("card_id") is not None:
        data["card"] = card_keys.get(int(raw["card_id"]))
    return data


def _starters(block: dict, workspace: Path) -> tuple[dict[str, str], list[str]]:
    """An exercise's starter files: kept with the block since starters were recorded, else the files as they are on
    disk now, which may hold the author's own work; the second list names those."""
    data = json.loads(block["data"] or "{}")
    if isinstance(data.get("starter"), dict):
        return {p: c for p, c in data["starter"].items() if isinstance(c, str)}, []
    found = {p: course_files.read_text(workspace, p) for p in data.get("files", [])}
    found = {p: c for p, c in found.items() if c is not None}
    return found, list(found)


def finished_lessons(course_id: int) -> set[int]:
    return {r["id"] for r in db.rows(
        "SELECT DISTINCT l.id FROM lessons l JOIN blocks b ON b.lesson_id = l.id WHERE l.course_id = ? AND b.kind = 'done' "
        "AND l.phase IN ('lesson', 'practice')", course_id,
    )}


def written_units(course_id: int) -> set[int]:
    """The units whose lesson reached its end: only these carry lessons and cards into a version; the rest of the
    map ships as coming later."""
    return {r["concept_id"] for r in db.rows(
        f"SELECT concept_id FROM lessons WHERE id IN ({','.join('?' * len(done))}) AND concept_id IS NOT NULL", *done,
    )} if (done := finished_lessons(course_id)) else set()


def setup_commands(course_id: int) -> list[str]:
    """The commands the author allowed internet for that ended well, in order, each once."""
    seen = []
    for r in db.rows(
        "SELECT command FROM commands WHERE course_id = ? AND origin = 'network' AND consent = 'allowed' AND exit_code = 0 ORDER BY id",
        course_id,
    ):
        if r["command"] not in seen:
            seen.append(r["command"])
    return seen


def preview(course_id: int) -> dict:
    """What publishing would carry, for the author to check first: the sources to choose from, the exercises whose
    starter files come from the workspace as it is now, and the setup commands."""
    course = db.course(course_id)
    workspace = db.WORKSPACE / course["slug"]
    from_disk = []
    for b in db.rows(
        "SELECT b.*, l.title AS lesson FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
        "WHERE l.course_id = ? AND b.kind = 'exercise' AND l.phase IN ('lesson', 'practice') ORDER BY b.id",
        course_id,
    ):
        _, disk = _starters(b, workspace)
        if disk and b["lesson_id"] in finished_lessons(course_id):
            from_disk.append({"block": b["id"], "lesson": b["lesson"], "files": disk})
    return {
        "sources": [{"id": s["id"], "name": s["name"], "size": s["size"]} for s in db.sources(course_id) if s["status"] == "ready"],
        "from_workspace": from_disk,
        "setup": setup_commands(course_id),
        "written": len(written_units(course_id)),
        "units": len(db.concepts(course_id)),
        "versions": versions(course_id),
        "forked_from": _origin(course),
        "licences": list(LICENCES),
    }


def _origin(course: dict) -> dict | None:
    if not course.get("source_version"):
        return None
    v = db.row("SELECT * FROM versions WHERE hash = ?", course["source_version"])
    return v and {"topic": v["topic"], "number": v["number"], "hash": v["hash"], "forkable": bool(v["forkable"])}


def versions(course_id: int) -> list[dict]:
    return [
        {k: v[k] for k in ("hash", "number", "notes", "licence", "forkable", "published", "written", "units")}
        for v in db.rows("SELECT * FROM versions WHERE course_id = ? ORDER BY number DESC", course_id)
    ]


def build(course_id: int, *, notes: str, licence: str, forkable: bool, sources: list[int], source_dir: Path) -> tuple[dict, dict[str, bytes]]:
    """The manifest of the course as it is now and the assets it names."""
    course = db.course(course_id)
    assets: dict[str, bytes] = {}

    def asset(data: bytes) -> str:
        digest = sha(data)
        assets[digest] = data
        return digest

    units = db.concepts(course_id)
    unit_keys = {u["id"]: u["key"] for u in units}
    written = written_units(course_id)
    needs = db.needs(course_id)
    cards = [k for k in db.rows("SELECT * FROM cards WHERE course_id = ? AND parent_id IS NULL ORDER BY id", course_id)
             if k["concept_id"] is None or k["concept_id"] in written]
    card_keys = {k["id"]: k["key"] for k in cards}
    workspace = db.WORKSPACE / course["slug"]
    lessons, files = [], {}
    for lesson in db.rows("SELECT * FROM lessons WHERE course_id = ? AND phase IN ('lesson', 'practice') ORDER BY id", course_id):
        if lesson["concept_id"] not in written and not (lesson["concept_id"] is None and lesson["id"] in finished_lessons(course_id)):
            continue
        blocks, summary = [], ""
        for b in db.rows("SELECT * FROM blocks WHERE lesson_id = ? ORDER BY position, id", lesson["id"]):
            if b["kind"] == "done":
                summary = b["markdown"]
            if b["kind"] not in BLOCK_KINDS:
                continue
            data = _block_data(b, card_keys)
            if b["kind"] == "exercise":
                starters, _ = _starters(b, workspace)
                files.update(starters)
                data.pop("starter", None)
            blocks.append({"key": b["key"], "kind": b["kind"], "markdown": b["markdown"], "data": data})
        lessons.append({"key": lesson["key"], "unit": unit_keys.get(lesson["concept_id"]), "title": lesson["title"], "phase": lesson["phase"], "summary": summary, "blocks": blocks})
    card_rows = [
        {"key": k["key"], "unit": unit_keys.get(k["concept_id"]), "question": k["question"], "kind": k["kind"],
         "options": json.loads(k["options"]), "answer_key": k["answer_key"], "explanation": k["explanation"],
         "scheduled": bool(k["scheduled"]), "vocab": bool(k["vocab"]), "lemma": k["lemma"], "lang": k["lang"], "translation": k["translation"] or ""}
        for k in cards
    ]
    unit_rows = []
    for u in units:
        content = {
            "unit": {k: u[k] for k in ("module", "title", "kind")},
            "lessons": [{k: v for k, v in lesson.items() if k != "key"} for lesson in lessons if lesson["unit"] == u["key"]],
            "cards": [{k: v for k, v in c.items() if k != "key"} for c in card_rows if c["unit"] == u["key"]],
        }
        unit_rows.append({"key": u["key"], "module": u["module"], "title": u["title"], "kind": u["kind"], "written": u["id"] in written,
                          "needs": [unit_keys[n] for n in needs.get(u["id"], []) if n in unit_keys], "hash": sha(canonical(content))})
    chosen = []
    for s in db.sources(course_id):
        if s["id"] not in sources or s["status"] != "ready":
            continue
        path = next((source_dir / str(course_id)).glob(f"{s['id']}-*"), None)
        if not path:
            continue
        sections = db.rows("SELECT title, text FROM source_sections WHERE source_id = ? ORDER BY id", s["id"])
        chosen.append({"name": s["name"], "asset": asset(path.read_bytes()), "sections": sections})
    origin = db.row("SELECT * FROM versions WHERE hash = ?", course["source_version"]) if course.get("source_version") else None
    credits = [*json.loads(origin["credits"]), {"topic": origin["topic"], "version": origin["hash"], "number": origin["number"]}] if origin else []
    number = (db.row("SELECT MAX(number) AS n FROM versions WHERE course_id = ?", course_id)["n"] or 0) + 1
    manifest = {
        "schema": SCHEMA,
        "course": {"topic": course["topic"], "lang": course["lang"], "details": course["details"], "hours": course["hours"],
                   "mechanism": course["mechanism"], "ranking": course["ranking"], "prerequisites": bool(course["prerequisites"]),
                   "cover": course["cover"], "cover_alt": course["cover_alt"]},
        "version": {"number": number, "notes": notes.strip(), "licence": licence, "forkable": forkable,
                    "published": datetime.now(timezone.utc).isoformat(timespec="seconds"), "credits": credits},
        "units": unit_rows,
        "capstones": [
            {"module": c["module"], "title": c["title"], "brief": c["brief"], "folder": c["folder"],
             "milestones": [{"unit": unit_keys[m["concept_id"]], "deliverable": m["deliverable"]} for m in c["milestones"] if m["concept_id"] in unit_keys]}
            for c in db.capstones(course_id)
        ],
        "lessons": lessons,
        "cards": card_rows,
        "files": [{"path": p, "asset": asset(c.encode())} for p, c in sorted(files.items())],
        "sources": chosen,
        "setup": setup_commands(course_id),
    }
    Manifest.model_validate(manifest)
    return manifest, assets


def publish(course_id: int, *, notes: str, licence: str, forkable: bool, sources: list[int], source_dir: Path, store: Path) -> dict:
    """Freeze the course as its next version: the bundle lands in store, named by the version id."""
    manifest, assets = build(course_id, notes=notes, licence=licence, forkable=forkable, sources=sources, source_dir=source_dir)
    version_hash, data = pack(manifest, assets)
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{version_hash}.zip").write_bytes(data)
    v = manifest["version"]
    db.conn.execute(
        "INSERT INTO versions (hash, course_id, number, topic, notes, licence, forkable, credits, setup, written, units, published) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_hash, course_id, v["number"], manifest["course"]["topic"], v["notes"], licence, int(forkable), json.dumps(v["credits"]),
         json.dumps(manifest["setup"]), sum(u["written"] for u in manifest["units"]), len(manifest["units"]), v["published"]),
    )
    return {"hash": version_hash, "number": v["number"], "size": len(data)}


def pack(manifest: dict, assets: dict[str, bytes]) -> tuple[str, bytes]:
    """The version id and the zip; the same manifest and assets always pack to the same bytes."""
    body = canonical(manifest)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [("manifest.json", body), *sorted((f"assets/{h}", d) for h, d in assets.items())]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return sha(body), out.getvalue()


def unpack(data: bytes) -> tuple[str, Manifest, dict[str, bytes]]:
    """Read and check a bundle from anyone: its size, its names, every asset against its hash and every one the
    manifest names. Raises ValueError with what is wrong."""
    if len(data) > BUNDLE_LIMIT:
        raise ValueError("the bundle is larger than 256 MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("not a course bundle (not a zip file)") from None
    infos = z.infolist()
    if len(infos) > ASSETS_LIMIT + 1 or sum(i.file_size for i in infos) > UNPACKED_LIMIT:
        raise ValueError("the bundle holds too much")
    names = [i.filename for i in infos]
    if "manifest.json" not in names or any(n != "manifest.json" and not _ASSET.fullmatch(n) for n in names):
        raise ValueError("not a course bundle (unexpected files inside)")
    if z.getinfo("manifest.json").file_size > MANIFEST_LIMIT:
        raise ValueError("the manifest is too large")
    body = z.read("manifest.json")
    try:
        manifest = Manifest.model_validate_json(body)
    except ValidationError as e:
        raise ValueError(f"the manifest does not hold a course: {e.errors()[0]['loc']} {e.errors()[0]['msg']}") from None
    assets = {}
    for name in names:
        if name == "manifest.json":
            continue
        content = z.read(name)
        if sha(content) != name.removeprefix("assets/"):
            raise ValueError("an asset does not match its name")
        assets[name.removeprefix("assets/")] = content
    named = {f.asset for f in manifest.files} | {s.asset for s in manifest.sources}
    if missing := named - assets.keys():
        raise ValueError(f"{len(missing)} assets the manifest names are missing")
    keys = {u.key for u in manifest.units}
    if any(n not in keys for u in manifest.units for n in u.needs) or any(
        x.unit and x.unit not in keys for x in [*manifest.lessons, *manifest.cards]
    ) or any(m.unit not in keys for c in manifest.capstones for m in c.milestones):
        raise ValueError("the manifest names units it does not hold")
    unwritten = {u.key for u in manifest.units if not u.written}
    if any(x.unit in unwritten for x in [*manifest.lessons, *manifest.cards]):
        raise ValueError("the manifest holds lessons for units it says are not written")
    return sha(body), manifest, assets


def _clean_block(block: Block, card_ids: dict[str, int]) -> dict | None:
    """A block from someone else, made safe to show and to hand to the tutor."""
    data = dict(block.data or {})
    if block.kind == "figure":
        data = {"svg": figures.clean(str(data.get("svg", "")), limit=FIGURE_LIMIT), "alt": str(data.get("alt", ""))[:2000],
                "credits": data.get("credits") if isinstance(data.get("credits"), list) else []}
    if block.kind == "quiz":
        key = data.pop("card", None)
        if key not in card_ids:
            raise ValueError("a quiz names a card the bundle does not hold")
        data["card_id"] = card_ids[key]
    data["imported"] = True
    return data


def install(profile_id: int, version_hash: str, manifest: Manifest, assets: dict[str, bytes], source_dir: Path) -> dict:
    """A new course of the profile in replay mode, made from the bundle, all or nothing for the rows; returns it."""
    c = manifest.course
    cover = figures.clean(c.cover) if c.cover else None
    db.conn.execute("BEGIN")
    try:
        if not db.row("SELECT 1 FROM versions WHERE hash = ?", version_hash):
            v = manifest.version
            db.conn.execute(
                "INSERT INTO versions (hash, course_id, number, topic, notes, licence, forkable, credits, setup, written, units, published) "
                "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (version_hash, v.number, c.topic, v.notes, v.licence, int(v.forkable), json.dumps([x.model_dump() for x in v.credits]),
                 json.dumps(manifest.setup), sum(u.written for u in manifest.units), len(manifest.units), v.published),
            )
        slug = db._free_slug(c.topic)
        course_id = db.conn.execute(
            "INSERT INTO courses (topic, slug, profile_id, mechanism, lang, ranking, details, hours, started, mode, prerequisites, cover, cover_alt, source_version, setup) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'replay', ?, ?, ?, ?, ?)",
            (c.topic, slug, profile_id, c.mechanism, c.lang, json.dumps(c.ranking) if c.ranking else None, c.details, c.hours,
             int(c.prerequisites), cover, c.cover_alt if cover else None, version_hash,
             json.dumps([{"command": command, "status": "asked"} for command in manifest.setup])),
        ).lastrowid
        db.create_lesson(course_id, "Interview", "interview")
        unit_ids = {}
        for position, u in enumerate(manifest.units):
            unit_ids[u.key] = db.conn.execute(
                "INSERT INTO concepts (course_id, module, title, known, position, kind, key, unwritten) VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
                (course_id, u.module, u.title, position, u.kind, u.key, int(not u.written)),
            ).lastrowid
        db.conn.executemany(
            "INSERT OR IGNORE INTO concept_needs (concept_id, needs_id) VALUES (?, ?)",
            [(unit_ids[u.key], unit_ids[n]) for u in manifest.units for n in u.needs],
        )
        for k in manifest.capstones:
            capstone_id = db.conn.execute(
                "INSERT INTO capstones (course_id, module, title, brief, folder) VALUES (?, ?, ?, ?, ?)",
                (course_id, k.module, k.title, k.brief, k.folder),
            ).lastrowid
            db.conn.executemany(
                "INSERT INTO milestones (capstone_id, concept_id, deliverable) VALUES (?, ?, ?)",
                [(capstone_id, unit_ids[m.unit], m.deliverable) for m in k.milestones],
            )
        card_ids = {}
        for k in manifest.cards:
            card_ids[k.key] = db.conn.execute(
                "INSERT INTO cards (course_id, concept_id, question, kind, options, answer_key, explanation, scheduled, vocab, lemma, lang, translation, origin, key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported', ?)",
                (course_id, unit_ids.get(k.unit), k.question, k.kind, json.dumps(k.options), k.answer_key, k.explanation,
                 int(k.scheduled), int(k.vocab), k.lemma, k.lang, k.translation, k.key),
            ).lastrowid
        for lesson in manifest.lessons:
            lesson_id = db.conn.execute(
                "INSERT INTO lessons (course_id, title, phase, concept_id, session_id, key, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (course_id, lesson.title, lesson.phase, unit_ids.get(lesson.unit), str(uuid.uuid4()), lesson.key, lesson.summary),
            ).lastrowid
            for b in lesson.blocks:
                data = _clean_block(b, card_ids)
                block_id = db.conn.execute(
                    "INSERT INTO blocks (lesson_id, kind, markdown, data, key) VALUES (?, ?, ?, ?, ?)",
                    (lesson_id, b.kind, b.markdown, json.dumps(data), b.key),
                ).lastrowid
                db.conn.execute("UPDATE blocks SET position = ? WHERE id = ?", (block_id, block_id))
        source_files = []
        for s in manifest.sources:
            name = Path(s.name).name
            source_id = db.conn.execute(
                "INSERT INTO sources (course_id, name, size, status, sections) VALUES (?, ?, ?, 'ready', ?)",
                (course_id, name, len(assets[s.asset]), len(s.sections)),
            ).lastrowid
            db.conn.executemany(
                "INSERT INTO source_sections (source_id, title, text) VALUES (?, ?, ?)", [(source_id, x.title, x.text) for x in s.sections],
            )
            source_files.append((source_dir / str(course_id) / f"{source_id}-{name}", assets[s.asset]))
        db.conn.execute("COMMIT")
    except Exception:
        db.conn.execute("ROLLBACK")
        raise
    course = db.course(course_id)
    workspace = db.workspace(course["slug"])
    refused = [f.path for f in manifest.files if not course_files.write_text(workspace, f.path, assets[f.asset].decode(errors="replace"))]
    for path, content in source_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {**course, "refused_files": refused}
