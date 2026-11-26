import io
import json
import uuid
import zipfile

import pytest

from wise_scholar import bundle, challenge, course_files, db

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
    for table in ("facts", "vocab_knowledge", "vocab_tiers"):
        db.conn.execute(f"DELETE FROM {table} WHERE profile_id > ?", (last,))
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
    card = db.add_card(course_id, lofting["id"], "Which call lofts wires?", "choice", ["ThruSections", "MakePipe"], "ThruSections", "It lofts.", scheduled=True,
                       misconceptions={"MakePipe": "a pipe sweep joins sections"})
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'MakePipe', 0.9, 0)", (card,))
    db.add_block(lesson_id, "prose", "Lofting joins **sections**.")
    db.add_block(lesson_id, "quiz", "Which call lofts wires?", {"card_id": card, "kind": "choice", "options": ["ThruSections", "MakePipe"],
                                                                 "answer": "MakePipe", "correct": False, "confidence": 0.9})
    db.add_block(lesson_id, "figure", "Two wires", {"svg": SVG, "alt": "two wires", "credits": [], "previous": {"svg": SVG},
                                                 "teaches": {"claim": "A loft needs two wires.", "notice": "The two outlines.", "extra": "x"}})
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


def assert_preview_lists_what_would_ship(preview):
    assert [s["name"] for s in preview["sources"]] == ["notes.md", "book.pdf"]
    assert [x["files"] for x in preview["from_workspace"]] == [["loft/old.py"]]
    assert preview["setup"] == ["uv pip install plotly"]
    assert (preview["written"], preview["units"]) == (1, 2)


def assert_manifest_has_nothing_of_the_author(manifest, a):
    raw = json.dumps(manifest.model_dump(by_alias=True))
    assert "pump maker" not in raw
    assert "Ada" not in raw
    assert "MakePipe\", \"correct" not in raw
    assert "Half" not in raw
    assert [u.key for u in manifest.units] == [u["key"] for u in a["units"]]
    assert manifest.units[1].needs == [a["units"][0]["key"]]
    assert [u.written for u in manifest.units] == [False, True]


def assert_manifest_lesson_is_stripped(manifest, a):
    [lesson] = manifest.lessons
    assert [b.kind for b in lesson.blocks] == ["prose", "quiz", "figure", "exercise", "exercise"]
    quiz = lesson.blocks[1].data
    assert quiz["answer"] is None
    assert "correct" not in quiz
    assert quiz["card"] == db.card(a["card"])["key"]
    assert "previous" not in lesson.blocks[2].data
    assert lesson.blocks[3].data["attempts"] == []
    assert "starter" not in lesson.blocks[3].data


def assert_manifest_files_and_terms(manifest, assets):
    files = {f.path: assets[f.asset].decode() for f in manifest.files}
    assert files == {"loft/new.py": "# TODO loft", "loft/old.py": "print('old, as edited')"}
    assert [s.name for s in manifest.sources] == ["notes.md"]
    assert manifest.setup == ["uv pip install plotly"]
    assert manifest.version.licence == "CC-BY-SA-4.0"
    assert manifest.version.forkable is False


def assert_installed_units(course, a, version_hash):
    assert course["mode"] == "replay"
    assert course["source_version"] == version_hash
    assert course["refused_files"] == []
    assert [(c["key"], c["unwritten"]) for c in db.concepts(course["id"])] == [(u["key"], k) for u, k in zip(a["units"], (1, 0))]
    assert bundle.versions(a["course"])[0]["written"] == 1
    assert db.needs(course["id"]) == {db.concepts(course["id"])[1]["id"]: [db.concepts(course["id"])[0]["id"]]}


def assert_installed_lesson_is_clean(course, a):
    new_lesson = db.row("SELECT * FROM lessons WHERE course_id = ? AND phase = 'lesson'", course["id"])
    blocks = db.blocks(new_lesson["id"])
    new_card = db.card(blocks[1]["data"]["card_id"])
    assert new_card["course_id"] == course["id"]
    assert new_card["key"] == db.card(a["card"])["key"]
    assert new_card["misconceptions"] == {"MakePipe": "a pipe sweep joins sections"}
    assert blocks[2]["data"]["teaches"] == {"claim": "A loft needs two wires.", "notice": "The two outlines.", "misconception": "", "limits": ""}
    assert all(b["data"]["imported"] for b in blocks if b["data"])
    assert db.rows("SELECT * FROM messages WHERE lesson_id = ?", new_lesson["id"]) == []
    assert db.facts(course["id"]) == []
    assert db.rows("SELECT * FROM answers WHERE card_id = ?", new_card["id"]) == []


def assert_installed_files_and_sources(course, places):
    workspace = db.WORKSPACE / course["slug"]
    assert course_files.read_text(workspace, "loft/new.py") == "# TODO loft"
    [source] = db.sources(course["id"])
    assert source["status"] == "ready"
    assert (places["source_dir"] / str(course["id"]) / f"{source['id']}-notes.md").read_bytes() == b"notes.md"


def test_a_unit_prepared_for_offline_study_ships_as_written(places):
    a = _authored(places)
    fitting, _ = a["units"]
    assert bundle.preview(a["course"])["written"] == 1
    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE concept_id = ?", (fitting["id"],))
    assert bundle.preview(a["course"])["written"] == 2


def test_a_published_version_carries_the_content_and_none_of_the_author(places):
    a = _authored(places)
    preview = bundle.preview(a["course"])
    assert_preview_lists_what_would_ship(preview)

    published = bundle.publish(a["course"], notes="first", licence="CC-BY-SA-4.0", forkable=False, sources=[a["kept"]], **places)
    assert published["number"] == 1
    assert bundle.versions(a["course"])[0]["hash"] == published["hash"]
    data = (places["store"] / f"{published['hash']}.zip").read_bytes()
    version_hash, manifest, assets = bundle.unpack(data)
    assert version_hash == published["hash"]

    assert_manifest_has_nothing_of_the_author(manifest, a)
    assert_manifest_lesson_is_stripped(manifest, a)
    assert_manifest_files_and_terms(manifest, assets)

    reader = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reader')").lastrowid
    course = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])
    assert_installed_units(course, a, version_hash)
    assert_installed_lesson_is_clean(course, a)
    assert_installed_files_and_sources(course, places)

    assert bundle.preview(course["id"])["forked_from"] == {"topic": "Blade lofting", "number": 1, "hash": version_hash, "forkable": False}


def test_a_version_leaves_out_the_cards_made_from_the_learners_corrected_text(places):
    import asyncio

    from wise_scholar import challenge
    from wise_scholar.tools import language as language_tools, practice as practice_tools

    a = _authored(places)
    roleplay = db.create_lesson(a["course"], "Role-play 1", "roleplay")
    db.add_message(roleplay, "learner", "Ich möchte ein Kaffee.")
    mistake = language_tools.Mistake(said="Ich möchte ein Kaffee.", correct="Ich möchte einen Kaffee.", explanation="Accusative.")
    assert asyncio.run(language_tools.end_roleplay(roleplay, [mistake], "Good.")).startswith("ended with 1")
    data = {**challenge.new(reveal_after=2, max_hints=3), "writing": True, "attempts": ["Ich habe gegeht."], "marks": []}
    for lesson in (db.create_lesson(a["course"], "Writing session 1", "writing"), a["lesson"]):
        block = db.add_block(lesson, "challenge", "Write about yesterday.", data)
        practice_tools._note_writing_error(block["id"], data, "Ich bin gegangen.")
    profile = db.course(a["course"])["profile_id"]
    errors = db.errors(profile, a["course"])
    keys = {db.card(e["card_id"])["key"] for e in errors}
    assert len(keys) == 3

    # A placement from the course's own cards may hold a quiz on such a card.
    placed = db.create_lesson(a["course"], "Placement", "placement")
    quoting = next(db.card(e["card_id"]) for e in errors if db.card(e["card_id"])["concept_id"])
    db.add_block(placed, "quiz", quoting["question"], {"card_id": quoting["id"], "kind": "open", "options": [], "answer": None})
    db.add_block(placed, "quiz", "Which call lofts wires?", {"card_id": a["card"], "kind": "choice", "options": ["ThruSections", "MakePipe"], "answer": None})

    def assert_left_out(course):
        manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
        raw = json.dumps(manifest, ensure_ascii=False)
        assert "Kaffee" not in raw and "gegeht" not in raw and "gegangen" not in raw
        assert not keys & {c["key"] for c in manifest["cards"]}
        assert [c["key"] for c in manifest["cards"]] == [db.card(a["card"])["key"]]

    assert_left_out(a["course"])
    for e in errors:
        db.update_error(e["id"], None, None, True)
    assert_left_out(a["course"])

    copy = db.copy_course(a["course"], "Blade lofting again")["id"]
    assert_left_out(copy)
    [copied] = db.rows("SELECT id FROM lessons WHERE course_id = ? AND phase = 'placement'", copy)
    [quiz] = db.blocks(copied["id"])
    assert db.card(quiz["data"]["card_id"])["course_id"] == copy


def _worked_blocks(a):
    """Every kind of answered card, with what the learner and the tutor's reply to them left on it."""
    import asyncio

    from wise_scholar import quiz
    from wise_scholar.tools import practice as practice_tools, quizzes as quiz_tools

    lesson = a["lesson"]
    work = {"attempts": ["LEARNER typed"], "marks": ["LEARNER mark"], "photos": [{"name": "LEARNER.jpg", "attempt": 0}],
            "transcripts": {"0": {"text": "LEARNER paper", "by": "tutor"}}}
    ladder = challenge.new(reveal_after=2, max_hints=3)
    key_points = db.add_card(a["course"], a["units"][1]["id"], "Explain lofting.", "open", [], "Key points.", "", scheduled=False)
    posed = [
        db.add_block(lesson, "challenge", "Write about lofting.", {**ladder, "writing": True, "structure": "passive", "words": [10, 50], **work}),
        db.add_block(lesson, "challenge", "Explain lofting.", {**ladder, "writing": True, "spoken": True, "teachback": True, "card_id": key_points, **work}),
        db.add_block(lesson, "exercise", "Loft a blade.", {**ladder, "files": [], "run": "true", "starter": {}, "helper": "Authored helper.", **work,
                                                          "last_run": {"exit_code": 1, "output": "LEARNER output"}}),
        db.add_block(lesson, "speaking", "Say lofting.", {**ladder, "speaking": "read", "lang": "en", **work,
                                                          "scores": [{"words": [], "heard": "LEARNER heard", "score": 0.5}]}),
    ]
    for b in posed:
        asyncio.run(practice_tools.give_hint(b["id"], "You wrote LEARNER typed."))
        db.set_block_data(b["id"], {**db.block(b["id"])["data"], "gave_up": True, "solution": "LEARNER corrected"})
    asked = asyncio.run(quiz_tools.pose_quiz(lesson, "Why loft?", "open", "To join.", "It joins."))
    asked = db.block(int(asked.split()[3].rstrip(";")))
    card = db.card(asked["data"]["card_id"])
    db.set_block_data(asked["id"], {**asked["data"], "answer": "LEARNER answer", "confidence": 0.9, "unheard": "LEARNER line",
                                    "answer_id": quiz.submit(card, "LEARNER answer", 0.9)})
    asyncio.run(quiz_tools.grade_quiz(asked["id"], False, "You said LEARNER answer.", "LEARNER belief"))
    sort = db.add_card(a["course"], a["units"][1]["id"], "Sort.", "sort", [{"text": "x", "category": "c"}], '["c"]', "", scheduled=False)
    db.add_block(lesson, "quiz", "Sort.", {"card_id": sort, "kind": "sort", "options": [{"text": "x"}], "categories": ["c"],
                                           "answer": "{}", "correct": False, "misplaced": ["x"], "due": "2031-01-01"})


def test_a_version_and_a_copy_leave_out_what_the_learner_left_on_the_cards(places):
    a = _authored(places)
    _worked_blocks(a)
    manifest, assets, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    raw = json.dumps(manifest, ensure_ascii=False)
    assert "LEARNER" not in raw
    blocks = {b["markdown"]: b["data"] for x in manifest["lessons"] for b in x["blocks"]}
    written, taught, exercise = (blocks[m] for m in ("Write about lofting.", "Explain lofting.", "Loft a blade."))
    for data in (written, taught, exercise):
        assert (data["attempts"], data["hints"], data["solution"], data["gave_up"], data["max_hints"]) == ([], [], None, False, 3)
        assert not {"photos", "transcripts", "marks"} & data.keys()
    assert (written["structure"], written["words"], exercise["helper"], exercise["run"]) == ("passive", [10, 50], "Authored helper.", "true")
    assert "Key points." in raw and "To join." in raw
    for markdown in ("Why loft?", "Sort."):
        assert blocks[markdown]["answer"] is None
        assert not {"misplaced", "misconception", "due", "unheard", "feedback"} & blocks[markdown].keys()

    version_hash, data = bundle.pack(manifest, assets)
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Bundle reader {uuid.uuid4().hex[:6]}",)).lastrowid
    _, m, assets = bundle.unpack(data)
    played = bundle.install(reader, version_hash, m, assets, places["source_dir"])
    installed = [b for x in db.rows("SELECT id FROM lessons WHERE course_id = ?", played["id"]) for b in db.blocks(x["id"])]
    assert all(challenge.is_open(b["data"]) for b in installed if b["markdown"] in ("Write about lofting.", "Explain lofting.", "Loft a blade."))

    copy = db.copy_course(a["course"], "Blade lofting worked")["id"]
    copied = [b["data"] for x in db.rows("SELECT id FROM lessons WHERE course_id = ?", copy) for b in db.blocks(x["id"])]
    assert "LEARNER" not in json.dumps(copied)


def _measured_blocks(a, monkeypatch) -> dict[str, dict]:
    """A vocabulary check, a reading, a widget and a goal question, each worked on as the learner does; what they held untouched."""
    import asyncio

    from wise_scholar import app, widgets
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import language as language_tools, lesson_flow

    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    lesson = a["lesson"]
    spec = {"controls": [{"name": "n", "label": "n", "min": 1, "max": 3, "step": 1, "value": 1}], "readouts": [{"label": "n", "expr": "n"}]}
    asyncio.run(language_tools.pose_vocab_check(lesson, "de"))
    asyncio.run(lesson_flow.ask(lesson, "What should it enable?", ["Lofting", "Welding"], non_goals=True))
    db.add_block(lesson, "reading", "Das Brot.", {"title": "T", "lang": "de-DE", "added": [], "targets": [], "known": [],
                                                   "glossary": [{"word": "Brot", "meaning": "bread"}]})
    db.add_block(lesson, "widget", "Turn it.", {"spec": spec, "widget": widgets.resolve(spec), "alt": "n"})
    vocab, question, reading, widget = posed = [b for b in db.blocks(lesson) if b["kind"] in ("vocab", "question", "reading", "widget")]

    while (data := db.block(vocab["id"])["data"])["current"]:
        known = data["current"]["words"] if len(data["rounds"]) < 2 else []
        asyncio.run(blocks_routes.vocab_check(vocab["id"], blocks_routes.Known(known=known)))
    asyncio.run(blocks_routes.know_word(reading["id"], blocks_routes.Word(word="Brot")))
    asyncio.run(blocks_routes.try_widget(widget["id"], blocks_routes.WidgetSetting(at=[2])))
    app._widget_tries(lesson)
    asyncio.run(blocks_routes.answer_question(question["id"], blocks_routes.Answer(answer="Lofting", non_goals=["Welding"])))
    worked = {b["kind"]: db.block(b["id"])["data"] for b in posed}
    assert len(worked["vocab"]["rounds"]) > 2 and worked["vocab"]["tier"] and worked["vocab"]["current"] is None
    assert (worked["reading"]["known"], worked["question"]["non_goals"]) == (["Brot"], ["Welding"])
    assert (worked["widget"]["tried"], worked["widget"]["told"]) == ([[2]], 1)
    return {b["kind"]: b["data"] for b in posed}


