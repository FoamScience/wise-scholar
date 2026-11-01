import io
import json
import uuid
import zipfile

import pytest

from wise_scholar import bundle, course_files, db

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


@pytest.fixture
def places(tmp_path, monkeypatch):
    """Files land in the test's folder, and the profiles and courses made here leave the shared test database."""
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]
    yield {"source_dir": tmp_path / "sources", "store": tmp_path / "versions"}
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    db.conn.execute("DELETE FROM facts WHERE profile_id > ?", (last,))
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _authored(places) -> dict:
    """A course worked through by its author: a map, a lesson with every kind of block, answers, chat and files."""
    author = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Author {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course("Blade lofting", author)
    course_id = course["id"]
    db.set_concepts(course_id, [{"title": "Sections", "concepts": ["Fitting", "Lofting"], "known": []}])
    fitting, lofting = db.concepts(course_id)
    db.conn.execute("INSERT INTO concept_needs (concept_id, needs_id) VALUES (?, ?)", (lofting["id"], fitting["id"]))
    db.add_fact(course_id, "The author works at a pump maker.", about_learner=True)
    begun = db.create_lesson(course_id, "Fitting", "lesson", fitting["id"])
    db.add_block(begun, "prose", "Half a lesson on fitting.")
    db.add_card(course_id, fitting["id"], "Half-taught?", "open", [], "a", "e", scheduled=True)
    lesson_id = db.create_lesson(course_id, "Lofting", "lesson", lofting["id"])
    card = db.add_card(course_id, lofting["id"], "Which call lofts wires?", "choice", ["ThruSections", "MakePipe"], "ThruSections", "It lofts.", scheduled=True)
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'MakePipe', 0.9, 0)", (card,))
    db.add_block(lesson_id, "prose", "Lofting joins **sections**.")
    db.add_block(lesson_id, "quiz", "Which call lofts wires?", {"card_id": card, "kind": "choice", "options": ["ThruSections", "MakePipe"],
                                                                 "answer": "MakePipe", "correct": False, "confidence": 0.9})
    db.add_block(lesson_id, "figure", "Two wires", {"svg": SVG, "alt": "two wires", "credits": [], "previous": {"svg": SVG}})
    workspace = db.workspace(course["slug"])
    course_files.write_text(workspace, "loft/new.py", "print('mine, solved')")
    db.add_block(lesson_id, "exercise", "Loft it", {"files": ["loft/new.py"], "run": "python loft/new.py", "attempts": ["done"], "solved": True,
                                                    "starter": {"loft/new.py": "# TODO loft"}})
    course_files.write_text(workspace, "loft/old.py", "print('old, as edited')")
    db.add_block(lesson_id, "exercise", "Older one", {"files": ["loft/old.py"], "run": "python loft/old.py", "attempts": [], "solved": False})
    db.add_block(lesson_id, "network", "Install", {"command": "uv pip install plotly", "status": "allowed"})
    db.add_block(lesson_id, "done", "", {})
    db.add_message(lesson_id, "learner", "I work at a pump maker, my name is Ada")
    lesson = db.lesson(lesson_id)
    ran = db.log_command(lesson, "network", "uv pip install plotly", "allowed")
    db.finish_command(ran, {"exit_code": 0, "output": "ok"}, 1.0)
    failed = db.log_command(lesson, "network", "uv pip install nothing", "allowed")
    db.finish_command(failed, {"exit_code": 1, "output": "no"}, 1.0)
    kept, private = (db.add_source(course_id, name, 5) for name in ("notes.md", "book.pdf"))
    for s in (kept, private):
        db.finish_source(s["id"], [("part 1", f"text of {s['name']}")])
        path = places["source_dir"] / str(course_id) / f"{s['id']}-{s['name']}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(s["name"].encode())
    return {"course": course_id, "lesson": lesson_id, "units": (fitting, lofting), "card": card, "kept": kept["id"]}


