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