def test_a_version_and_a_copy_hold_word_checks_readings_widgets_and_goals_as_they_were_posed(places, monkeypatch):
    a = _authored(places)
    posed = _measured_blocks(a, monkeypatch)
    manifest, _, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    shipped = {b["kind"]: b["data"] for x in manifest["lessons"] for b in x["blocks"]}
    assert {k: shipped[k] for k in ("vocab", "reading", "widget")} == {k: posed[k] for k in ("vocab", "reading", "widget")}

    copy = db.copy_course(a["course"], "Blade lofting measured")["id"]
    copied = {b["kind"]: b["data"] for x in db.rows("SELECT id FROM lessons WHERE course_id = ?", copy) for b in db.blocks(x["id"])}
    assert {k: copied[k] for k in posed} == posed


def _unfiltered(block, card_keys, authored=False):
    """A block's data as a version carries it when nothing is left out."""
    if not block["data"]:
        return None
    data = json.loads(block["data"])
    card = data.pop("card_id", None)
    return data if card is None else {**data, "card": card_keys[card]}


def _installed(course: int) -> dict[str, dict]:
    return {b["markdown"]: b for x in db.rows("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course) for b in db.blocks(x["id"])}


def test_a_bundle_published_with_the_record_installs_and_upgrades_without_it(places, monkeypatch):
    a = _authored(places)
    posed = _measured_blocks(a, monkeypatch)
    _worked_blocks(a)
    monkeypatch.setattr(bundle, "_block_data", _unfiltered)

    def published():
        v = bundle.publish(a["course"], notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
        return bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())

    version_hash, old, assets = published()
    sent = json.dumps(old.model_dump(by_alias=True))
    assert all(f'"{f}"' in sent for f in ("rounds", "tried", "photos", "transcripts", "correct", "starter", "previous")) and "LEARNER typed" in sent
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Old bundle reader {uuid.uuid4().hex[:6]}",)).lastrowid
    mine = bundle.install(reader, version_hash, old, assets, places["source_dir"])["id"]
    got = _installed(mine)
    assert "LEARNER" not in json.dumps([b["data"] for b in got.values()])
    for markdown, kind in (("Which of these words do you know?", "vocab"), ("Das Brot.", "reading"), ("Turn it.", "widget")):
        assert got[markdown]["data"] == {**posed[kind], "imported": True}
    tasks = [b for b in got.values() if b["kind"] in challenge.KINDS]
    assert len(tasks) == 5 and all(challenge.is_open(b["data"]) and b["data"]["attempts"] == [] for b in tasks)
    assert db.locked(got["Write about lofting."]["id"])["hints"] == ["You wrote LEARNER typed."]
    quizzes = [b["data"] for b in got.values() if b["kind"] == "quiz"]
    assert len(quizzes) == 3 and all(d["answer"] is None and "correct" not in d and db.card(d["card_id"])["course_id"] == mine for d in quizzes)

    # the reader's own work stays on a kept unit; the unit the author finished comes without the author's
    write = got["Write about lofting."]
    db.set_block_data(write["id"], {**write["data"], "attempts": ["the reader's own"]})
    begun = db.row("SELECT id FROM lessons WHERE course_id = ? AND title = 'Fitting'", a["course"])["id"]
    db.add_block(begun, "challenge", "Fit it.", {**challenge.new(), "attempts": ["LEARNER later"], "solved": True})
    db.add_block(begun, "done", "", {})
    version_hash, new, assets = published()
    done = bundle.upgrade(mine, version_hash, new, assets, old, places["source_dir"])
    assert (done["kept"], done["restarted"]) == ([a["units"][1]["key"]], [a["units"][0]["key"]])
    got = _installed(mine)
    assert got["Write about lofting."]["data"]["attempts"] == ["the reader's own"]
    assert (got["Fit it."]["data"]["attempts"], got["Fit it."]["data"]["solved"]) == ([], False)


def test_a_hostile_block_sets_no_record_of_the_reader():
    def clean(kind, data):
        return bundle._clean_block(bundle.Block(kind=kind, markdown="x", data=data, key="a" * 32), {"k": 7})

    task = {"solved": True, "gave_up": True, "hints": ["h"], "solution": "s", "card_id": 1, "marks": ["m"], "unlisted": 1}
    opened = {"attempts": [], "gave_up": False, "solved": False, "hints": ["h"], "solution": "s", "imported": True}
    assert clean("challenge", task) == clean("challenge", {**task, "attempts": ["x"]}) == opened
    quiz = {"card": "k", "kind": "open", "options": [], "answer": "x", "correct": True, "answer_id": 3, "card_id": 1}
    assert clean("quiz", quiz) == {"kind": "open", "options": [], "answer": None, "card_id": 7, "imported": True}
    for rounds in (["x"], "x", {"a": 1}, [{"tier": 1}]):
        with pytest.raises(ValueError, match="vocabulary check"):
            clean("vocab", {"lang": "de", "rounds": rounds, "current": None, "tier": 2})


PARTS = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g data-part="one"><rect width="4" height="4"/></g>'
         '<g data-part="two"><rect x="5" width="4" height="4"/></g></svg>')


async def _pose_figures(lesson: int, teaches) -> list[str]:
    """A figure by every tool that draws one, then redrawn, narrated and drawn on."""
    from wise_scholar.board import BoardStep
    from wise_scholar.tools import visuals

    first, second = [await visuals.add_figure(lesson, PARTS, "Caption.", "alt", teaches) for _ in range(2)]
    drawn, redrawn = (int(r.split()[-1]) for r in (first, second))
    return [
        first, second,
        await visuals.narrate_figure(lesson, drawn, [BoardStep(say="One.", draw=["one"]), BoardStep(say="Two.", draw=["two"])]),
        await visuals.annotate_figure(lesson, drawn, '<g data-part="three"><rect y="5" width="4" height="4"/></g>', [BoardStep(say="Three.", draw=["three"])]),
        await visuals.replace_figure(lesson, redrawn, SVG, "Again.", "alt"),
        await visuals.add_diagram(lesson, "sets", "Set A", "Caption.", "alt", teaches),
        await visuals.add_animation(lesson, "sets", ["Set A", "Set B"], "Caption.", "alt", teaches),
    ]


async def _pose_every_kind(lesson: int) -> list[str]:
    """Each kind of block a version carries, posed with its tools in a prepared course; the tools' replies."""
    from wise_scholar.figures import Teaches
    from wise_scholar.tools import language, lesson_flow, practice, quizzes, visuals

    teaches = Teaches(claim="Lofts join.", notice="The join.")
    slider = {"controls": [{"name": "n", "label": "n", "min": 1, "max": 3, "step": 1, "value": 1}], "readouts": [{"label": "n", "expr": "n"}]}
    line = {"x": {"label": "x"}, "y": {"label": "y"}, "marks": [{"type": "line", "fn": "x", "domain": [0, 1]}]}
    sort = [quizzes.SortItem(text=f"item {n}", category="ab"[n % 2]) for n in range(6)]
    replies = [await practice.pose_challenge(lesson, "Try.", form="case", helper="Help.")]
    [solved] = db.blocks(lesson)
    db.set_block_data(solved["id"], {**solved["data"], "solved": True})
    return replies + [
        await practice.pose_comparison(lesson, "Compare.", "left", "right", "When?"),
        await lesson_flow.add_block(lesson, "prose", "Text."),
        await lesson_flow.add_block(lesson, "example", "Worked."),
        await lesson_flow.set_outline(lesson, ["One", "Two", "Three"], cards=40),
        await quizzes.pose_quiz(lesson, "Which?", "choice", "a", "Because.", ["a", "b"], form="pick one", translation="Welche?", misconceptions={"b": "belief"}),
        await quizzes.pose_sort(lesson, "Sort them.", ["a", "b"], sort, "Why."),
        await practice.pose_exercise(lesson, "Run.", [practice.ExerciseFile(path="p/a.py", content="x")], "true",
                                     completions=[course_files.Completion(label="sqrt", signature="sqrt(x)", doc="root")]),
        await practice.pose_teachback(lesson, "Explain.", "Points."),
        await language.pose_writing(lesson, "Write.", min_words=1, max_words=9, structure="weil"),
        await language.pose_speaking(lesson, "answer", "Say it.", "de-DE"),
        *await _pose_figures(lesson, teaches),
        await visuals.add_plot(lesson, "Plot.", line, "alt", teaches),
        await visuals.add_widget(lesson, "Widget.", slider, "alt", teaches),
        await visuals.add_board(lesson, "script", teaches),
        await language.add_reading(lesson, "Title", "Das ist ein Haus.", "de-DE", [], names=["Haus"]),
        await language.pose_vocab_check(lesson, "de"),
    ]


async def _pose_in_other_lessons(course: int, source: int) -> tuple[list[str], list[int]]:
    """What only a practice unit, a story or a gist turn poses; the replies and the lessons."""
    from wise_scholar import tutor
    from wise_scholar.figures import Teaches
    from wise_scholar.tools import language, practice, visuals

    unit = db.conn.execute("INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Blades', 'Practice', 0, 99, 'practice')", (course,)).lastrowid
    varied, story = db.create_lesson(course, "Practice", "practice", unit), db.create_lesson(course, "Story", "story")
    replies = [
        await practice.pose_challenge(varied, "Vary.", variant_of=source),
        await language.start_series(course, "Series", ["Ada: a smith"], "A forge."),
        await language.add_episode(story, "One", "Haus " * 400, "de-DE", "It began.", names=["Haus"]),
    ]
    tutor._calling.set({"kind": "gist"})
    replies.append(await visuals.add_board(story, "script", Teaches(claim="Lofts join.", notice="The join.")))
    board = int(replies[-1].split()[3].rstrip(";"))
    return [*replies, await visuals.extend_board(board, "> more")], [varied, story]


def _unclassified(lessons: list[int]) -> set[tuple[str, str]]:
    # an exercise's starter files ship as the version's files, a quiz's card by its key, a figure as its drawing, without its answers
    kept_back = {*db._RECORD, "card_id", "starter", "previous", "unanswered"}
    return {(b["kind"], f) for x in lessons for b in db.blocks(x) for f in b["data"] or {} if f not in {*bundle.SHIPPED[b["kind"]], *kept_back}}


def test_every_field_the_posing_tools_give_a_block_is_named_as_shipped_or_kept_back(places, monkeypatch):
    import asyncio

    from wise_scholar import diagrams, figcheck, speech, wiseboard
    from wise_scholar.tools import practice

    async def answer(value):
        return value

    monkeypatch.setattr(figcheck, "problems", lambda *_, **__: answer([]))
    monkeypatch.setattr(speech, "available", lambda: True)
    monkeypatch.setattr(wiseboard, "available", lambda: True)
    monkeypatch.setattr(wiseboard, "render", lambda script, prior=None: answer(({"v": 1}, "ok")))
    monkeypatch.setattr(diagrams, "render", lambda domain, substance: SVG)
    monkeypatch.setattr(diagrams, "animate", lambda domain, stages: (SVG, [SVG, SVG]))
    course = _prepared_course("Every field")
    lesson = db.create_lesson(course, "Every", "lesson", db.concepts(course)[0]["id"])
    replies = asyncio.run(_pose_every_kind(lesson))
    others, lessons = asyncio.run(_pose_in_other_lessons(course, db.blocks(lesson)[0]["id"]))
    assert not [r for r in [*replies, *others] if r.startswith(("error", "refused", "rewrite"))]
    assert {b["kind"] for b in db.blocks(lesson)} == set(bundle.BLOCK_KINDS)
    assert _unclassified([lesson, *lessons]) == set()
    given = {f for x in (lesson, *lessons) for b in db.blocks(x) for f in b["data"] or {}}
    assert {"variant_of", "comparison", "frames", "diagram", "previous", "board", "story", "gist"} <= given

    # a field a tool starts to write fails the check until it is named, and stays out of a version meanwhile
    new = challenge.new
    monkeypatch.setattr(challenge, "new", lambda *args, **kwargs: {**new(*args, **kwargs), "mood": "keen"})
    asyncio.run(practice.pose_challenge(lesson, "Another."))
    assert _unclassified([lesson]) == {("challenge", "mood")}
    manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert "Another." in json.dumps(manifest) and "keen" not in json.dumps(manifest)


def test_a_prepared_course_ships_the_hints_and_solution_its_teacher_wrote(places):
    a = _authored(places)
    data = {**challenge.new(), "hints": ["Think of wires."], "solution": "Two wires.", "attempts": ["LEARNER trial"]}
    db.add_block(a["lesson"], "challenge", "What does a loft need?", data)

    def shipped(course):
        manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
        [task] = [b["data"] for x in manifest["lessons"] for b in x["blocks"] if b["markdown"] == "What does a loft need?"]
        return task["hints"], task["solution"], task["attempts"]

    assert shipped(a["course"]) == ([], None, [])
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (a["course"],))
    assert shipped(a["course"]) == (["Think of wires."], "Two wires.", [])
    assert shipped(db.copy_course(a["course"], "Blade lofting prepared")["id"]) == (["Think of wires."], "Two wires.", [])


def _prepared_course(title: str) -> int:
    """A prepared course whose tasks carry hints and a solution, one of each kind, and the opening."""
    author = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Locksmith {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course(title, author)["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(course, "Loft", "lesson", db.concepts(course)[0]["id"])
    written = lambda what: {"hints": [f"SECRET first on {what}", f"SECRET second on {what}"], "solution": f"SECRET answer on {what}"}  # noqa: E731
    db.add_block(lesson, "challenge", "Guess.", {**challenge.new(max_hints=0), **written("guess"), "pretest": True})
    db.add_block(lesson, "challenge", "Reason.", {**challenge.new(max_hints=0), **written("reason")})
    db.add_block(lesson, "exercise", "Loft it.", {**challenge.new(max_hints=0), **written("loft"), "files": [], "run": "true", "last_run": None, "starter": {}})
    db.add_block(lesson, "challenge", "Write.", {**challenge.new(reveal_after=2, max_hints=3), **written("write"), "writing": True, "marks": []})
    db.add_block(lesson, "done", "You can loft.", {})
    return course


def _played(course: int, places) -> tuple[int, int]:
    """The course published and installed for a new reader: the replay and its lesson."""
    v = bundle.publish(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Lockpick {uuid.uuid4().hex[:6]}",)).lastrowid
    version_hash, manifest, assets = bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())
    mine = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])["id"]
    return mine, db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", mine)["id"]