def test_a_published_version_carries_the_content_and_none_of_the_author(places):
    a = _authored(places)
    preview = bundle.preview(a["course"])
    assert [s["name"] for s in preview["sources"]] == ["notes.md", "book.pdf"]
    assert [x["files"] for x in preview["from_workspace"]] == [["loft/old.py"]]
    assert preview["setup"] == ["uv pip install plotly"] and (preview["written"], preview["units"]) == (1, 2)

    published = bundle.publish(a["course"], notes="first", licence="CC-BY-SA-4.0", forkable=False, sources=[a["kept"]], **places)
    assert published["number"] == 1 and bundle.versions(a["course"])[0]["hash"] == published["hash"]
    data = (places["store"] / f"{published['hash']}.zip").read_bytes()
    version_hash, manifest, assets = bundle.unpack(data)
    assert version_hash == published["hash"]

    raw = json.dumps(manifest.model_dump(by_alias=True))
    assert "pump maker" not in raw and "Ada" not in raw and "MakePipe\", \"correct" not in raw
    assert [u.key for u in manifest.units] == [u["key"] for u in a["units"]] and manifest.units[1].needs == [a["units"][0]["key"]]
    assert [u.written for u in manifest.units] == [False, True] and "Half" not in raw
    [lesson] = manifest.lessons
    assert [b.kind for b in lesson.blocks] == ["prose", "quiz", "figure", "exercise", "exercise"]
    quiz = lesson.blocks[1].data
    assert quiz["answer"] is None and "correct" not in quiz and quiz["card"] == db.card(a["card"])["key"]
    assert "previous" not in lesson.blocks[2].data and lesson.blocks[3].data["attempts"] == [] and "starter" not in lesson.blocks[3].data
    files = {f.path: assets[f.asset].decode() for f in manifest.files}
    assert files == {"loft/new.py": "# TODO loft", "loft/old.py": "print('old, as edited')"}
    assert [s.name for s in manifest.sources] == ["notes.md"] and manifest.setup == ["uv pip install plotly"]
    assert manifest.version.licence == "CC-BY-SA-4.0" and manifest.version.forkable is False

    reader = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reader')").lastrowid
    course = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])
    assert course["mode"] == "replay" and course["source_version"] == version_hash and course["refused_files"] == []
    assert [(c["key"], c["unwritten"]) for c in db.concepts(course["id"])] == [(u["key"], k) for u, k in zip(a["units"], (1, 0))]
    assert bundle.versions(a["course"])[0]["written"] == 1
    assert db.needs(course["id"]) == {db.concepts(course["id"])[1]["id"]: [db.concepts(course["id"])[0]["id"]]}
    new_lesson = db.row("SELECT * FROM lessons WHERE course_id = ? AND phase = 'lesson'", course["id"])
    blocks = db.blocks(new_lesson["id"])
    new_card = db.card(blocks[1]["data"]["card_id"])
    assert new_card["course_id"] == course["id"] and new_card["key"] == db.card(a["card"])["key"]
    assert all(b["data"]["imported"] for b in blocks if b["data"]) and db.rows("SELECT * FROM messages WHERE lesson_id = ?", new_lesson["id"]) == []
    assert db.facts(course["id"]) == [] and db.rows("SELECT * FROM answers WHERE card_id = ?", new_card["id"]) == []
    workspace = db.WORKSPACE / course["slug"]
    assert course_files.read_text(workspace, "loft/new.py") == "# TODO loft"
    [source] = db.sources(course["id"])
    assert source["status"] == "ready" and (places["source_dir"] / str(course["id"]) / f"{source['id']}-notes.md").read_bytes() == b"notes.md"

    assert bundle.preview(course["id"])["forked_from"] == {"topic": "Blade lofting", "number": 1, "hash": version_hash, "forkable": False}