def _all_the_learner_can_reach(course: int, lesson: int) -> str:
    """The lesson as the browser gets it, the tutor's prompt and record of it, the vault and the next version."""
    from wise_scholar import app, history, obsidian, search

    view = app._lesson_view(lesson)
    vault = obsidian.Vault(course).lesson_text({**db.lesson(lesson), "blocks": view["blocks"], "messages": []}, chat=True)
    manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=None)
    return json.dumps([
        view, [db.block(b["id"]) for b in view["blocks"]], app._turn_prompt(db.lesson(lesson), "[learner] help"), app._lesson_record(lesson),
        history.digest([view]), [list(x) for x in search._wanted(db.course(course)).values()], manifest, vault,
    ], default=str, ensure_ascii=False)


def test_a_replayed_task_keeps_its_authors_solution_locked_until_the_reader_reaches_it(places, monkeypatch):
    import asyncio

    from wise_scholar import app, hub
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import practice as practice_tools

    run, sent, lines = asyncio.run, [], []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: lines.append(line))
    monkeypatch.setattr(hub, "publish", lambda course_id, event: sent.append(json.dumps(event, default=str)))
    mine, replayed = _played(_prepared_course("Locked lofting"), places)
    guess, reason, loft, write = app._lesson_view(replayed)["blocks"]
    assert "SECRET" not in _all_the_learner_can_reach(mine, replayed)

    # the opening is one try; any other task asks for the author's hints one at a time
    with pytest.raises(app.HTTPException, match="no hint ladder"):
        run(blocks_routes.request_hint(guess["id"]))
    run(blocks_routes.attempt(reason["id"], blocks_routes.Answer(answer="two wires")))
    assert "refused" in run(practice_tools.reveal(reason["id"], "the tutor's own"))
    run(blocks_routes.request_hint(reason["id"]))
    assert "SECRET first on reason" in run(practice_tools.give_hint(reason["id"], "the tutor's own"))
    reached = _all_the_learner_can_reach(mine, replayed) + "".join(sent + lines)
    assert "SECRET first on reason" in reached
    assert "SECRET second" not in reached and "SECRET answer" not in reached
    assert db.block(reason["id"])["data"]["hints"] == ["SECRET first on reason"]
    run(blocks_routes.give_up(reason["id"]))
    assert "SECRET answer on reason" in run(practice_tools.reveal(reason["id"], "the tutor's own"))

    run(blocks_routes.give_up(guess["id"]))
    run(practice_tools.reveal(guess["id"], "the tutor's own"))
    run(blocks_routes.check_exercise(loft["id"], blocks_routes.ExerciseCheck(answer="done")))
    run(practice_tools.mark_solved(loft["id"]))
    run(blocks_routes.attempt(write["id"], blocks_routes.Answer(answer="a text")))
    # a correction of the learner's own text stays the tutor's
    run(practice_tools.give_hint(write["id"], "look at this word", ["text"]))
    assert db.block(write["id"])["data"]["hints"] == ["look at this word"]
    run(blocks_routes.give_up(write["id"]))
    assert not any(b["kind"] == "done" for b in db.blocks(replayed))
    run(practice_tools.reveal(write["id"], "A text."))
    app._turn_over(db.lesson(replayed), "", {"ok": True}, 0.0, quiet=True)

    assert db.blocks(replayed)[-1]["markdown"] == "You can loft."
    shown = {b["markdown"]: b["data"]["solution"] for b in db.blocks(replayed) if b["kind"] in challenge.KINDS}
    assert shown == {"Guess.": "SECRET answer on guess", "Reason.": "SECRET answer on reason", "Loft it.": None, "Write.": "SECRET answer on write"}
    assert db.row("SELECT correct FROM errors WHERE course_id = ? AND kind = 'writing'", mine)["correct"] == "A text."
    assert not any(x in "".join(sent + lines) for x in ("SECRET second", "answer on loft"))
    # a fork ships neither what was shown nor what is still locked
    manifest, _, _ = bundle.build(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert "SECRET" not in json.dumps(manifest)
    assert {b["markdown"]: b["data"]["max_hints"] for x in manifest["lessons"] for b in x["blocks"]} == {"Guess.": 0, "Reason.": 0, "Loft it.": 0, "Write.": 3}
    plain = db.block(loft["id"])
    assert (plain["data"]["max_hints"], bundle._block_data({**plain, "data": json.dumps(plain["data"])}, {})["max_hints"]) == (2, 0)


def test_a_solution_shown_after_enough_attempts_finishes_the_unit(places, monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import practice as practice_tools

    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    _, replayed = _played(_prepared_course("Locked attempts"), places)
    for b in db.blocks(replayed):
        for n in range(1 if b["data"].get("pretest") else b["data"]["reveal_after"]):
            if b["kind"] == "exercise":
                asyncio.run(blocks_routes.check_exercise(b["id"], blocks_routes.ExerciseCheck(answer=f"try {n}")))
            else:
                asyncio.run(blocks_routes.attempt(b["id"], blocks_routes.Answer(answer=f"try {n}")))
        assert not any(x["kind"] == "done" for x in db.blocks(replayed))
        assert "SECRET answer" in asyncio.run(practice_tools.reveal(b["id"], ""))
        app._turn_over(db.lesson(replayed), "", {"ok": True}, 0.0, quiet=True)
    assert not any(b["data"]["gave_up"] or b["data"]["solved"] for b in db.blocks(replayed) if b["kind"] in challenge.KINDS)
    assert db.blocks(replayed)[-1]["markdown"] == "You can loft."


def test_an_author_hint_moves_out_of_the_lock_in_one_write(places):
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    _, replayed = _played(_prepared_course("Locked write"), places)
    reason = db.blocks(replayed)[1]["id"]
    writes = []
    connection = db.conn._local.connection
    connection.set_trace_callback(lambda sql: writes.append(sql) if sql.startswith("UPDATE blocks") else None)
    try:
        asyncio.run(practice_tools.give_hint(reason, "the tutor's own"))
    finally:
        connection.set_trace_callback(None)
    assert len(writes) == 1
    assert db.block(reason)["data"]["hints"] == ["SECRET first on reason"]
    assert db.locked(reason)["hints"] == ["SECRET second on reason"]


def test_a_tried_opening_lets_the_tutor_show_its_authors_solution(places, monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import practice as practice_tools

    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    _, replayed = _played(_prepared_course("Locked opening"), places)
    guess = db.blocks(replayed)[0]["id"]
    assert "refused" in asyncio.run(practice_tools.reveal(guess, ""))
    asyncio.run(blocks_routes.attempt(guess, blocks_routes.Answer(answer="wires")))
    assert "SECRET answer on guess" in asyncio.run(practice_tools.reveal(guess, ""))


def test_an_upgrade_keeps_and_brings_locked_solutions(places):
    course = _prepared_course("Locked upgrade")
    mine, replayed = _played(course, places)
    old = bundle.stored(places["store"], db.course(mine)["source_version"])
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]

    def upgraded():
        v = bundle.publish(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
        version_hash, new, assets = bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())
        plan = bundle.upgrade(mine, version_hash, new, assets, old, places["source_dir"])
        blocks = db.blocks(db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", mine)["id"])
        assert all(challenge.is_open(b["data"]) and b["data"]["hints"] == [] for b in blocks)
        return len(plan["kept"]), {b["markdown"]: db.locked(b["id"])["solution"] for b in blocks}

    kept, solutions = upgraded()
    assert (kept, solutions["Reason."]) == (1, "SECRET answer on reason")
    reason = next(b for b in db.blocks(lesson) if b["markdown"] == "Reason.")
    db.set_block_data(reason["id"], {**reason["data"], "solution": "SECRET better answer"})
    kept, solutions = upgraded()
    assert (kept, solutions["Reason."]) == (0, "SECRET better answer")


def test_replays_installed_before_the_lock_hold_their_untouched_solutions_behind_it(tmp_path):
    import sqlite3

    raw = sqlite3.connect(tmp_path / "old.db")
    raw.row_factory = sqlite3.Row
    for script in db.MIGRATIONS[: db.MIGRATIONS.index(db._lock_imported)]:
        script(raw) if callable(script) else raw.executescript(script)
    raw.execute("PRAGMA foreign_keys = OFF")
    for course, mode in ((1, "replay"), (2, "teacher")):
        raw.execute("INSERT INTO courses (id, topic, slug, profile_id, mode) VALUES (?, 't', ?, 1, ?)", (course, f"s{course}", mode))
        raw.execute("INSERT INTO lessons (id, course_id, title, session_id, phase) VALUES (?, ?, 't', ?, 'lesson')", (course, course, f"s{course}"))
    task = {**challenge.new(max_hints=0), "hints": ["one", "two"], "solution": "answer", "imported": True}
    bare = {k: v for k, v in task.items() if k not in ("max_hints", "reveal_after")}
    stored = {
        "closed": (1, task), "opening": (1, {**task, "pretest": True}), "transfer": (1, {**task, "transfer": True}),
        "hints only": (1, {**task, "solution": None}), "no list": (1, {**task, "hints": "text"}),
        "odd list": (1, {**task, "hints": ["one", "", " \n", 7, None, {"a": 1}, "two"]}), "blank": (1, {**task, "hints": [" "], "solution": " "}),
        "bare": (1, bare), "bare opening": (1, {**bare, "pretest": True}), "null": (1, {**task, "max_hints": None, "reveal_after": None}),
        "revealed": (1, {**task, "gave_up": True}), "tried": (1, {**task, "solution": None, "attempts": ["x"]}),
        "own": (1, {k: v for k, v in task.items() if k != "imported"}), "teacher": (2, task),
    }
    for name, (lesson, data) in stored.items():
        raw.execute("INSERT INTO blocks (lesson_id, kind, markdown, data) VALUES (?, 'challenge', ?, ?)", (lesson, name, json.dumps(data)))
    db._lock_imported(raw)
    db._lock_imported(raw)  # a rerun after a crash before the version bump is harmless
    got = {r["markdown"]: (json.loads(r["data"]), json.loads(r["locked"]) if r["locked"] else None) for r in raw.execute("SELECT * FROM blocks").fetchall()}
    raw.close()
    ladder = {"hints": ["one", "two"], "solution": "answer", "max_hints": 0}
    opened = {**task, "hints": [], "solution": None}
    default = challenge.new()["max_hints"]
    assert got["closed"] == got["odd list"] == ({**opened, "max_hints": 2}, ladder)
    assert got["opening"] == ({**opened, "pretest": True, "reveal_after": 1}, ladder)
    assert got["transfer"] == ({**opened, "transfer": True}, ladder)
    assert got["hints only"] == ({**opened, "max_hints": 2}, {**ladder, "solution": None})
    assert got["no list"] == (opened, {**ladder, "hints": []})
    assert got["blank"] == (opened, None)
    assert got["bare"] == got["null"] == ({**opened, "max_hints": max(default, 2), "reveal_after": challenge.REVEAL_AFTER}, {**ladder, "max_hints": default})
    assert got["bare opening"] == ({**opened, "max_hints": default, "reveal_after": 1, "pretest": True}, {**ladder, "max_hints": default})
    untouched = ("revealed", "tried", "own", "teacher")
    assert {k: got[k] for k in untouched} == {k: (stored[k][1], None) for k in untouched}
    # what an import makes of the same task
    for name in stored.keys() - set(untouched):
        data = dict(stored[name][1])
        assert db.lock(data) == got[name][1] and data == got[name][0]
        assert challenge.reveal_blocker(data) and (challenge.hint_blocker(data) is None) == bool(data["max_hints"])


def _checked_course(title: str) -> int:
    """A prepared course with a check of each kind, posed with its tools, and an outline its designer ticked to the end."""
    import asyncio

    from wise_scholar.tools import lesson_flow, quizzes

    author = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, 'teacher')", (f"Key author {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course(title, author)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(course, "Loft", "lesson", db.concepts(course)[0]["id"])
    items = [quizzes.SortItem(text=f"item {n}", category=("SECRET even", "SECRET odd")[n % 2]) for n in range(6)]
    replies = [
        asyncio.run(lesson_flow.set_outline(lesson, ["Predict", "Loft", "Check"], cards=9)),
        asyncio.run(quizzes.pose_quiz(lesson, "Which call lofts?", "choice", "ThruSections", "SECRET why.", ["ThruSections", "MakePipe"],
                                      misconceptions={"MakePipe": "SECRET belief"})),
        asyncio.run(quizzes.pose_quiz(lesson, "Why sections?", "open", "SECRET model.", "SECRET because.")),
        asyncio.run(quizzes.pose_sort(lesson, "Sort them.", ["SECRET even", "SECRET odd"], items, "SECRET tells apart.")),
        asyncio.run(lesson_flow.step_done(lesson)),
        asyncio.run(lesson_flow.finish_lesson(lesson, "You can loft.")),
    ]
    assert not [r for r in replies if r.startswith(("error", "refused"))]
    return course


def _imported(course: int, places, monkeypatch) -> tuple[int, int]:
    """The course published and imported through the routes for a new reader: the replay and its lesson."""
    import asyncio

    from fastapi import UploadFile

    from wise_scholar import app
    from wise_scholar.routes import sharing as sharing_routes

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Key reader {uuid.uuid4().hex[:6]}",)).lastrowid
    data = (places["store"] / f"{v['hash']}.zip").read_bytes()
    mine = asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(data), filename="x.zip")))["id"]
    return mine, db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", mine)["id"]


def _checks(blocks: list[dict]) -> dict[str, dict]:
    return {b["markdown"]: b["data"] for b in blocks if b["kind"] == "quiz"}


def _unit_lesson(course: int) -> int:
    return db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]


def _stored(lesson: int) -> list[dict]:
    """The lesson's blocks as the database holds them, where db.blocks gives them as their reader gets them."""
    return [db.block(r["id"]) for r in db.rows("SELECT id FROM blocks WHERE lesson_id = ? ORDER BY position, id", lesson)]


def _gives_away(data: dict) -> bool:
    return bool({"answer_key", "explanation", "misconceptions"} & data.keys()) or any("category" in o for o in data["options"] if isinstance(o, dict))


def _as_installed_before(course: int, lesson: int) -> None:
    """The replay's blocks as an install left them before keys and ticks stayed behind: as the bundle holds them."""
    from wise_scholar import app

    version = bundle.stored(app.VERSIONS, db.course(course)["source_version"])
    shipped = {b.key: b for x in version.lessons for b in x.blocks}
    for b in db.blocks(lesson):
        if b["key"] in shipped:
            came = {k: v for k, v in (shipped[b["key"]].data or {}).items() if k != "card"}
            db.set_block(b["id"], shipped[b["key"]].markdown, {**(b["data"] or {}), **came})
            db.conn.execute("UPDATE blocks SET locked = NULL WHERE id = ?", (b["id"],))


@pytest.mark.parametrize("installed", ["now", "before"])
def test_a_reader_gets_a_quizs_key_once_they_answered_it(places, monkeypatch, installed):
    import asyncio

    from wise_scholar import app, hub, obsidian
    from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes

    sent, run = [], asyncio.run
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    course = _checked_course(f"Keys {installed}")
    mine, replayed = _imported(course, places, monkeypatch)
    if installed == "before":
        _as_installed_before(mine, replayed)
    held = _checks(_stored(replayed)).values()
    assert len(held) == 3 and all(_gives_away(d) == (installed == "before") for d in held)
    monkeypatch.setattr(hub, "publish", lambda course_id, event: sent.append(event))

    def notes() -> str:
        return "".join(x.decode() for path, x in obsidian.Vault(mine).build().items() if "/Cards/" in path and "Sort" not in path)

    views = (lambda: app._lesson_view(replayed), lambda: next(x for x in app._course(mine)["lessons"] if x["id"] == replayed),
             lambda: run(learner_routes.open_concept(db.concepts(mine)[0]["id"])))
    ids = {b["markdown"]: b["id"] for b in db.blocks(replayed)}
    for view in views:
        choice, opened, sort = _checks(view()["blocks"]).values()
        assert not any(map(_gives_away, (choice, opened, sort)))
        assert (sorted(choice["options"]), sort["options"][0].keys(), sort["categories"]) == (["MakePipe", "ThruSections"], {"text"}, ["SECRET even", "SECRET odd"])
    assert "SECRET" not in notes()

    answered = {"Which call lofts?": "MakePipe", "Why sections?": "no idea", "Sort them.": json.dumps({"item 0": "SECRET odd"})}
    for markdown, answer in answered.items():
        sent.clear()
        run(blocks_routes.answer_quiz(ids[markdown], app.QuizAnswer(answer=answer, confidence=0.4)))
        [data] = [e["block"]["data"] for e in sent if e["type"] == "block.updated" and e["block"]["id"] == ids[markdown]][-1:]
        assert data["answer_key"] and "SECRET" in data["explanation"]
        assert _checks(app._lesson_view(replayed)["blocks"])[markdown] == data
        left = [m for m in list(answered)[list(answered).index(markdown) + 1:]]
        assert not any("answer_key" in _checks(app._lesson_view(replayed)["blocks"])[m] for m in left)
    assert run(blocks_routes.self_grade_quiz(ids["Why sections?"], app.SelfGrade(correct=False)))["data"]["answer_key"] == "SECRET model."
    choice, opened, sort = _checks(app._lesson_view(replayed)["blocks"]).values()
    assert (choice["correct"], choice["answer_key"], choice["misconception"], opened["correct"]) == (False, "ThruSections", "SECRET belief", False)
    assert "item 0" in sort["misplaced"]
    assert "SECRET model." in notes() and "SECRET why." in notes()


def test_the_author_of_a_prepared_course_and_a_unit_taken_offline_hold_their_keys(places, monkeypatch):
    import asyncio

    from wise_scholar import app, handout, hub
    from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes, lessons as lessons_routes
    from wise_scholar.tools import quizzes

    sent = []
    monkeypatch.setattr(hub, "publish", lambda course_id, event: sent.append(event))
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False, then=None: None)
    course = _checked_course("Keys kept")
    again = courses_routes.duplicate_course(course)["id"]
    for mine in (course, again):
        lesson = next(x for x in app._course(mine)["lessons"] if x["phase"] == "lesson")
        choice, opened, sort = _checks(lesson["blocks"]).values()
        assert (choice["answer_key"], choice["explanation"], choice["misconceptions"]) == ("ThruSections", "SECRET why.", {"MakePipe": "SECRET belief"})
        assert opened["answer_key"] == "SECRET model." and sort["options"][0]["category"].startswith("SECRET")
        assert "SECRET model." in handout.markdown(lesson["id"], solutions=True)
        block = next(b for b in lesson["blocks"] if b["markdown"] == "Why sections?")
        edited = blocks_routes.edit_block(block["id"], blocks_routes.BlockEdit(explanation="Edited."))
        assert (edited["data"]["answer_key"], edited["data"]["explanation"]) == ("SECRET model.", "Edited.")
        assert sent[-1]["block"]["data"]["explanation"] == "Edited."

    learner = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Key offline {uuid.uuid4().hex[:6]}",)).lastrowid
    own = db.create_course("Keys offline", learner)["id"]
    db.set_concepts(own, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(own, "Loft", "lesson", db.concepts(own)[0]["id"])
    db.conn.execute("UPDATE lessons SET batch = 1 WHERE id = ?", (lesson,))
    asyncio.run(quizzes.pose_quiz(lesson, "Why loft?", "open", "SECRET join.", "SECRET it joins."))
    assert sent[-1]["block"]["data"]["answer_key"] == _checks(app._lesson_view(lesson)["blocks"])["Why loft?"]["answer_key"] == "SECRET join."
    # sent without an answer, the check waits for the tutor like any other
    asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[])))
    assert "SECRET" not in json.dumps(app._lesson_view(lesson))
    copied = _checks(_stored(_unit_lesson(db.copy_course(own, "Keys offline again")["id"])))
    assert "SECRET" not in json.dumps(copied) and not _gives_away(copied["Why loft?"])


@pytest.mark.parametrize("installed", ["now", "before"])
def test_a_replays_tutor_gets_a_quizs_key_once_the_reader_answered_it(places, monkeypatch, installed):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes

    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: None)
    mine, replayed = _imported(_checked_course(f"Tutor keys {installed}"), places, monkeypatch)
    if installed == "before":
        _as_installed_before(mine, replayed)
    ids = {b["markdown"]: b["id"] for b in db.blocks(replayed)}
    prompt = lambda: app._turn_prompt(db.lesson(replayed), "[learner] help")  # noqa: E731
    assert "Which call lofts?" in prompt() and "| key:  |  | learner: not answered" in prompt() and "SECRET" not in prompt()
    asyncio.run(blocks_routes.answer_quiz(ids["Which call lofts?"], app.QuizAnswer(answer="MakePipe", confidence=0.4)))
    assert "| key: ThruSections | SECRET why. | learner: 'MakePipe'" in prompt()
    assert not any(x in prompt() for x in ("SECRET model.", "SECRET because.", "SECRET tells apart.", "'category'"))


def test_an_upgrade_brings_checks_without_their_keys_and_a_fork_ships_them_as_they_came(places, monkeypatch):
    from wise_scholar.routes import sharing as sharing_routes

    course = _checked_course("Keys upgraded")
    mine, replayed = _imported(course, places, monkeypatch)
    old = bundle.stored(places["store"], db.course(mine)["source_version"])

    def forked():
        manifest, _, _ = bundle.build(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
        return manifest

    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE id = ?", (replayed,))
    shipped = {b.key: b.data for x in old.lessons for b in x.blocks if b.kind == "quiz"}
    assert all("answer_key" in d for d in shipped.values())
    assert {b["key"]: b["data"] for x in forked()["lessons"] for b in x["blocks"] if b["kind"] == "quiz"} == {k: {**d, "imported": True} for k, d in shipped.items()}
    kept = forked()["units"][0]["hash"]
    _as_installed_before(mine, replayed)
    for b in db.blocks(replayed):
        if b["kind"] == "outline":
            db.set_block_markdown(b["id"], "1. Predict\n2. Loft\n3. Check")
    assert forked()["units"][0]["hash"] == kept

    db.add_block(db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"], "prose", "One more thing.")
    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))
    assert len(done["upgraded"]["restarted"]) == 1
    lesson = next(x for x in done["lessons"] if x["phase"] == "lesson")
    assert len(_checks(lesson["blocks"])) == 3
    for blocks in (lesson["blocks"], _stored(lesson["id"])):
        assert not any(map(_gives_away, _checks(blocks).values()))


def _outline(blocks: list[dict]) -> tuple[int, str]:
    [block] = [b for b in blocks if b["kind"] == "outline"]
    return block["data"]["at"], block["markdown"]


PLAIN = "1. Predict\n2. Loft\n3. Check"


def test_an_outline_starts_without_the_ticks_of_whoever_it_came_from(places, monkeypatch):
    import asyncio

    from wise_scholar import app, obsidian
    from wise_scholar.routes import sharing as sharing_routes
    from wise_scholar.tools import lesson_flow

    course = _checked_course("Ticks")
    author = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]
    ticked = "1. Predict ✓\n2. Loft ✓\n3. Check ✓"
    assert _outline(db.blocks(author)) == (3, ticked)
    copy = db.copy_course(course, "Ticks again")["id"]
    assert _outline(_stored(_unit_lesson(copy))) == (0, PLAIN)
    mine, replayed = _imported(course, places, monkeypatch)
    assert _outline(_stored(replayed)) == (0, PLAIN)

    db.add_block(author, "prose", "One more thing.")
    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))
    replayed = _unit_lesson(mine)
    assert _outline(_stored(replayed)) == (0, PLAIN)

    # one installed before still holds the author's ticks, and shows none until the reader's own
    _as_installed_before(mine, replayed)
    assert _outline(_stored(replayed)) == (0, ticked)
    assert _outline(app._lesson_view(replayed)["blocks"]) == (0, PLAIN)
    vault = obsidian.Vault(mine)
    assert PLAIN in "\n".join(x for lesson in vault.lessons for x in vault.lesson_text(lesson))
    asyncio.run(lesson_flow.step_done(replayed))
    assert _outline(db.blocks(replayed)) == _outline(app._lesson_view(replayed)["blocks"]) == (1, "1. Predict ✓\n2. Loft\n3. Check")


@pytest.mark.parametrize("data, markdown", [
    ({"steps": ["a", "b"]}, "The teacher's own plan ✓"), ({"steps": "ab"}, "1. a ✓"), ({}, "1. a ✓"),
    ({"steps": ["a", "b"]}, "1. a\n2. b ✓"), ({"steps": [{"x": 1}, None]}, "1. a ✓"),
])
def test_outline_text_that_is_not_its_steps_stays_as_it_was_written(places, data, markdown):
    course = _checked_course("Written plan")
    author = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]
    [block] = [b for b in db.blocks(author) if b["kind"] == "outline"]
    db.set_block(block["id"], markdown, data)
    mine = _replay(_version(course, places), places)
    for other in (mine, db.copy_course(course, "Written plan again")["id"]):
        for blocks in (_stored(_unit_lesson(other)), db.blocks(_unit_lesson(other))):
            assert [b["markdown"] for b in blocks if b["kind"] == "outline"] == [markdown]


def test_a_step_that_ends_in_the_tick_keeps_its_own(places):
    course = _checked_course("Ticked step")
    author = _unit_lesson(course)
    [block] = [b for b in db.blocks(author) if b["kind"] == "outline"]
    steps = ["a ✓", "b ✓", "c"]
    db.set_block(block["id"], db.outline_text(steps, 2), {"steps": steps, "at": 2})
    ticked, plain = "1. a ✓ ✓\n2. b ✓ ✓\n3. c", "1. a ✓\n2. b ✓\n3. c"
    assert _outline(_stored(author)) == _outline(db.blocks(author)) == (2, ticked)
    mine = _replay(_version(course, places), places)
    for other in (mine, db.copy_course(course, "Ticked step again")["id"]):
        assert _outline(_stored(_unit_lesson(other))) == (0, plain)
    # one installed before, whose reader is now at the second step
    [got] = [b for b in _stored(_unit_lesson(mine)) if b["kind"] == "outline"]
    db.set_block(got["id"], ticked, {**got["data"], "at": 1})
    assert _outline(db.blocks(_unit_lesson(mine))) == (1, "1. a ✓ ✓\n2. b ✓\n3. c")


REASON = "You confused the two cases."
GROWN = "1. Predict\n2. Tell the cases apart\n3. Loft\n4. Check"
FRESH = {"steps": ["Predict", "Tell the cases apart", "Loft", "Check"], "at": 0, "added": None, "cards": 9}


def _grown_course(title: str, mode: str = "learner") -> int:
    """Two finished units with an outline each; the first took a step its tutor added, with a reason."""
    import asyncio

    from wise_scholar.tools import lesson_flow

    author = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Step author {uuid.uuid4().hex[:6]}", mode)).lastrowid
    course = db.create_course(title, author)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Grown", "Plain"], "known": []}])
    grown, plain = (db.create_lesson(course, c["title"], "lesson", c["id"]) for c in db.concepts(course))
    replies = [
        asyncio.run(lesson_flow.set_outline(grown, ["Predict", "Loft", "Check"], cards=9)),
        asyncio.run(lesson_flow.set_outline(grown, FRESH["steps"], REASON)),
        asyncio.run(lesson_flow.set_outline(plain, ["Predict", "Loft", "Check"], cards=9)),
        *(asyncio.run(lesson_flow.finish_lesson(lesson, "You can loft.")) for lesson in (grown, plain)),
    ]
    assert not [r for r in replies if r.startswith(("error", "refused"))]
    [row] = _outline_rows(course, "Grown")
    assert json.loads(row["data"])["added"] == {"step": "Tell the cases apart", "reason": REASON}
    return course


def _outline_rows(course: int, title: str) -> list[dict]:
    return db.rows("SELECT b.markdown, b.data FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
                   "WHERE l.course_id = ? AND l.title = ? AND b.kind = 'outline'", course, title)


def _rows_text(course: int) -> str:
    return json.dumps(db.rows("SELECT b.* FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ?", course))


def _file(version_hash: str, places) -> str:
    with zipfile.ZipFile(places["store"] / f"{version_hash}.zip") as z:
        return z.read("manifest.json").decode()


def _shipped_before(m) -> None:
    """Versions are built as they were while the reason of an added step was part of them."""
    built = bundle._block_data

    def with_reason(block, card_keys, authored=False):
        data = built(block, card_keys, authored)
        return {**data, "added": json.loads(block["data"])["added"]} if block["kind"] == "outline" else data

    m.setattr(bundle, "_block_data", with_reason)


@pytest.mark.parametrize("mode", ["learner", "teacher"])
def test_a_version_leaves_out_why_a_step_was_added(places, monkeypatch, mode):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import lesson_flow

    course = _grown_course(f"Grown {mode}", mode)
    mine, replayed = _imported(course, places, monkeypatch)
    sent = _file(db.course(mine)["source_version"], places)
    [shipped] = [b for x in json.loads(sent)["lessons"] if x["title"] == "Grown" for b in x["blocks"] if b["kind"] == "outline"]
    assert shipped["data"] == FRESH and "2. Tell the cases apart" in shipped["markdown"]
    assert REASON not in sent
    [row] = _outline_rows(mine, "Grown")
    assert (row["markdown"], json.loads(row["data"])) == (GROWN, {**FRESH, "imported": True})
    assert REASON not in _rows_text(mine) and REASON in _rows_text(course)
    assert REASON not in json.dumps(app._lesson_view(replayed))

    # the reader's own tutor may add its one step
    steps = [*FRESH["steps"], "Once more"]
    assert asyncio.run(lesson_flow.set_outline(replayed, steps, "You asked for it.")) == "step added: now step 1 of 5"
    assert asyncio.run(lesson_flow.set_outline(replayed, [*steps, "And again"], "r")) == "refused: the outline already took its one added step"


def test_an_old_bundle_installs_and_upgrades_without_why_a_step_was_added(places, monkeypatch):
    from wise_scholar.routes import sharing as sharing_routes

    course = _grown_course("Grown before")
    with monkeypatch.context() as m:
        _shipped_before(m)
        mine, _ = _imported(course, places, monkeypatch)
        assert REASON in _file(db.course(mine)["source_version"], places)
        [row] = _outline_rows(mine, "Grown")
        assert (row["markdown"], json.loads(row["data"])) == (GROWN, {**FRESH, "imported": True})

        db.add_block(_unit_lesson(course), "prose", "One more thing.")
        v = sharing_routes.publish_version(course, sharing_routes.Publish())
        assert REASON in _file(v["hash"], places)
    done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))["upgraded"]
    assert len(done["restarted"]) == len(done["kept"]) == 1
    [row] = _outline_rows(mine, "Grown")
    assert (row["markdown"], json.loads(row["data"])) == (GROWN, {**FRESH, "imported": True})
    assert REASON not in _rows_text(mine)