def test_the_same_content_packs_to_the_same_bytes_and_a_fork_credits_its_origin(places):
    a = _authored(places)
    manifest, assets = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert bundle.pack(manifest, assets) == bundle.pack(manifest, assets)
    first = bundle.publish(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], **places)
    version_hash, m, assets = bundle.unpack((places["store"] / f"{first['hash']}.zip").read_bytes())
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES ('Forker')").lastrowid
    fork = bundle.install(reader, version_hash, m, assets, places["source_dir"])
    again = bundle.publish(fork["id"], notes="mine", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    _, forked, _ = bundle.unpack((places["store"] / f"{again['hash']}.zip").read_bytes())
    assert [c.model_dump() for c in forked.version.credits] == [{"topic": "Blade lofting", "version": version_hash, "number": 1}]

    copied = db.copy_course(a["course"], "Blade lofting (2)")
    assert [c["key"] for c in db.concepts(copied["id"])] == [c["key"] for c in db.concepts(a["course"])]


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def test_a_bundle_from_anyone_is_checked_before_anything_is_written(places):
    a = _authored(places)
    manifest, assets = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[a["kept"]], source_dir=places["source_dir"])
    body = bundle.canonical(manifest)
    good = {"manifest.json": body, **{f"assets/{h}": d for h, d in assets.items()}}

    with pytest.raises(ValueError, match="not a zip"):
        bundle.unpack(b"plain text")
    with pytest.raises(ValueError, match="unexpected files"):
        bundle.unpack(_zip({**good, "../escape.txt": b"x"}))
    tampered = dict(good)
    tampered[next(n for n in good if n.startswith("assets/"))] = b"changed"
    with pytest.raises(ValueError, match="does not match"):
        bundle.unpack(_zip(tampered))
    with pytest.raises(ValueError, match="missing"):
        bundle.unpack(_zip({"manifest.json": body}))
    bad_kind = json.loads(body)
    bad_kind["lessons"][0]["blocks"][0]["kind"] = "network"
    with pytest.raises(ValueError, match="does not hold a course"):
        bundle.unpack(_zip({**good, "manifest.json": bundle.canonical(bad_kind)}))

    scripted = json.loads(body)
    scripted["lessons"][0]["blocks"][2]["data"]["svg"] = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    escaping = {**json.loads(body), "files": [{"path": "../../outside.py", "asset": json.loads(body)["files"][0]["asset"]}]}
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES ('Target')").lastrowid
    before = db.row("SELECT COUNT(*) AS n FROM courses")["n"]
    version_hash, m, got = bundle.unpack(_zip({**good, "manifest.json": bundle.canonical(scripted)}))
    with pytest.raises(ValueError):
        bundle.install(reader, version_hash, m, got, places["source_dir"])
    assert db.row("SELECT COUNT(*) AS n FROM courses")["n"] == before
    version_hash, m, got = bundle.unpack(_zip({**good, "manifest.json": bundle.canonical(escaping)}))
    assert bundle.install(reader, version_hash, m, got, places["source_dir"])["refused_files"] == ["../../outside.py"]


def test_the_endpoints_publish_download_and_import_a_version(places, monkeypatch):
    import asyncio

    from fastapi import HTTPException, UploadFile

    from wise_scholar import app

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    a = _authored(places)
    v = app.publish_version(a["course"], app.Publish(notes="v1", forkable=False, sources=[a["kept"]]))
    assert app.version_bundle(v["hash"]).filename == "blade-lofting-v1.zip"
    with pytest.raises(HTTPException, match="no such version"):
        app.version_bundle("../../etc/passwd")

    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Reader {uuid.uuid4().hex[:6]}",)).lastrowid
    data = (places["store"] / f"{v['hash']}.zip").read_bytes()
    made = asyncio.run(app.import_course(reader, UploadFile(io.BytesIO(data), filename="x.zip")))
    assert made["mode"] == "replay" and db.course(made["id"])["profile_id"] == reader
    assert app._course(made["id"])["setup"] == [{"command": "uv pip install plotly", "status": "asked"}]
    assert asyncio.run(app.decide_setup(made["id"], 0, app.Decision(allow=False)))["setup"][0]["status"] == "refused"
    with pytest.raises(HTTPException, match="already decided"):
        asyncio.run(app.decide_setup(made["id"], 0, app.Decision(allow=True)))
    empty = db.create_course("Nothing yet", reader)["id"]
    with pytest.raises(HTTPException, match="nothing to publish"):
        app.publish_version(empty, app.Publish())
    with pytest.raises(HTTPException, match="does not allow"):
        app.publish_version(made["id"], app.Publish())
    with pytest.raises(HTTPException, match="not a course bundle"):
        asyncio.run(app.import_course(reader, UploadFile(io.BytesIO(b"nope"), filename="x.zip")))