def test_only_the_unit_that_took_a_step_restarts_once_and_a_fork_leaves_the_reason_out(places, monkeypatch):
    from wise_scholar.routes import sharing as sharing_routes

    course = _grown_course("Grown restarted")
    with monkeypatch.context() as m:
        _shipped_before(m)
        mine, replayed = _imported(course, places, monkeypatch)
    _as_installed_before(mine, replayed)
    assert REASON in _rows_text(mine)
    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE course_id = ? AND concept_id IS NOT NULL", (mine,))
    fork = bundle.publish(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    assert "Tell the cases apart" in _file(fork["hash"], places) and REASON not in _file(fork["hash"], places)

    for kept in (["Plain"], ["Grown", "Plain"]):
        v = sharing_routes.publish_version(course, sharing_routes.Publish())
        done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))["upgraded"]
        titles = {c["key"]: c["title"] for c in db.concepts(mine)}
        assert sorted(titles[k] for k in done["kept"]) == kept
        assert REASON not in _rows_text(mine)


@pytest.mark.parametrize("mode", ["learner", "teacher"])
def test_a_copy_leaves_out_why_a_step_was_added(places, mode):
    course = _grown_course(f"Grown copied {mode}", mode)
    copy = db.copy_course(course, f"Grown copied {mode} (2)")["id"]
    [row] = _outline_rows(copy, "Grown")
    assert (row["markdown"], json.loads(row["data"])) == (GROWN, FRESH)
    assert REASON not in _rows_text(copy) and REASON in _rows_text(course)


FIGURE = (
    '<svg viewBox="0 0 300 150"><defs><marker id="a2-tip"><path d="M0 0L4 2L0 4z"/></marker></defs>'
    '<g data-part="sun"><circle cx="40" cy="75" r="20"/></g><g data-part="orbit"><ellipse cx="170" cy="75" rx="110" ry="40"/>'
    '<g data-part="earth"><circle cx="280" cy="75" r="8" marker-end="url(#a2-tip)"/></g></g>'
    '<g data-part="guess"><use href="art:bioicons/cc-0/Cell_types/Me/cell" width="20" height="10"/></g>\n</svg>'
)
CELL, LEAF = ({"name": name, "author": "Me", "licence": "CC0", "pack": "Bioicons", "url": "https://bioicons.com"} for name in ("cell", "leaf"))


def _step(say: str, draw=(), erase=()):
    from wise_scholar import board

    return board.BoardStep(say=say, draw=list(draw), erase=list(erase))


def _answers(n: int) -> tuple[str, list]:
    """The drawing and the steps of a figure's nth answer; the first opens by only erasing, the second brings its own icon."""
    if n == 0:
        return ('\n loose SECRET <defs><marker id="tip"><path d="M0 0L4 2L0 4z"/></marker></defs>\n'
                '<g data-part="why"><line x1="200" y1="120" x2="272" y2="80" marker-end="url(#tip)"/>'
                '<g data-part="label"><text x="150" y="140" font-size="14">SECRET tilt</text></g></g> loose SECRET\n',
                [_step("SECRET: you guessed the distance.", erase=["guess"]), _step("SECRET: it tilts.", ["why"])])
    return ('<g data-part="leaf"><use href="art:bioicons/cc-0/Cell_types/Me/leaf" width="20" height="10"/>'
            '<use href="art:bioicons/cc-0/Cell_types/Me/cell" width="20" height="10"/></g><defs><text>SECRET</text></defs>',
            [_step("SECRET: look again.", ["leaf"], ["label"])])


def _answer(lesson: int, figure: int, *which: int) -> None:
    import asyncio

    from wise_scholar.tools import visuals

    for n in which:
        assert asyncio.run(visuals.annotate_figure(lesson, figure, *_answers(n))) == f"drawn on figure {figure}; it plays now"


NARRATED = [("The Sun.", ["sun"], []), ("A guess.", ["guess"], []), ("The orbit.", ["orbit"], [])]


def _narrate(lesson: int, figure: int, steps=NARRATED) -> None:
    import asyncio

    from wise_scholar.tools import visuals

    assert asyncio.run(visuals.narrate_figure(lesson, figure, [_step(*s) for s in steps])).startswith(f"figure {figure} plays")


def _drawn_course(title: str, tmp_path, monkeypatch, mode: str = "learner") -> tuple[int, int, int]:
    """Three finished units: two with a figure that plays as a board, the last one's gone back to, and one without: the
    course, the first one's lesson and its figure, not yet answered on."""
    import asyncio

    from wise_scholar import art, figcheck, figures, tutor
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import lesson_flow, visuals

    icons = tmp_path / "art" / "bioicons" / "cc-0" / "Cell_types" / "Me"
    icons.mkdir(parents=True)
    for name in ("cell", "leaf"):
        (icons / f"{name}.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1"><path d="M0 0h1"/></svg>')
    (icons.parents[2] / "manifest.json").write_text(json.dumps([
        {"id": f"bioicons/cc-0/Cell_types/Me/{n}", "name": n, "category": "Cell types", "author": "Me", "licence": "CC0", "ratio": 2.0} for n in ("cell", "leaf")]))
    monkeypatch.setattr(art, "ART", tmp_path / "art")
    art._manifests.clear()
    monkeypatch.setattr(figcheck, "available", lambda: False)
    monkeypatch.setattr(tutor, "_needs_opening", lambda lesson: False)
    teaches = figures.Teaches(claim="Seasons come from the tilt.", notice="Which side leans.")
    author = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Draw author {uuid.uuid4().hex[:6]}", mode)).lastrowid
    course = db.create_course(title, author)["id"]
    db.set_concepts(course, [{"title": "Seasons", "concepts": ["Asked", "Quiet", "Wordy"], "known": []}])
    lessons = [db.create_lesson(course, c["title"], "lesson", c["id"]) for c in db.concepts(course)]
    for lesson in lessons[:2]:
        assert asyncio.run(visuals.add_figure(lesson, FIGURE, "The tilt", "Earth on its orbit", teaches)).startswith("shown")
        _narrate(lesson, _figure(lesson)["id"])
    asyncio.run(visuals.replace_figure(lessons[1], _figure(lessons[1])["id"], FIGURE, "Again", "Earth"))
    blocks_routes.restore_figure(_figure(lessons[1])["id"])
    db.add_block(lessons[2], "prose", "No figure here.")
    assert not [r for r in (asyncio.run(lesson_flow.finish_lesson(x, "Done.")) for x in lessons) if r.startswith(("error", "refused"))]
    return course, lessons[0], _figure(lessons[0])["id"]


def _figure(lesson: int) -> dict:
    return next(b for b in _stored(lesson) if b["kind"] == "figure")


def _lesson_titled(course: int, title: str) -> int:
    return db.row("SELECT id FROM lessons WHERE course_id = ? AND title = ? AND phase = 'lesson'", course, title)["id"]


def _shipped_figure(version_hash: str, places, title: str = "Asked", kind: str = "figure") -> dict:
    sent = json.loads(_file(version_hash, places))
    return next(b["data"] for x in sent["lessons"] if x["title"] == title for b in x["blocks"] if b["kind"] == kind)


def _ships_answers(m) -> None:
    """Versions are built as they were while answers were part of a figure."""
    from wise_scholar import board

    m.setattr(board, "without_answers", lambda data, authored=False: data)


def _unkept(figure: int) -> dict:
    """The figure as it was answered before the figure it was before was kept."""
    return db.set_block_data(figure, {k: v for k, v in db.block(figure)["data"].items() if k != "unanswered"})["data"]


def _unit_hashes(course: int, places) -> dict[str, str]:
    manifest, _, _ = bundle.build(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    return {u["title"]: u["hash"] for u in manifest["units"]}


def test_a_version_an_install_a_copy_and_an_upgrade_hold_a_figure_without_its_answers(places, tmp_path, monkeypatch):
    from wise_scholar.routes import sharing as sharing_routes

    course, lesson, figure = _drawn_course("Answered", tmp_path, monkeypatch)
    before, hashes = db.block(figure)["data"], _unit_hashes(course, places)
    _answer(lesson, figure, 0, 1)
    answered = db.block(figure)["data"]
    assert "SECRET" in answered["svg"] and len(answered["board"]["steps"]) == 6 and answered["credits"] == [CELL, LEAF]
    assert answered["unanswered"] == {k: before[k] for k in ("svg", "credits", "board")}

    mine, replayed = _imported(course, places, monkeypatch)
    sent = _shipped_figure(db.course(mine)["source_version"], places)
    assert sent == {k: v for k, v in before.items() if k in bundle.SHIPPED["figure"]}
    assert "SECRET" not in _file(db.course(mine)["source_version"], places) and _unit_hashes(course, places) == hashes
    assert _figure(replayed)["data"]["svg"] == before["svg"] and _figure(replayed)["data"]["credits"] == [CELL]
    assert "SECRET" not in _rows_text(mine)

    copy = db.copy_course(course, "Answered (2)")["id"]
    assert _figure(_lesson_titled(copy, "Asked"))["data"] == before
    assert "SECRET" not in _rows_text(copy) and db.block(figure)["data"] == answered

    # the reader asks in turn, and a fork of their course leaves that out too
    came = _figure(replayed)["data"]
    _answer(replayed, _figure(replayed)["id"], 0)
    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE course_id = ? AND concept_id IS NOT NULL", (mine,))
    fork = bundle.publish(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    assert _shipped_figure(fork["hash"], places) == {k: v for k, v in came.items() if k in bundle.SHIPPED["figure"]}

    # an upgrade to a version where the figure was answered in between restarts nothing
    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))["upgraded"]
    assert (done["restarted"], done["added"], done["removed"]) == ([], [], [])


@pytest.mark.parametrize("mode", ["learner", "teacher"])
def test_figures_never_answered_ship_and_copy_as_they_are(places, tmp_path, monkeypatch, mode):
    course, lesson, figure = _drawn_course(f"Quiet {mode}", tmp_path, monkeypatch, mode)
    _answer(lesson, figure, 0)
    db.add_block(_lesson_titled(course, "Wordy"), "example", "Another kind.", {"previous": "its own", "board": "its own"})
    hashes = _unit_hashes(course, places)
    with monkeypatch.context() as m:
        _ships_answers(m)
        assert [t for t, h in _unit_hashes(course, places).items() if h != hashes[t]] == ["Asked"]
    copy = db.copy_course(course, f"Quiet {mode} (2)")["id"]
    quiet = _figure(_lesson_titled(course, "Quiet"))["data"]
    assert quiet["restored"] and quiet["board"] and "unanswered" not in quiet
    assert _figure(_lesson_titled(copy, "Quiet"))["data"] == quiet


def test_an_old_bundle_installs_as_it_came_and_its_unit_restarts_once_without_the_answer(places, tmp_path, monkeypatch):
    from wise_scholar.routes import sharing as sharing_routes

    course, lesson, figure = _drawn_course("Answered before", tmp_path, monkeypatch)
    before = db.block(figure)["data"]
    _answer(lesson, figure, 0)
    with monkeypatch.context() as m:
        _ships_answers(m)
        mine, replayed = _imported(course, places, monkeypatch)
    assert _figure(replayed)["data"]["svg"] == db.block(figure)["data"]["svg"]
    for restarted in (["Asked"], []):
        v = sharing_routes.publish_version(course, sharing_routes.Publish())
        done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))["upgraded"]
        titles = {c["key"]: c["title"] for c in db.concepts(mine)}
        assert [titles[k] for k in done["restarted"]] == restarted
        assert _figure(_lesson_titled(mine, "Asked"))["data"]["svg"] == before["svg"] and "SECRET" not in _rows_text(mine)


NOTE = '<g data-part="note"><text x="10" y="20" font-size="14">SECRET note</text></g>'


def _note(lesson: int, figure: int) -> None:
    import asyncio

    from wise_scholar.tools import visuals

    assert asyncio.run(visuals.annotate_figure(lesson, figure, NOTE, [_step("SECRET.", ["note"])])).startswith("drawn")


def test_a_figure_answered_before_it_was_kept_loses_its_last_answer(places, tmp_path, monkeypatch):
    from xml.etree import ElementTree as ET

    from wise_scholar import board

    course, lesson, figure = _drawn_course("Unkept", tmp_path, monkeypatch)
    _answer(lesson, figure, 0)
    once = {k: v for k, v in db.block(figure)["data"].items() if k != "unanswered"}
    _note(lesson, figure)
    twice = _unkept(figure)
    ET.register_namespace("svg", "http://www.w3.org/2000/svg")  # a server that cleaned no drawing yet writes no prefixes either
    left = board.without_answers(twice)
    assert left == once | {"board": {"steps": once["board"]["steps"]}}  # the one before the last cannot be told
    shipped = _shipped_figure(bundle.publish(course, notes="", licence="CC-BY-4.0", forkable=True, sources=[], **places)["hash"], places)
    assert shipped["svg"] == once["svg"] and "answer" not in shipped["board"]

    # answered or narrated again, what is kept is the figure without it
    _answer(lesson, figure, 1)
    assert db.block(figure)["data"]["unanswered"] == {k: left[k] for k in ("svg", "credits", "board")}
    assert board.without_answers(db.block(figure)["data"]) == left
    db.set_block_data(figure, twice)
    _narrate(lesson, figure, [("The Sun.", ["sun"], []), ("SECRET.", ["note"], [])])
    assert board.without_answers(db.block(figure)["data"]) == left | {"board": {"steps": [{"say": "The Sun.", "draw": ["sun"], "erase": []}]}}

    # its first answer leaves no board behind, and its defs and credits stay
    db.set_block_data(figure, {k: v for k, v in once.items() if k != "board"} | {"board": {"steps": [{"say": "x", "draw": ["why"], "erase": []}], "answer": 0}})
    left = board.without_answers(db.block(figure)["data"])
    assert "board" not in left and f'id="f{figure}-a3-tip"' in left["svg"] and "SECRET tilt" not in left["svg"] and left["credits"] == once["credits"]


def test_a_figure_that_was_only_its_answer_stays(places):
    from wise_scholar import board

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9"><defs><path id="p" d="M0 0h1" /></defs><g data-part="why"><rect /></g></svg>'
    data = {"svg": svg, "credits": [], "board": {"steps": [{"say": "x", "draw": ["why"], "erase": []}], "answer": 0}}
    assert board.without_answers(data) == data


def test_narration_written_after_an_answer_keeps_what_the_figure_had(places, tmp_path, monkeypatch):
    from wise_scholar import board

    course, lesson, figure = _drawn_course("Narrated after", tmp_path, monkeypatch)
    before = db.block(figure)["data"]
    _answer(lesson, figure, 0)
    _narrate(lesson, figure, [("The Sun.", ["sun"], []), ("SECRET why.", ["why"], []), ("The orbit.", ["orbit"], ["label"]),
                              ("SECRET is wiped.", [], ["why"]), ("A guess.", ["guess"], [])])
    told = [{"say": say, "draw": [part], "erase": []} for say, part in (("The Sun.", "sun"), ("The orbit.", "orbit"), ("A guess.", "guess"))]
    assert board.without_answers(db.block(figure)["data"]) == before | {"board": {"steps": told}}
    _note(lesson, figure)
    assert board.without_answers(db.block(figure)["data"]) == before | {"board": {"steps": told}}
    _narrate(lesson, figure, [("SECRET why.", ["why"], []), ("SECRET note.", ["note"], [])])
    assert board.without_answers(db.block(figure)["data"]) == {k: v for k, v in before.items() if k != "board"}


def test_a_drawing_gone_back_to_keeps_what_it_was_before_its_answers_and_a_copy_leaves_them_out_of_the_one_it_replaced(places, tmp_path, monkeypatch):
    import asyncio

    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import visuals

    course, lesson, figure = _drawn_course("Redrawn", tmp_path, monkeypatch)
    before = db.block(figure)["data"]
    _answer(lesson, figure, 0, 1)
    asyncio.run(visuals.replace_figure(lesson, figure, SVG, "Redrawn", "a square"))
    assert "SECRET" in json.dumps(db.block(figure)["data"]["previous"]) and "unanswered" not in db.block(figure)["data"]
    hashes = _unit_hashes(course, places)
    with monkeypatch.context() as m:
        _ships_answers(m)
        assert _unit_hashes(course, places) == hashes
    copy = db.copy_course(course, "Redrawn (2)")["id"]
    copied = _figure(_lesson_titled(copy, "Asked"))["data"]
    assert copied["previous"] == before | {"caption": "The tilt"} and "SECRET" not in _rows_text(copy)

    blocks_routes.restore_figure(figure)
    mine, replayed = _imported(course, places, monkeypatch)
    assert "SECRET" not in _file(db.course(mine)["source_version"], places) and "SECRET" not in _rows_text(mine)
    assert _figure(replayed)["data"]["svg"] == before["svg"]


def test_an_answer_in_a_prepared_course_is_its_authors_material(places, tmp_path, monkeypatch):
    import asyncio

    from wise_scholar.tools import visuals

    course, lesson, figure = _drawn_course("Prepared", tmp_path, monkeypatch, mode="teacher")
    _answer(lesson, figure, 0)
    drawn = db.block(figure)["data"]
    kept = {k: v for k, v in drawn.items() if k != "unanswered"} | {"board": {"steps": drawn["board"]["steps"]}}
    copy = db.copy_course(course, "Prepared (2)")["id"]
    assert _figure(_lesson_titled(copy, "Asked"))["data"] == kept
    mine, replayed = _imported(course, places, monkeypatch)
    assert _shipped_figure(db.course(mine)["source_version"], places) == {k: v for k, v in kept.items() if k in bundle.SHIPPED["figure"]}
    assert _figure(replayed)["data"]["svg"] == drawn["svg"] and _figure(replayed)["data"]["credits"] == drawn["credits"]

    asyncio.run(visuals.replace_figure(lesson, figure, SVG, "Redrawn", "a square"))
    again = db.copy_course(course, "Prepared (3)")["id"]
    assert _figure(_lesson_titled(again, "Asked"))["data"]["previous"] == kept | {"caption": "The tilt"}


# Draws as `wise-board serve --stdio` does, an element for each `eq` line and a beat for each `>` line, on the prior board
# when there is one; refuses a script that places an element by one the board does not have.
INK = """\
import json, re, sys
for line in sys.stdin:
    call = json.loads(line)
    doc, text = json.loads(call["params"].get("prior") or '{"schema": 2, "pages": 1, "elements": [], "beats": []}'), "ok"
    for said in call["params"]["script"].splitlines():
        if said.startswith("> "):
            doc["beats"].append({"say": said[2:]})
        elif drawn := re.fullmatch(r"eq (\\w+)(?: below (\\w+))?: (.*)", said):
            if drawn[2] and drawn[2] not in [e["id"] for e in doc["elements"]]:
                text = f'no element "{drawn[2]}"'
            doc["elements"].append({"id": drawn[1], "kind": "eq", "alt": drawn[3]})
    print(json.dumps({"jsonrpc": "2.0", "id": call["id"], "result": {"ok": text == "ok", "text": text, "doc": json.dumps(doc)}}), flush=True)
"""
WRITTEN = 'board "Legs"\n> The theorem.\neq e: a^2+b^2=c^2\n'
REPLY, AGAIN = "> SECRET: you doubled c.\neq why below e: SECRET not 2c\n", "> SECRET: look again.\neq look below why: SECRET c\n"
MORE, BUILT_ON = "> Solve it.\neq s below e: c=5\n", "> So it holds.\neq so below why: c is not 10\n"


@pytest.fixture
def ink(tmp_path, monkeypatch):
    import sys

    from wise_scholar import tutor, wiseboard

    binary = tmp_path / "wise-board"
    binary.write_text(f"#!{sys.executable}\n{INK}")
    binary.chmod(0o755)
    monkeypatch.setenv(wiseboard.ENV, str(binary))
    monkeypatch.setattr(tutor, "_needs_opening", lambda lesson: False)
    yield
    wiseboard.stop()


def _written_course(title: str, mode: str = "learner") -> tuple[int, int, int]:
    """Two finished units with a handwritten board each: the course and the boards, not yet answered on."""
    import asyncio

    from wise_scholar import figures
    from wise_scholar.tools import lesson_flow, visuals

    author = db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Ink author {uuid.uuid4().hex[:6]}", mode)).lastrowid
    course = db.create_course(title, author)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Triangles", "concepts": ["Asked", "Quiet"], "known": []}])
    lessons = [db.create_lesson(course, c["title"], "lesson", c["id"]) for c in db.concepts(course)]
    for lesson in lessons:
        assert asyncio.run(visuals.add_board(lesson, WRITTEN, figures.Teaches(claim="The squares add up.", notice="The legs."))).startswith("shown")
        assert not asyncio.run(lesson_flow.finish_lesson(lesson, "Done.")).startswith(("error", "refused"))
    return course, *(_board(lesson)["id"] for lesson in lessons)


def _board(lesson: int) -> dict:
    return next(b for b in _stored(lesson) if b["kind"] == "board")


def _turn(monkeypatch, lesson: int, path: str, body: dict, *calls: tuple[int, str], end: str = "well") -> list[str]:
    """The replies to the extend_board calls a tutor makes, as a backend makes them, in the lesson's turn this POST starts."""
    import asyncio
    from types import SimpleNamespace

    import httpx

    from wise_scholar import app, backends, tutor

    replies, running = [], asyncio.Event()

    async def run_turn(prompt, *, token, **kwargs):
        running.set()
        context = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={backends.TURN_HEADER: token})))
        for board, script in calls:
            replies.append(await tutor.mcp._tool_manager.call_tool("extend_board", {"block_id": board, "script": script}, context))
        if end == "stopped":
            await asyncio.sleep(60)
        if end == "raised":
            raise RuntimeError("the agent broke")
        yield {"type": "turn.done", "ok": end == "well", "error": None if end == "well" else end}

    async def post() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://127.0.0.1") as client:
            assert (await client.post(path, json=body)).status_code == 202
            turn = app._turns[lesson]
            if end == "stopped":
                await running.wait()
                assert (await client.post(f"/api/lessons/{lesson}/stop")).status_code == 204
            await turn

    monkeypatch.setattr(app.backend, "run_turn", run_turn)
    asyncio.run(asyncio.wait_for(post(), 30))
    assert lesson not in app._turns and lesson not in tutor.turns
    return replies


def _ask(monkeypatch, board: int, *calls: tuple[int, str], part: str = "e", end: str = "well") -> list[str]:
    lesson = db.block(board)["lesson_id"]
    return _turn(monkeypatch, lesson, f"/api/blocks/{board}/ask", {"part": part, "question": "Is c doubled?"}, *calls, end=end)


def _go_on(monkeypatch, board: int, *calls: tuple[int, str]) -> list[str]:
    lesson = db.block(board)["lesson_id"]
    return _turn(monkeypatch, lesson, f"/api/lessons/{lesson}/turns", {"text": "Go on."}, *calls)


def test_a_version_an_install_a_copy_and_an_upgrade_hold_a_board_without_its_answers(places, ink, monkeypatch):
    from wise_scholar import obsidian
    from wise_scholar.routes import sharing as sharing_routes

    course, board, _ = _written_course("Asked on a board")
    before, hashes = db.block(board)["data"], _unit_hashes(course, places)
    assert _ask(monkeypatch, board, (board, REPLY)) == [f"board {board} extended; it plays now"]
    _ask(monkeypatch, board, (board, AGAIN), part="why")
    answered = db.block(board)["data"]
    assert answered["script"] == WRITTEN + REPLY + AGAIN and [e["id"] for e in answered["doc"]["elements"]] == ["e", "why", "look"]

    mine, replayed = _imported(course, places, monkeypatch)
    version = db.course(mine)["source_version"]
    assert _shipped_figure(version, places, kind="board") == before
    assert "SECRET" not in _file(version, places) and _unit_hashes(course, places) == hashes
    came = _board(replayed)["data"]
    assert came == before | {"imported": True} and "SECRET" not in _rows_text(mine)

    copy = db.copy_course(course, "Asked on a board (2)")["id"]
    assert _board(_lesson_titled(copy, "Asked"))["data"] == before and "SECRET" not in _rows_text(copy)

    # the owner keeps their board as it was answered
    assert db.block(board)["data"] == answered == before | {k: answered[k] for k in ("script", "doc")} | {"unanswered": {k: before[k] for k in ("script", "doc")}}
    assert "SECRET not 2c" in "".join(text.decode() for path, text in obsidian.Vault(course).build().items() if path.endswith(".md"))

    # the reader asks in turn, and a fork of their course leaves that out too
    theirs = _board(replayed)["id"]
    _ask(monkeypatch, theirs, (theirs, REPLY))
    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE course_id = ? AND concept_id IS NOT NULL", (mine,))
    fork = bundle.publish(mine, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    assert "SECRET" in _rows_text(mine) and _shipped_figure(fork["hash"], places, kind="board") == came

    # an upgrade to a version where the board was answered in between restarts nothing
    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    done = sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=v["hash"]))["upgraded"]
    assert (done["restarted"], done["added"], done["removed"]) == ([], [], [])


def test_what_a_board_goes_on_with_after_an_answer_ships_unless_it_builds_on_the_answer(places, ink, monkeypatch):
    from wise_scholar import wiseboard

    course, board, _ = _written_course("Continued after")
    before = db.block(board)["data"]
    _ask(monkeypatch, board, (board, REPLY))
    extended = [f"board {board} extended; it plays now"]
    assert _go_on(monkeypatch, board, (board, MORE)) == extended
    kept = db.block(board)["data"]["unanswered"]
    assert kept["script"] == WRITTEN + MORE and kept["doc"]["beats"] == [{"say": "The theorem."}, {"say": "Solve it."}]
    assert [e["id"] for e in kept["doc"]["elements"]] == ["e", "s"]

    # what is left of a continuation that names the answer's parts would not be drawn: the board is kept as it was
    assert _go_on(monkeypatch, board, (board, BUILT_ON)) == extended
    data = db.block(board)["data"]
    assert data["script"] == WRITTEN + REPLY + MORE + BUILT_ON and data["unanswered"] == kept
    copy = db.copy_course(course, "Continued after (2)")["id"]
    assert _board(_lesson_titled(copy, "Asked"))["data"] == before | kept

    # a wise-board that could not draw it just now is called again, so nothing is written before it can
    render = wiseboard.render

    async def busy(script, prior=None):
        if prior == kept["doc"]:
            raise wiseboard.Busy("wise-board is busy")
        return await render(script, prior)

    with monkeypatch.context() as m:
        m.setattr(wiseboard, "render", busy)
        assert _go_on(monkeypatch, board, (board, "> Last.\n")) == ["error: wise-board is busy"]
    assert db.block(board)["data"] == data


def test_a_board_that_grew_while_its_kept_board_was_drawn_is_not_written_over(places, ink, monkeypatch):
    from wise_scholar import wiseboard
    from wise_scholar.tools import visuals

    _, board, _ = _written_course("Grew meanwhile")
    _ask(monkeypatch, board, (board, REPLY))
    kept, render, other, landed = db.block(board)["data"]["unanswered"], wiseboard.render, "> Or b.\neq other below e: b=4\n", []

    async def grown_meanwhile(script, prior=None):
        if script == MORE and prior == kept["doc"]:
            landed.append(await visuals.extend_board(board, other))
        return await render(script, prior)

    monkeypatch.setattr(wiseboard, "render", grown_meanwhile)
    assert _go_on(monkeypatch, board, (board, MORE)) == [f"error: board {board} grew while this was drawn; extend it again from what it shows now"]
    assert landed == [f"board {board} extended; it plays now"]
    data = db.block(board)["data"]
    assert data["script"] == WRITTEN + REPLY + other and [e["id"] for e in data["doc"]["elements"]] == ["e", "why", "other"]
    assert data["unanswered"]["script"] == WRITTEN + other and [e["id"] for e in data["unanswered"]["doc"]["elements"]] == ["e", "other"]


@pytest.mark.parametrize("end", ["well", "failed", "raised", "stopped"])
def test_a_question_whose_turn_wrote_no_answer_leaves_no_mark_on_its_board(places, ink, monkeypatch, end):
    course, board, _ = _written_course(f"Unmarked {end}")
    before = db.block(board)["data"]
    assert _ask(monkeypatch, board, end=end) == [] and db.block(board)["data"] == before
    _go_on(monkeypatch, board, (board, MORE))
    data = db.block(board)["data"]
    assert data["script"] == WRITTEN + MORE and "unanswered" not in data
    assert _board(_lesson_titled(db.copy_course(course, f"Unmarked {end} (2)")["id"], "Asked"))["data"] == data


def test_only_the_board_asked_about_is_answered(places, ink, monkeypatch):
    course, board, other = _written_course("Other board")
    lesson = db.block(board)["lesson_id"]
    db.conn.execute("UPDATE blocks SET lesson_id = ? WHERE id = ?", (lesson, other))
    _ask(monkeypatch, board, (other, MORE), (board, REPLY))
    assert "unanswered" in db.block(board)["data"] and "unanswered" not in db.block(other)["data"]


@pytest.mark.parametrize("mode", ["learner", "teacher"])
def test_boards_never_answered_ship_and_copy_as_they_are(places, ink, monkeypatch, mode):
    import asyncio

    from fastapi import HTTPException

    from wise_scholar.routes import blocks as blocks_routes

    course, board, quiet = _written_course(f"Quiet board {mode}", mode)
    _go_on(monkeypatch, quiet, (quiet, MORE))
    if mode == "learner":
        _ask(monkeypatch, board, (board, REPLY))
    else:
        with pytest.raises(HTTPException, match="take no answers"):
            asyncio.run(blocks_routes.ask_about_part(board, blocks_routes.BoardQuestion(part="e", question="Is c doubled?")))
    hashes = _unit_hashes(course, places)
    with monkeypatch.context() as m:
        _ships_answers(m)
        assert [t for t, h in _unit_hashes(course, places).items() if h != hashes[t]] == (["Asked"] if mode == "learner" else [])
    data = db.block(quiet)["data"]
    assert data["script"] == WRITTEN + MORE and "unanswered" not in data
    copy = db.copy_course(course, f"Quiet board {mode} (2)")["id"]
    assert _board(_lesson_titled(copy, "Quiet"))["data"] == data