def test_a_replayed_unit_runs_as_written_and_calls_the_tutor_only_on_misses(places, monkeypatch):
    import asyncio

    from wise_scholar import app

    started = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: started.append((lesson["id"], line)))
    author = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Writer {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course("Lofting", author)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft", "Fillet"], "known": []}])
    loft, fillet = db.concepts(course)
    lesson = db.create_lesson(course, "Loft", "lesson", loft["id"])
    choice = db.add_card(course, loft["id"], "Which call lofts?", "choice", ["ThruSections", "MakePipe"], "ThruSections", "It lofts.", scheduled=True)
    open_card = db.add_card(course, loft["id"], "Why sections?", "open", [], "They bound the surface.", "Sections bound it.", scheduled=True)
    db.add_block(lesson, "prose", "Lofting joins sections.")
    db.add_block(lesson, "challenge", "Guess first: what joins two wires?", {"attempts": ["a guess"], "hints": [], "gave_up": False, "solved": False,
                                                                             "solution": None, "reveal_after": 3, "max_hints": 3, "pretest": True})
    db.add_block(lesson, "quiz", "Which call lofts?", {"card_id": choice, "kind": "choice", "options": ["ThruSections", "MakePipe"], "answer": None})
    db.add_block(lesson, "quiz", "Why sections?", {"card_id": open_card, "kind": "open", "options": [], "answer": None})
    db.add_block(lesson, "done", "You can loft two wires.", {})
    v = bundle.publish(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Learner {uuid.uuid4().hex[:6]}",)).lastrowid
    version_hash, manifest, assets = bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())
    mine = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])["id"]
    replayed = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", mine)["id"]
    view = app._lesson_view(replayed)
    assert view["replay"] is True and [b["kind"] for b in view["blocks"]] == ["prose", "challenge", "quiz", "quiz"]
    pretest, right, open_quiz = view["blocks"][1:]

    asyncio.run(app.attempt(pretest["id"], app.Answer(answer="two wires make a surface")))
    asyncio.run(app.answer_quiz(right["id"], app.QuizAnswer(answer="ThruSections", confidence=0.8)))
    asyncio.run(app.answer_quiz(open_quiz["id"], app.QuizAnswer(answer="no idea really", confidence=0.3)))
    assert started == [] and db.block(open_quiz["id"])["data"]["answer_key"] == "They bound the surface."
    assert not any(b["kind"] == "done" for b in db.blocks(replayed))

    asyncio.run(app.self_grade_quiz(open_quiz["id"], app.SelfGrade(correct=False)))
    [(where, line)] = started
    assert where == replayed and app.REPLAY_MISS in line and "marked it wrong" in line
    assert db.blocks(replayed)[-1]["kind"] == "done" and db.blocks(replayed)[-1]["markdown"] == "You can loft two wires."

    prompt = app._turn_prompt(db.lesson(replayed), "[learner] why?")
    assert "[replay]" in prompt and "Lofting joins sections." in prompt

    unwritten = next(c for c in db.concepts(mine) if c["unwritten"])
    live = asyncio.run(app.open_concept(unwritten["id"]))
    assert live["replay"] is False and "The lesson begins" in started[-1][1]

    with pytest.raises(app.HTTPException, match="cards left"):
        app.card_placement(mine)  # the one written unit is finished already
    fresh = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])["id"]
    placement = app.card_placement(fresh)
    [card] = placement["blocks"]
    assert card["data"]["kind"] == "choice" and card["data"].get("answer_key") is None
    asyncio.run(app.answer_quiz(card["id"], app.QuizAnswer(answer="ThruSections", confidence=0.9)))
    assert db.blocks(placement["id"])[-1]["kind"] == "done" and db.concepts(fresh)[0]["known"] == 1
    assert len(started) == 2
    with pytest.raises(app.HTTPException, match="cards left"):
        app.card_placement(fresh)
    with pytest.raises(app.HTTPException, match="only an imported course"):
        app.card_placement(course)