def test_the_same_content_packs_to_the_same_bytes_and_a_fork_credits_its_origin(places):
    a = _authored(places)
    manifest, assets, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert bundle.pack(manifest, assets) == bundle.pack(manifest, assets)
    # A card naming no beliefs packs as cards did before beliefs existed, so its unit's hash, and an upgrade over it, holds.
    assert [c["misconceptions"] for c in manifest["cards"]] == [[{"option": "MakePipe", "belief": "a pipe sweep joins sections"}]]
    assert bundle._beliefs({"misconceptions": "{}"}) == {}
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
    manifest, assets, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[a["kept"]], source_dir=places["source_dir"])
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
    from wise_scholar.routes import courses as courses_routes, sharing as sharing_routes

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    a = _authored(places)
    v = sharing_routes.publish_version(a["course"], sharing_routes.Publish(notes="v1", forkable=False, sources=[a["kept"]]))
    assert sharing_routes.version_bundle(v["hash"]).filename == "blade-lofting-v1.zip"
    with pytest.raises(HTTPException, match="no such version"):
        sharing_routes.version_bundle("../../etc/passwd")

    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Reader {uuid.uuid4().hex[:6]}",)).lastrowid
    data = (places["store"] / f"{v['hash']}.zip").read_bytes()
    made = asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(data), filename="x.zip")))
    assert made["mode"] == "replay" and db.course(made["id"])["profile_id"] == reader
    assert app._course(made["id"])["setup"] == [{"command": "uv pip install plotly", "status": "asked"}]
    assert asyncio.run(courses_routes.decide_setup(made["id"], 0, app.Decision(allow=False)))["setup"][0]["status"] == "refused"
    with pytest.raises(HTTPException, match="already decided"):
        asyncio.run(courses_routes.decide_setup(made["id"], 0, app.Decision(allow=True)))
    empty = db.create_course("Nothing yet", reader)["id"]
    with pytest.raises(HTTPException, match="nothing to publish"):
        sharing_routes.publish_version(empty, sharing_routes.Publish())
    # a unit written in full for offline study is enough to publish, with nothing finished
    db.set_concepts(empty, [{"title": "Basics", "concepts": ["Pressure"], "known": []}])
    offline = db.create_lesson(empty, "Pressure", "lesson", db.concepts(empty)[0]["id"])
    db.add_block(offline, "prose", "Pressure is force over area.")
    db.conn.execute("UPDATE lessons SET prepared_offline = 1 WHERE id = ?", (offline,))
    sharing_routes.publish_version(empty, sharing_routes.Publish())
    assert bundle.versions(empty)[0]["written"] == 1
    with pytest.raises(HTTPException, match="does not allow"):
        sharing_routes.publish_version(made["id"], sharing_routes.Publish())
    with pytest.raises(HTTPException, match="not a course bundle"):
        asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(b"nope"), filename="x.zip")))


def assert_replay_view(view):
    assert view["replay"] is True
    assert [b["kind"] for b in view["blocks"]] == ["prose", "challenge", "quiz", "quiz"]


def assert_misses_hold_the_tutor_back(started, replayed, open_quiz):
    assert started == []
    assert db.block(open_quiz["id"])["data"]["answer_key"] == "They bound the surface."
    assert not any(b["kind"] == "done" for b in db.blocks(replayed))


def assert_a_self_graded_miss_calls_the_tutor(started, replayed, blocks_routes):
    [(where, line)] = started
    assert where == replayed
    assert blocks_routes.REPLAY_MISS in line
    assert "marked it wrong" in line
    assert db.blocks(replayed)[-1]["kind"] == "done"
    assert db.blocks(replayed)[-1]["markdown"] == "You can loft two wires."


def test_a_replayed_unit_runs_as_written_and_calls_the_tutor_only_on_misses(places, monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes, learner as learner_routes

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
    assert_replay_view(view)
    pretest, right, open_quiz = view["blocks"][1:]

    asyncio.run(blocks_routes.attempt(pretest["id"], blocks_routes.Answer(answer="two wires make a surface")))
    asyncio.run(blocks_routes.answer_quiz(right["id"], app.QuizAnswer(answer="ThruSections", confidence=0.8)))
    asyncio.run(blocks_routes.answer_quiz(open_quiz["id"], app.QuizAnswer(answer="no idea really", confidence=0.3)))
    assert_misses_hold_the_tutor_back(started, replayed, open_quiz)

    asyncio.run(blocks_routes.self_grade_quiz(open_quiz["id"], app.SelfGrade(correct=False)))
    assert_a_self_graded_miss_calls_the_tutor(started, replayed, blocks_routes)

    prompt = app._turn_prompt(db.lesson(replayed), "[learner] why?")
    assert "[replay]" in prompt
    assert "Lofting joins sections." in prompt

    unwritten = next(c for c in db.concepts(mine) if c["unwritten"])
    live = asyncio.run(learner_routes.open_concept(unwritten["id"]))
    assert live["replay"] is False
    assert "The lesson begins" in started[-1][1]

    with pytest.raises(app.HTTPException, match="cards left"):
        courses_routes.card_placement(mine)  # the one written unit is finished already
    fresh = bundle.install(reader, version_hash, manifest, assets, places["source_dir"])["id"]
    placement = courses_routes.card_placement(fresh)
    [card] = placement["blocks"]
    assert card["data"]["kind"] == "choice"
    assert card["data"].get("answer_key") is None
    asyncio.run(blocks_routes.answer_quiz(card["id"], app.QuizAnswer(answer="ThruSections", confidence=0.9)))
    assert db.blocks(placement["id"])[-1]["kind"] == "done"
    assert db.concepts(fresh)[0]["known"] == 1
    assert len(started) == 2
    with pytest.raises(app.HTTPException, match="cards left"):
        courses_routes.card_placement(fresh)
    with pytest.raises(app.HTTPException, match="only an imported course"):
        courses_routes.card_placement(course)


def assert_check_prompts(prompts, a, prose):
    assert len(prompts) > 1
    assert all("[author]" in p for p in prompts)
    assert all("pump maker" in p for p in prompts)
    joined = "".join(prompts)
    assert f"[block {prose['key']}, lesson \"Lofting\"]" in joined
    assert "[file loft/new.py]" in joined


def assert_proposals(replies):
    assert replies[0].splitlines() == ["1: proposed", "2: proposed", "3: proposed", "4: error: old is not in that block; copy it exactly",
                                      "5: error: there is no summary 'nope' in this version", "6: already proposed"]


def assert_version_holds_accepted_edits(manifest, assets, plain):
    [lesson] = manifest.lessons
    assert lesson.blocks[0].markdown == "Lofting joins **profiles**."
    assert lesson.blocks[1].data["options"] == ["Loft", "MakePipe"]
    [card] = manifest.cards
    assert (card.question, card.options, card.answer_key) == ("Which call lofts wires?", ["Loft", "MakePipe"], "Loft")
    assert {f.path: assets[f.asset].decode() for f in manifest.files}["loft/new.py"] == "# TODO loft"
    assert manifest.units[1].hash != plain["units"][1]["hash"]
    assert manifest.units[0].hash == plain["units"][0]["hash"]


def assert_course_keeps_its_own_content(a, prose, quiz_block):
    assert db.block(prose["id"])["markdown"] == "Lofting joins **sections**."
    assert db.card(a["card"])["answer_key"] == "ThruSections"
    assert db.block(quiz_block["id"])["data"]["options"] == ["ThruSections", "MakePipe"]


def test_the_publish_check_proposes_edits_the_author_accepts_into_the_version_only(places, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException
    from mcp.server.mcpserver.exceptions import ToolError

    from wise_scholar import app, tutor
    from wise_scholar.tools import side_turns as side_tools
    from wise_scholar.routes import sharing as sharing_routes
    from wise_scholar.backends import TURN_HEADER

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    monkeypatch.setattr(sharing_routes, "CHECK_CHARS", 200)
    a = _authored(places)
    prose, quiz_block = db.blocks(a["lesson"])[:2]
    card_key = db.card(a["card"])["key"]
    prompts, replies = [], []

    async def turn(lesson, prompt, kind, what):
        assert kind == "cleanup"
        assert lesson["course_id"] == a["course"]
        prompts.append(prompt)
        if len(prompts) == 1:
            replies.append(await side_tools.propose_edits(a["course"], [
                side_tools.Edit(target="block", ref=prose["key"], old="**sections**", new="**profiles**", reason="r"),
                side_tools.Edit(target="card", ref=card_key, old="ThruSections", new="Loft", reason="r"),
                side_tools.Edit(target="file", ref="loft/new.py", old="TODO", new="FIXME", reason="r"),
                side_tools.Edit(target="block", ref=prose["key"], old="not in it", new="x", reason="r"),
                side_tools.Edit(target="summary", ref="nope", old="a", new="b", reason="r"),
                side_tools.Edit(target="block", ref=prose["key"], old="**sections**", new="**rings**", reason="r"),
            ]))
        return True

    monkeypatch.setattr(app, "_background_turn", turn)
    asyncio.run(sharing_routes._check(a["course"]))
    assert_check_prompts(prompts, a, prose)
    assert_proposals(replies)
    check = sharing_routes.publish_check(a["course"])
    assert check["checked"]
    assert not check["running"]
    assert [e["lesson"] for e in check["edits"]] == ["Lofting", None, None]
    block_edit, card_edit, file_edit = check["edits"]
    sharing_routes.decide_edit(a["course"], block_edit["id"], sharing_routes.EditStatus(status="accepted"))
    sharing_routes.decide_edit(a["course"], card_edit["id"], sharing_routes.EditStatus(status="accepted"))
    sharing_routes.decide_edit(a["course"], file_edit["id"], sharing_routes.EditStatus(status="rejected"))
    with pytest.raises(HTTPException, match="no such edit"):
        sharing_routes.decide_edit(a["course"], 10**9, sharing_routes.EditStatus(status="accepted"))

    plain, _, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    v = sharing_routes.publish_version(a["course"], sharing_routes.Publish())
    assert v["stale"] == 0
    _, manifest, assets = bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())
    assert_version_holds_accepted_edits(manifest, assets, plain)
    assert_course_keeps_its_own_content(a, prose, quiz_block)

    # A rerun keeps the author's decisions and reads the course with the accepted edits already made.
    prompts.clear()
    asyncio.run(sharing_routes._check(a["course"]))
    assert "**profiles**" in "".join(prompts)
    assert [e["status"] for e in sharing_routes.publish_check(a["course"])["edits"]] == ["accepted", "accepted", "rejected"]

    db.conn.execute("UPDATE blocks SET markdown = 'Rewritten.' WHERE id = ?", (prose["id"],))
    assert sharing_routes.publish_version(a["course"], sharing_routes.Publish())["stale"] == 1

    lesson_turn = db.lesson(a["lesson"])
    context = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={TURN_HEADER: "tok-lesson"})))
    tutor.turn_started(lesson_turn, "tok-lesson")
    try:
        with pytest.raises(ToolError, match="not available in this turn"):
            asyncio.run(tutor.mcp._tool_manager.call_tool("propose_edits", {"course_id": a["course"], "edits": []}, context))
    finally:
        tutor.turn_ended(lesson_turn["id"])
    assert asyncio.run(side_tools.propose_edits(a["course"], [])) == f"error: course {a['course']} is not being checked"


def test_an_edit_to_a_quiz_block_reaches_its_card_and_a_broken_sort_key_is_refused(places):
    a = _authored(places)
    quiz_block = db.blocks(a["lesson"])[1]
    edit = {"id": 1, "target": "block", "ref": quiz_block["key"], "old": "lofts wires", "new": "joins wires"}
    manifest, assets, stale = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"], edits=[edit])
    assert stale == [] and manifest["cards"][0]["question"] == "Which call joins wires?"
    assert manifest["lessons"][0]["blocks"][1]["markdown"] == "Which call joins wires?"

    sort = {"key": "f" * 32, "unit": None, "question": "Sort", "kind": "sort", "options": [{"text": "a", "category": "Left"}],
            "answer_key": '["Left", "Right"]', "explanation": "", "scheduled": True, "vocab": False, "lemma": None, "lang": None, "translation": ""}
    manifest["cards"].append(sort)
    assert not bundle.apply_edit(manifest, assets, {"target": "card", "ref": sort["key"], "old": "Left", "new": 'Le"ft'})
    assert bundle.apply_edit(manifest, assets, {"target": "card", "ref": sort["key"], "old": "Left", "new": "Port"})
    assert sort["answer_key"] == '["Port", "Right"]' and sort["options"] == [{"text": "a", "category": "Port"}]


def test_a_check_starts_in_the_background_and_blocks_publishing_until_it_ends(places, monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.routes import sharing as sharing_routes

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    a = _authored(places)
    release = None

    async def check(course_id):
        await release.wait()
        raise RuntimeError("the agent went away")

    monkeypatch.setattr(sharing_routes, "_check", check)

    async def scenario():
        nonlocal release
        release = asyncio.Event()
        assert (await sharing_routes.start_publish_check(a["course"]))["running"]
        with pytest.raises(HTTPException, match="already being checked"):
            await sharing_routes.start_publish_check(a["course"])
        with pytest.raises(HTTPException, match="wait for the check"):
            sharing_routes.publish_version(a["course"], sharing_routes.Publish())
        release.set()
        await sharing_routes._checks[a["course"]]

    asyncio.run(scenario())
    state = sharing_routes.publish_check(a["course"])
    assert not state["running"] and state["failed"]
    sharing_routes._checks_failed.discard(a["course"])


def assert_upgrade_offer(offer):
    assert offer["number"] == 2
    assert offer["notes"] == "fitting written"
    assert (offer["kept"], offer["restarted"], offer["added"], offer["removed"]) == (["Lofting"], ["Fitting"], ["Trimming"], ["Dropped"])


def assert_upgraded_units(course, mine, a, card, gone):
    fitting, lofting = a["units"]
    after = {c["key"]: c for c in db.concepts(course)}
    assert [c["title"] for c in db.concepts(course)] == ["Fitting", "Lofting", "Trimming"]
    assert after[lofting["key"]]["known"] == 1
    assert db.row("SELECT COUNT(*) AS n FROM answers WHERE card_id = ?", card)["n"] == 1
    [trimming] = [c for k, c in after.items() if k not in mine]
    assert after[fitting["key"]]["unwritten"] == 0
    assert trimming["unwritten"] == 1
    written = db.row("SELECT id FROM lessons WHERE course_id = ? AND concept_id = ?", course, after[fitting["key"]]["id"])
    assert [b["markdown"] for b in db.blocks(written["id"])] == ["Half a lesson on fitting."]
    assert db.rows("SELECT id FROM lessons WHERE concept_id = ?", gone) == []
    assert db.concept_view(course)
    assert db.needs(course) == {after[lofting["key"]]["id"]: [after[fitting["key"]]["id"]]}


def test_an_upgrade_keeps_unchanged_units_restarts_changed_ones_and_is_offered_on_import(places, monkeypatch):
    import asyncio

    from fastapi import HTTPException, UploadFile

    from wise_scholar import app
    from wise_scholar.routes import sharing as sharing_routes

    monkeypatch.setattr(app, "SOURCES", places["source_dir"])
    monkeypatch.setattr(app, "VERSIONS", places["store"])
    a = _authored(places)
    fitting, lofting = a["units"]
    v1 = sharing_routes.publish_version(a["course"], sharing_routes.Publish())
    data1 = (places["store"] / f"{v1['hash']}.zip").read_bytes()
    readers = [db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Reader {uuid.uuid4().hex[:6]}",)).lastrowid for _ in range(2)]
    course = asyncio.run(sharing_routes.import_course(readers[0], UploadFile(io.BytesIO(data1), filename="v1.zip")))["id"]
    assert app._course(course)["upgrade"] is None

    # The reader works through the written unit, and the course holds a unit the next version no longer has.
    mine = {c["key"]: c for c in db.concepts(course)}
    card = db.row("SELECT id FROM cards WHERE course_id = ? AND concept_id = ?", course, mine[lofting["key"]]["id"])["id"]
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'ThruSections', 0.9, 1)", (card,))
    db.conn.execute("UPDATE concepts SET known = 1 WHERE id = ?", (mine[lofting["key"]]["id"],))
    gone = db.conn.execute("INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Old', 'Dropped', 0, 9, 'concept')", (course,)).lastrowid
    db.create_lesson(course, "Dropped", "lesson", gone)

    # The author finishes the other unit and adds one, then publishes again.
    begun = db.row("SELECT id FROM lessons WHERE course_id = ? AND concept_id = ?", a["course"], fitting["id"])["id"]
    db.add_block(begun, "done", "", {})
    db.conn.execute("INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Sections', 'Trimming', 0, 5, 'concept')", (a["course"],))
    v2 = sharing_routes.publish_version(a["course"], sharing_routes.Publish(notes="fitting written"))

    assert_upgrade_offer(app._course(course)["upgrade"])
    assert sharing_routes.skip_upgrade(course, sharing_routes.Upgrade(hash=v2["hash"]))["upgrade"] is None
    with pytest.raises(HTTPException, match="not the one"):
        sharing_routes.upgrade_course(course, sharing_routes.Upgrade(hash=v1["hash"]))

    # Importing the newer bundle again brings the offer back on the course already played, instead of a second course.
    data2 = (places["store"] / f"{v2['hash']}.zip").read_bytes()
    again = asyncio.run(sharing_routes.import_course(readers[0], UploadFile(io.BytesIO(data2), filename="v2.zip")))
    assert again["id"] == course
    assert again["upgrade"] == 2
    assert app._course(course)["upgrade"]["number"] == 2
    assert asyncio.run(sharing_routes.import_course(readers[1], UploadFile(io.BytesIO(data2), filename="v2.zip")))["id"] != course

    done = sharing_routes.upgrade_course(course, sharing_routes.Upgrade(hash=v2["hash"]))
    assert done["upgraded"]["kept"] == [lofting["key"]]
    assert done["upgrade"] is None
    assert db.course(course)["source_version"] == v2["hash"]
    assert_upgraded_units(course, mine, a, card, gone)


def _varied_course(title: str) -> dict:
    """A course whose practice unit varies a solved task of an earlier unit, all finished; the unit's card is due far off."""
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    author = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Variant author {uuid.uuid4().hex[:6]}",)).lastrowid
    course = db.create_course(title, author)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Fit", "Loft"], "known": []}])
    loft = db.concepts(course)[1]["id"]
    lesson = db.create_lesson(course, "Loft", "lesson", loft)
    tasks = [db.add_block(lesson, "challenge", markdown, {**challenge.new(), "solved": True})["id"] for markdown in ("Loft two wires.", "Loft three wires.")]
    card = db.add_card(course, loft, "Why loft?", "open", [], "To join.", "", scheduled=True, due="2099-01-01T00:00:00+00:00")
    db.add_block(lesson, "done", "", {})
    unit = db.conn.execute("INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Blades', 'Practice 1', 0, 99, 'practice')", (course,)).lastrowid
    practice = db.create_lesson(course, "Practice 1", "practice", unit)
    assert asyncio.run(practice_tools.pose_challenge(practice, "Loft two other wires.", variant_of=tasks[0])).startswith("shown")
    db.add_block(practice, "done", "", {})
    return {"course": course, "lesson": lesson, "tasks": tasks, "practice": practice, "card": card}


def _version(course: int, places) -> tuple:
    v = bundle.publish(course, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], **places)
    return bundle.unpack((places["store"] / f"{v['hash']}.zip").read_bytes())


def _replay(version: tuple, places) -> int:
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"Variant reader {uuid.uuid4().hex[:6]}",)).lastrowid
    version_hash, manifest, assets = version
    return bundle.install(reader, version_hash, manifest, assets, places["source_dir"])["id"]


def _by_text(course: int) -> dict[str, dict]:
    return {b["markdown"]: b for x in db.rows("SELECT id FROM lessons WHERE course_id = ?", course) for b in db.blocks(x["id"])}


def _far_off(course: int) -> int:
    """The course's card, due in 2099 and scheduled."""
    card = db.row("SELECT id FROM cards WHERE course_id = ?", course)["id"]
    db.conn.execute("UPDATE cards SET due = '2099-01-01T00:00:00+00:00', scheduled = 1 WHERE id = ?", (card,))
    return card


def _missed(course: int) -> list[tuple]:
    """The variant given up and revealed; the misses in the notebook then."""
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    variant = _by_text(course)["Loft two other wires."]
    db.set_block_data(variant["id"], {**variant["data"], "attempts": ["no"], "gave_up": True})
    assert asyncio.run(practice_tools.reveal(variant["id"], "Like this.")) == "shown"
    assert db.block(variant["id"])["data"]["solution"] == "Like this."
    return [(e["kind"], e["said"], e["correct"]) for e in db.errors(db.course(course)["profile_id"], course)]


MISS = [("practice", "no", "Like this.")]


def _left_as_the_old_code_did(course: int, original: int) -> None:
    variant = _by_text(course)["Loft two other wires."]
    db.set_block_data(variant["id"], {**variant["data"], "variant_of": original})


@pytest.mark.parametrize("made", ["replay", "copy"])
def test_a_variant_in_another_course_names_that_courses_own_task(places, made):
    from wise_scholar.tools import practice as practice_tools

    a = _varied_course(f"Varied {made}")
    mine = _replay(_version(a["course"], places), places) if made == "replay" else db.copy_course(a["course"], "Varied again")["id"]
    card, got = _far_off(mine), _by_text(mine)
    assert _missed(mine) == MISS
    assert (db.card(a["card"])["due"][:4], db.card(card)["due"] < "2099") == ("2099", True)
    assert got["Loft two other wires."]["data"]["variant_of"] == got["Loft two wires."]["id"]
    assert practice_tools.varied(mine) == {got["Loft two wires."]["id"]}


@pytest.mark.parametrize("made", ["replay", "copy"])
@pytest.mark.parametrize("gone", [False, True])
def test_a_variant_left_naming_another_courses_task_never_reaches_it(places, made, gone):
    from wise_scholar.tools import practice as practice_tools

    a = _varied_course(f"Foreign {made} {gone}")
    mine = _replay(_version(a["course"], places), places) if made == "replay" else db.copy_course(a["course"], "Foreign again")["id"]
    _left_as_the_old_code_did(mine, a["tasks"][0])
    if gone:
        db.delete_course(a["course"])
    card = _far_off(mine)
    assert _missed(mine) == MISS
    assert gone or db.card(a["card"])["due"][:4] == "2099"
    assert db.card(card)["due"][:4] == "2099"
    assert practice_tools.varied(mine) == set()


def test_a_task_deleted_from_the_course_keeps_its_variants_reveal_and_miss(places):
    a = _varied_course("Deleted original")
    db.delete_block(a["tasks"][0])
    assert _missed(a["course"]) == MISS
    assert "variant_of" not in _by_text(db.copy_course(a["course"], "Deleted original again")["id"])["Loft two other wires."]["data"]
    assert "variant_of" not in _by_text(_replay(_version(a["course"], places), places))["Loft two other wires."]["data"]


@pytest.mark.parametrize("named", ["number", "unknown key", "odd"])
def test_a_bundle_that_names_no_task_it_holds_installs_without_the_variant(places, named):
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    a = _varied_course(f"Old bundle {named}")
    version_hash, manifest, assets = _version(a["course"], places)
    first = db.row("SELECT MAX(id) AS n FROM blocks")["n"] + 1  # the ids the install will give, so the number is one of the reader's
    variant = next(b for x in manifest.lessons for b in x.blocks if b.markdown == "Loft two other wires.")
    variant.data["variant_of"] = {"number": first + 1, "unknown key": "f" * 32, "odd": {"a": 1}}[named]
    mine = _replay((version_hash, manifest, assets), places)
    got = _by_text(mine)
    three = got["Loft three wires."]
    assert three["id"] == first + 1
    db.set_block_data(three["id"], {**three["data"], "solved": True})
    practice = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'practice'", mine)["id"]
    posed = asyncio.run(practice_tools.pose_challenge(practice, "Loft three others.", variant_of=three["id"]))
    assert posed.startswith("shown"), posed
    assert "variant_of" not in got["Loft two other wires."]["data"]


def test_an_upgrade_points_variants_at_the_tasks_the_course_has_then(places):
    a = _varied_course("Varied upgrade")
    first = _version(a["course"], places)
    mine = _replay(first, places)

    def upgraded(old):
        new = _version(a["course"], places)
        plan = bundle.upgrade(mine, *new, old[1], places["source_dir"])
        return new, [db.row("SELECT title FROM concepts WHERE key = ? AND course_id = ?", k, mine)["title"] for k in plan["kept"]]

    def original():
        got = _by_text(mine)
        return got["Loft two other wires."]["data"].get("variant_of"), got.get("Loft two wires.", {}).get("id")

    # the task's unit is taught again, the variant's kept
    db.add_block(a["lesson"], "prose", "More on lofting.")
    second, kept = upgraded(first)
    assert kept == ["Fit", "Practice 1"] and original()[0] == original()[1] is not None
    # the variant's unit is taught again, the task's kept
    db.add_block(a["practice"], "prose", "More practice.")
    third, kept = upgraded(second)
    assert kept == ["Fit", "Loft"] and original()[0] == original()[1] is not None
    # the task is gone
    db.delete_block(a["tasks"][0])
    upgraded(third)
    assert original() == (None, None)


def _twice_varied(title: str) -> dict:
    """_varied_course with a second variant and a prose block: what a made-up bundle may name as an original."""
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    a = _varied_course(title)
    db.add_block(a["lesson"], "prose", "On wires.")
    assert asyncio.run(practice_tools.pose_challenge(a["practice"], "Loft three others.", variant_of=a["tasks"][1])).startswith("shown")
    return a


@pytest.mark.parametrize("named", ["itself", "prose", "milestone", "transfer", "a variant", "a variant after it", "a variant by number", "each other"])
def test_a_variant_naming_what_no_practice_could_vary_installs_without_it(places, named):
    from wise_scholar.tools import practice as practice_tools

    a = _twice_varied(f"Made up {named}")
    version_hash, manifest, assets = _version(a["course"], places)
    blocks = {b.markdown: b for x in manifest.lessons for b in x.blocks}
    first, second, two, three = (blocks[m] for m in ("Loft two other wires.", "Loft three others.", "Loft two wires.", "Loft three wires."))
    second.data["variant_of"] = {"itself": second, "prose": blocks["On wires."], "milestone": three, "transfer": three}.get(named, first).key
    if named in ("milestone", "transfer"):
        three.data[named] = True
    if named == "a variant by number":
        first.data["variant_of"] = 7
    if named == "each other":
        first.data["variant_of"] = second.key
    if named == "a variant after it":
        practice = next(x for x in manifest.lessons if x.phase == "practice")
        practice.blocks.reverse()
    mine = _replay((version_hash, manifest, assets), places)
    got = _by_text(mine)
    assert "variant_of" not in got["Loft three others."]["data"]
    kept = named not in ("a variant by number", "each other")
    assert practice_tools.varied(mine) == ({got["Loft two wires."]["id"]} if kept else set())
    assert ("variant_of" in got["Loft two other wires."]["data"]) is kept


def test_an_upgrade_drops_a_kept_variant_whose_task_became_a_milestone(places):
    a = _varied_course("Varied milestone")
    first = _version(a["course"], places)
    mine = _replay(first, places)
    task = db.block(a["tasks"][0])
    db.set_block_data(task["id"], {**task["data"], "milestone": True})
    plan = bundle.upgrade(mine, *_version(a["course"], places), first[1], places["source_dir"])
    assert len(plan["restarted"]) == 1 and len(plan["kept"]) == 2
    assert "variant_of" not in _by_text(mine)["Loft two other wires."]["data"]


@pytest.mark.parametrize("ahead", [1, 10**9])
def test_an_upgrade_drops_a_kept_variants_number_that_names_no_block_of_the_course(places, ahead):
    from wise_scholar.tools import practice as practice_tools

    a = _varied_course(f"Stray number {ahead}")
    first = _version(a["course"], places)
    mine = _replay(first, places)
    db.add_block(a["lesson"], "prose", "More on lofting.")
    new = _version(a["course"], places)
    stray = db.row("SELECT MAX(id) AS n FROM blocks")["n"] + ahead  # one ahead is the id the upgrade's first block takes
    _left_as_the_old_code_did(mine, stray)
    plan = bundle.upgrade(mine, *new, first[1], places["source_dir"])
    assert len(plan["kept"]) == 2
    assert ahead != 1 or db.block(stray)["markdown"] == "Loft two wires."
    assert "variant_of" not in _by_text(mine)["Loft two other wires."]["data"]
    assert practice_tools.varied(mine) == set()


def test_an_upgrade_between_versions_that_name_a_variants_task_by_number_drops_it(places, monkeypatch):
    a = _varied_course("Numbered versions")
    now = bundle._block_data
    with monkeypatch.context() as old:
        old.setattr(bundle, "_block_data", lambda block, *args: now(block, *args) and {
            **now(block, *args), **({"variant_of": a["tasks"][0]} if "variant_of" in json.loads(block["data"]) else {})})
        first = _version(a["course"], places)
        db.add_block(a["lesson"], "prose", "More on lofting.")
        second = _version(a["course"], places)
    mine = _replay(first, places)
    _left_as_the_old_code_did(mine, a["tasks"][0])  # an install of then stored the number
    assert len(bundle.upgrade(mine, *second, first[1], places["source_dir"])["kept"]) == 2
    assert "variant_of" not in _by_text(mine)["Loft two other wires."]["data"]
    # the first version with keys restarts the practice unit, which then names the course's own task
    plan = bundle.upgrade(mine, *_version(a["course"], places), second[1], places["source_dir"])
    assert len(plan["restarted"]) == 1
    got = _by_text(mine)
    assert got["Loft two other wires."]["data"]["variant_of"] == got["Loft two wires."]["id"]


def test_a_version_names_a_varied_task_by_its_key_out_of_reach_of_edits(places):
    a = _varied_course("Varied edits")
    key = db.block(a["tasks"][0])["key"]
    manifest, assets, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    variant = next(b for x in manifest["lessons"] for b in x["blocks"] if b["markdown"] == "Loft two other wires.")
    assert variant["data"]["variant_of"] == key
    assert key not in bundle.texts(manifest, assets)["block", variant["key"]]
    assert bundle.apply_edit(manifest, assets, {"target": "block", "ref": variant["key"], "old": "o", "new": "0"})
    assert (variant["markdown"], variant["data"]["variant_of"]) == ("L0ft tw0 0ther wires.", key)
    copy = db.copy_course(a["course"], "Varied edits again")["id"]
    again, _, _ = bundle.build(copy, notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    plain, _, _ = bundle.build(a["course"], notes="", licence="CC-BY-4.0", forkable=True, sources=[], source_dir=places["source_dir"])
    assert [u["hash"] for u in again["units"]] == [u["hash"] for u in plain["units"]]
