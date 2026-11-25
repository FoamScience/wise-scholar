import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figures  # noqa: E402

TEACHES = figures.Teaches(claim="Parts have a place.", notice="Where each part sits.")


def test_book_export_reports_a_missing_course_and_a_missing_install(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar.routes import sharing as sharing_routes

    with pytest.raises(HTTPException) as missing:
        asyncio.run(sharing_routes.course_book(10**9))
    assert missing.value.status_code == 404

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Booker')").lastrowid
    course = db.create_course("Bookbinding", who)["id"]
    monkeypatch.setattr(sharing_routes.book, "available", lambda: False)
    with pytest.raises(HTTPException) as uninstalled:
        asyncio.run(sharing_routes.course_book(course))
    assert uninstalled.value.status_code == 503 and "make pdf" in uninstalled.value.detail

    async def no_browser(*_):
        raise sharing_routes.book.NoBrowser

    monkeypatch.setattr(sharing_routes.book, "available", lambda: True)
    monkeypatch.setattr(sharing_routes.book, "render", no_browser)
    with pytest.raises(HTTPException) as browserless:
        asyncio.run(sharing_routes.course_book(course))
    assert browserless.value.status_code == 503


def test_a_task_carries_the_knowledge_it_needs_folded_under_it_and_into_the_export():
    import asyncio

    from wise_scholar import obsidian
    from wise_scholar.tools import practice as practice_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Helped')").lastrowid
    course = db.create_course("Lean", who)["id"]
    lesson = db.create_lesson(course, "Equality", "lesson")
    helper = "`h.symm` turns `h : a = b` into a proof of `b = a`."
    assert asyncio.run(practice_tools.pose_challenge(lesson, "Given h : a = b, prove b = a.", helper=f"  {helper}\n")).startswith("shown as challenge")
    task = db.blocks(lesson)[-1]
    assert task["data"]["helper"] == helper
    note = obsidian.Vault(course)._card_body(db.lesson(lesson), task)
    assert "> [!info]- What you need to know" in note and helper in note
    asyncio.run(practice_tools.pose_challenge(lesson, "Prove a = a."))
    plain = db.blocks(lesson)[-1]
    assert plain["data"]["helper"] == "" and "What you need to know" not in obsidian.Vault(course)._card_body(db.lesson(lesson), plain)

# Obsidian export: seeds profiles, so it lives here with the other profile-creating tests.


def seed_vault(name: str) -> tuple[int, int]:
    """A small course with every kind of note; returns the course and its plot block."""
    import asyncio

    from wise_scholar import quiz
    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools, quizzes as quiz_tools, visuals as visual_tools

    who = db.conn.execute("INSERT INTO profiles (name, locale) VALUES (?, 'en')", (name,)).lastrowid
    course = db.create_course("Chemistry: bonds & shells", who)["id"]
    db.conn.execute("UPDATE courses SET details = 'second year', hours = 20, level = 'beginner', placement = 'Knows atoms.' WHERE id = ?", (course,))
    db.set_concepts(course, [
        {"title": "Atoms", "concepts": ["Electrons", "Bonds"], "known": ["Electrons"]},
        {"title": "Reactions", "concepts": ["Acids/Bases?", "Acids/Bases?"], "known": []},
    ])
    units = db.concepts(course)
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    db.add_block(interview, "question", "Why chemistry?", {"options": ["fun", "work"], "answer": "fun"})
    db.add_message(interview, "tutor", "Welcome.")
    lesson = db.create_lesson(course, "Bonds", "lesson", units[1]["id"])
    db.add_message(lesson, "learner", "ready")
    asyncio.run(practice_tools.pose_challenge(lesson, "Predict: do two H atoms bond? [note] #tag", pretest=True))
    pretest = db.blocks(lesson)[-1]
    db.set_block_data(pretest["id"], {**pretest["data"], "attempts": ["yes"], "hints": ["think of shells"], "solved": True})
    asyncio.run(flow_tools.add_block(lesson, "prose", "Atoms share electrons."))
    asyncio.run(visual_tools.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A pair", "two atoms", TEACHES))
    asyncio.run(quiz_tools.pose_quiz(lesson, "How many bonds does carbon form?", "choice", "4", "Four valence electrons.", options=["4", "2"]))
    q = db.blocks(lesson)[-1]
    card = db.card(q["data"]["card_id"])
    answer_id = quiz.submit(card, "2", 0.9)
    result = quiz.grade(answer_id, False)
    db.set_block_data(q["id"], {**q["data"], "answer": "2", "confidence": 0.9, "answer_id": answer_id, **result})
    asyncio.run(flow_tools.finish_lesson(lesson, "You can now count bonds."))
    db.add_capstone(course, "Atoms", "Model kit", "Build a molecule model.", "kit", [(units[1]["id"], "a water model")])
    plot = db.add_block(lesson, "plot", "Bond energies", {"spec": {"marks": []}, "alt": "bars"})
    return course, plot["id"]


def assert_vault_files(names: set[str], root: str):
    assert f"{root}/Chemistry bonds & shells.md" in names
    assert f"{root}/Interview.md" in names
    assert f"{root}/Modules/Atoms.md" in names
    assert f"{root}/Units/Electrons.md" in names
    assert f"{root}/Lessons/1 Bonds.md" in names
    assert f"{root}/Projects/Model kit.md" in names
    assert f"{root}/Course map.canvas" in names
    assert any(n.startswith(f"{root}/Mistakes/") for n in names)
    assert any(n.startswith(f"{root}/attachments/figure-") for n in names)
    # Two units with the same title get distinct files.
    assert len([n for n in names if n.startswith(f"{root}/Units/Acids Bases")]) == 2


def assert_notes_resolve(z, names: set[str]):
    import re

    for name in names:
        if not name.endswith(".md"):
            continue
        text = z.read(name).decode()
        assert text.startswith("---\n")
        assert "\ntype: " in text.split("---")[1]
        for target in re.findall(r"\[\[([^\]|#]+)", text):
            assert target + ".md" in names or target in names, (name, target)


def assert_unit_and_card_notes(z, names: set[str], root: str):
    unit = z.read(f"{root}/Units/Bonds.md").decode()
    assert "mastery: 0.0" in unit
    assert 'builds_on: "[[' in unit
    assert "#flashcards" in unit
    assert "How many bonds does carbon form?\n- " in unit
    assert "\n?\n4\n" in unit
    card = next(n for n in names if "/Cards/" in n and "carbon" in n)
    text = z.read(card).decode()
    assert "correct: false" in text
    assert "confident_miss: true" in text
    assert "**Your answer** · 90% sure: 2" in text
    assert "[[" + root + "/Mistakes/" in text


def assert_lesson_and_map_notes(z, root: str, course: int):
    import json

    lesson = z.read(f"{root}/Lessons/1 Bonds.md").decode()
    assert lesson.count("![[") >= 4
    assert "> [!quote]- Tutor" not in lesson
    assert "> [!quote] You\n> ready" in lesson
    assert f"![[{root}/attachments/plot-" in lesson
    assert "[!success] Unit covered" in lesson
    canvas = json.loads(z.read(f"{root}/Course map.canvas"))
    assert {n["type"] for n in canvas["nodes"]} == {"text", "file"}
    assert len(canvas["edges"]) == len(db.concepts(course)) + 1
    electrons = z.read(f"{root}/Units/Electrons.md").decode()
    assert "known: true" in electrons
    assert "placed out" in electrons


def test_export_is_a_vault_folder_whose_links_all_resolve():
    import io
    import zipfile

    from wise_scholar import obsidian

    course, plot = seed_vault("Vault")
    z = zipfile.ZipFile(io.BytesIO(obsidian.export(course, {plot: b"png"})))
    names = set(z.namelist())
    root = "Wise Scholar/Chemistry bonds & shells"
    assert_vault_files(names, root)
    assert_notes_resolve(z, names)
    assert_unit_and_card_notes(z, names, root)
    assert_lesson_and_map_notes(z, root, course)


def test_export_writes_the_courses_claims_as_linked_notes():
    import io
    import re
    import zipfile

    from wise_scholar import obsidian

    course, _ = seed_vault("Vault claims")
    who = db.course(course)["profile_id"]
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ? AND phase = 'lesson'", course)["id"]
    check = next(b for b in db.blocks(lesson) if b["kind"] == "quiz")
    elsewhere = db.create_course("Physics", who)["id"]
    other = db.create_lesson(elsewhere, "Forces", "lesson")
    ids = db.record_claims(who, lesson, [
        {"key": "a", "text": "Carbon forms four bonds.", "evidence": [check["id"]]},
        {"key": "b", "text": "Bonds share electron pairs.", "evidence": []},
    ], [("b", "a", "follows")])  # fmt: skip
    far = db.record_claims(who, other, [{"key": "f", "text": "Forces add as vectors.", "evidence": []}], [])["f"]
    db.conn.execute("INSERT INTO claim_edges (from_id, to_id, kind) VALUES (?, ?, 'contrasts')", (ids["b"], far))

    z = zipfile.ZipFile(io.BytesIO(obsidian.export(course, {})))
    names = set(z.namelist())
    vault = obsidian.Vault(course)
    root = vault.root
    carbon = z.read(f"{root}/Claims/Carbon forms four bonds.md").decode()
    assert 'type: "claim"' in carbon and 'state: "shaky"' in carbon and "*shaky*" in carbon
    assert f"**Follows from**\n- [[{root}/Claims/Bonds share electron pairs]]" in carbon and "**Checked by**\n- [[" in carbon and " · wrong" in carbon
    pairs = z.read(f"{root}/Claims/Bonds share electron pairs.md").decode()
    assert "**Looks like but differs from**\n- Forces add as vectors. (Physics)" in pairs
    assert not any("Forces add" in n for n in names)
    assert "## Claims" in z.read(f"{root}/Units/Bonds.md").decode() and "## Claims" in z.read(vault.names[("course",)] + ".md").decode()
    for name in (n for n in names if n.endswith(".md")):
        for target in re.findall(r"\[\[([^\]|#]+)", z.read(name).decode()):
            assert target + ".md" in names or target in names, (name, target)
    assert obsidian.Vault(course, inline=True).claims == []


def test_vault_endpoint_serves_a_zip_without_a_browser(monkeypatch):
    import asyncio
    import io
    import zipfile

    from wise_scholar.routes import sharing as sharing_routes

    course, _ = seed_vault("Vault 2")
    monkeypatch.setattr(sharing_routes.book, "available", lambda: False)
    sent = asyncio.run(sharing_routes.course_vault(course))
    assert sent.media_type == "application/zip" and zipfile.ZipFile(io.BytesIO(sent.body)).testzip() is None
    plot = [n for n in zipfile.ZipFile(io.BytesIO(sent.body)).namelist() if "plot-" in n]
    assert plot == []


def test_vault_folder_is_kept_current_and_never_touches_the_learners_own_notes(tmp_path):
    import json

    from wise_scholar import obsidian, vault

    course, _ = seed_vault("Vault 3")
    folder = vault.write(course, tmp_path)
    manifest = json.loads((folder / vault.MANIFEST).read_text())
    assert folder == tmp_path / obsidian.Vault(course).root and all((tmp_path / p).exists() for p in manifest)
    own = folder / "My notes.md"
    own.write_text("[[Units/Bonds]] matters")
    unit = next(p for p in manifest if "/Units/Bonds" in p)
    lesson = db.rows("SELECT id FROM lessons WHERE course_id = ? ORDER BY id DESC", course)[0]["id"]
    db.add_block(lesson, "prose", "Later addition.", {})
    db.conn.execute("UPDATE concepts SET title = 'Covalent bonds' WHERE course_id = ? AND title = 'Bonds'", (course,))
    vault.write(course, tmp_path)
    after = json.loads((folder / vault.MANIFEST).read_text())
    assert not (tmp_path / unit).exists() and any("/Units/Covalent bonds" in p for p in after)
    assert "Later addition." in (tmp_path / next(p for p in after if "/Lessons/" in p)).read_text()
    assert own.read_text() == "[[Units/Bonds]] matters"
    # A renamed course moves to a new folder and leaves none behind.
    db.conn.execute("UPDATE courses SET topic = 'Chemistry renamed' WHERE id = ?", (course,))
    moved = vault.write(course, tmp_path)
    assert moved != folder and not (folder / vault.MANIFEST).exists() and not (folder / "Units").exists() and own.exists()
    vault.remove(course, tmp_path)
    assert own.exists() and not (moved / vault.MANIFEST).exists() and not (moved / "Units").exists()


def test_vault_follows_published_changes_from_any_thread(tmp_path, monkeypatch):
    import asyncio
    import threading

    from wise_scholar import hub, obsidian, vault

    course, _ = seed_vault("Vault 4")
    monkeypatch.setattr(vault, "VAULT", tmp_path)
    monkeypatch.setattr(vault, "SETTLE", 0.2)
    monkeypatch.setattr(hub, "_listeners", [])
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]

    async def scenario():
        await vault.start()
        for i in range(3):
            db.add_block(lesson, "prose", f"change {i}", {})
            threading.Thread(target=hub.publish, args=(course, {"type": "block.added"})).start()
            await asyncio.sleep(0.05)
        for _ in range(50):
            await asyncio.sleep(0.1)
            note = tmp_path / obsidian.Vault(course).root / "Interview.md"
            if note.exists() and "change 2" in note.read_text() and not vault._pending:
                return True
        return False

    assert asyncio.run(scenario())


def test_two_courses_with_one_title_get_two_vault_folders():
    from wise_scholar import obsidian

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Twin')").lastrowid
    first = db.create_course("Chemistry: bonds & shells", who)["id"]
    second = db.create_course("chemistry bonds & shells", who)["id"]
    assert obsidian.Vault(first).root != obsidian.Vault(second).root and obsidian.Vault(second).root.endswith(f"({second})")


# A card's key stays out of a learner's vault until they answered the card.


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    """Workspaces, sources and published versions land in the test's folder; turns are not run."""
    from wise_scholar import app

    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources")
    monkeypatch.setattr(app, "VERSIONS", tmp_path / "versions")
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False, then=None: None)
    return tmp_path


def keyed_course(name: str, mode: str = "learner", batch: bool = False) -> tuple[int, dict[str, int]]:
    """A finished unit with a check of each kind, none answered; returns the course and its blocks by question."""
    import asyncio

    from wise_scholar.tools import quizzes

    who = db.conn.execute("INSERT INTO profiles (name, mode, locale) VALUES (?, ?, 'en')", (name, mode)).lastrowid
    course = db.create_course(name, who)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Loft"], "known": []}])
    lesson = db.create_lesson(course, "Loft", "lesson", db.concepts(course)[0]["id"])
    db.conn.execute("UPDATE lessons SET batch = ? WHERE id = ?", (int(batch), lesson))
    items = [quizzes.SortItem(text=f"item {n}", category=("even", "odd")[n % 2]) for n in range(6)]
    for reply in (
        asyncio.run(quizzes.pose_quiz(lesson, "Which call lofts?", "choice", "ThruSections", "SECRET why.", ["ThruSections", "MakePipe"])),
        asyncio.run(quizzes.pose_quiz(lesson, "Why sections?", "open", "SECRET model.", "SECRET because.")),
        asyncio.run(quizzes.pose_sort(lesson, "Sort them.", ["even", "odd"], items, "SECRET tells apart.")),
    ):
        assert reply.startswith("shown as quiz")
    db.add_block(lesson, "done", "", {})
    return course, checks(course)


def replayed(course: int, shelf) -> int:
    """The course published and imported through the routes by a new reader."""
    import asyncio
    import io

    from fastapi import UploadFile

    from wise_scholar.routes import sharing as sharing_routes

    v = sharing_routes.publish_version(course, sharing_routes.Publish())
    reader = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"{db.course(course)['topic']} reader",)).lastrowid
    data = (shelf / "versions" / f"{v['hash']}.zip").read_bytes()
    return asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(data), filename="x.zip")))["id"]


def checks(course: int) -> dict[str, int]:
    return {b["markdown"]: b["id"] for l in db.rows("SELECT id FROM lessons WHERE course_id = ?", course) for b in db.blocks(l["id"]) if b["kind"] == "quiz"}


def answer(block: int, text: str) -> None:
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes

    asyncio.run(blocks_routes.answer_quiz(block, app.QuizAnswer(answer=text, confidence=0.4)))


def exported(course: int) -> dict[str, str]:
    """The notes of the downloaded vault, by their path inside the course's folder."""
    import io
    import zipfile

    from wise_scholar import obsidian

    root = obsidian.Vault(course).root
    with zipfile.ZipFile(io.BytesIO(obsidian.export(course))) as z:
        return {n.removeprefix(f"{root}/"): z.read(n).decode() for n in z.namelist() if n.endswith(".md")}


def everything(notes: dict[str, str]) -> str:
    return "\n".join(notes.values())


def sort_note(notes: dict[str, str]) -> str:
    return next(text for path, text in notes.items() if path.startswith("Cards/") and "Sort them" in path)


def flashcards(notes: dict[str, str]) -> list[str]:
    """The first line of each card in the unit note's flashcards, the section that ends it."""
    unit = notes["Units/Loft.md"]
    return [card.split("\n")[0] for card in unit.split("\n#flashcards\n", 1)[1].strip().split("\n\n")] if "\n#flashcards\n" in unit else []


def keyless(notes: dict[str, str]) -> bool:
    text = everything(notes)
    return not any(key in text for key in ("SECRET", "**ThruSections**", "item 0 → ", "\n?\nThruSections"))


def card_of(block: int) -> int:
    return db.block(block)["data"]["card_id"]


@pytest.mark.parametrize("reader", ["learner", "replay"])
def test_a_readers_vault_gives_no_key_of_a_card_they_have_not_answered(reader, shelf):
    import json

    course, blocks = keyed_course(f"Vault keys of a {reader}")
    if reader == "replay":
        course = replayed(course, shelf)
        blocks = checks(course)
    notes = exported(course)
    assert keyless(notes) and flashcards(notes) == []
    sort = sort_note(notes)
    assert all(f"- item {n}\n" in sort for n in range(6)) and "**even · odd**" in sort and "*not answered*" in sort

    answer(blocks["Which call lofts?"], "MakePipe")
    notes = exported(course)
    assert flashcards(notes) == ["Which call lofts?"] and "Which call lofts?\n- " in notes["Units/Loft.md"] and "\n?\nThruSections\n" in notes["Units/Loft.md"]
    assert "SECRET model." not in everything(notes) and "item 0 → " not in everything(notes)

    answer(blocks["Why sections?"], "no idea")
    notes = exported(course)
    assert flashcards(notes) == ["Which call lofts?", "Why sections?"] and "Why sections?\n?\nSECRET model.\n" in notes["Units/Loft.md"]

    answer(blocks["Sort them."], json.dumps({f"item {n}": "odd" for n in range(6)}))
    notes = exported(course)
    assert "item 0 → even" in notes["Units/Loft.md"] and "item 1 → odd" in notes["Units/Loft.md"]
    assert "- item 0 → odd ✗" in sort_note(notes) and "item 0 → even" not in sort_note(notes)


def test_a_card_is_met_once_answered_or_saved_from_a_reading_not_by_coming_due(shelf):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from wise_scholar import quiz
    from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes

    course, blocks = keyed_course("Vault cards met")
    unit = db.concepts(course)[0]
    lesson = db.block(blocks["Sort them."])["lesson_id"]
    db.conn.execute("UPDATE courses SET lang = 'de' WHERE id = ?", (course,))
    reading = db.add_block(lesson, "reading", "Das Brot ist frisch.", {"title": "Brot", "lang": "de", "glossary": [{"word": "Brot", "meaning": "bread"}], "added": []})
    asyncio.run(blocks_routes.add_vocabulary(reading["id"], blocks_routes.Word(word="Brot")))
    [saved] = db.rows("SELECT id, concept_id, vocab, due, question FROM cards WHERE course_id = ? AND lemma IS NOT NULL", course)
    assert (saved["concept_id"], saved["vocab"], bool(saved["due"])) == (unit["id"], 1, True)
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=1)).isoformat()
    card = lambda question, **k: db.add_card(course, unit["id"], question, "open", [], "key", "", scheduled=True, **k)  # noqa: E731
    card("word of the course", vocab=True)
    correction = card("correction", due=past)
    card("due later", due=(now + timedelta(days=9)).isoformat())
    quiz.submit(db.card(card("answered, not graded yet")), "mine", 0.5)
    again = card("reviewed")
    quiz.grade(quiz.submit(db.card(again), "mine", 0.5), True)
    skipped = card("did not know")
    placement = db.create_lesson(course, "Placement", "placement")
    db.add_block(placement, "quiz", "did not know", {"card_id": skipped, "kind": "open", "options": [], "answer": "I don't know", "unknown": True, "correct": False})
    db.add_block(db.create_lesson(course, "Loft again", "lesson", unit["id"]), "quiz", "did not know", {"card_id": skipped, "kind": "open", "options": [], "answer": None})
    due = [card_of(b) for b in blocks.values()]
    db.conn.execute(f"UPDATE cards SET due = ? WHERE id IN ({','.join('?' * len(due))})", (past, *due))
    assert {db.card(c)["kind"] for c in due} == {"choice", "open", "sort"}

    met = [saved["question"].split("\n")[0], "answered, not graded yet", "reviewed", "did not know"]
    notes = exported(course)
    assert flashcards(notes) == met and "\n?\nbread" in notes["Units/Loft.md"] and keyless(notes)
    learner_routes.review_card(correction, learner_routes.ReviewAnswer(answer="mine"))
    learner_routes.review_card(card_of(blocks["Which call lofts?"]), learner_routes.ReviewAnswer(answer="MakePipe"))
    assert flashcards(exported(course)) == ["Which call lofts?", met[0], "correction", *met[1:]]


def test_a_missed_practice_variant_brings_its_units_cards_due_and_no_key_into_the_vault(shelf):
    import asyncio

    from wise_scholar import challenge
    from wise_scholar.tools import practice as practice_tools

    course, blocks = keyed_course("Vault keys of a missed variant")
    lesson = db.block(blocks["Sort them."])["lesson_id"]
    task = db.add_block(lesson, "challenge", "Loft two wires.", {**challenge.new(), "solved": True})["id"]
    practice = db.conn.execute("INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Blades', 'Practice 1', 0, 99, 'practice')", (course,)).lastrowid
    practiced = db.create_lesson(course, "Practice 1", "practice", practice)
    assert asyncio.run(practice_tools.pose_challenge(practiced, "Loft two other wires.", variant_of=task)).startswith("shown")
    variant = db.blocks(practiced)[-1]
    db.set_block_data(variant["id"], {**variant["data"], "attempts": ["no"], "gave_up": True})
    assert asyncio.run(practice_tools.reveal(variant["id"], "Like this.")) == "shown"
    assert all(db.card(card_of(b))["due"] for b in blocks.values())
    notes = exported(course)
    assert flashcards(notes) == [] and keyless(notes) and "Like this." in everything(notes)


@pytest.mark.parametrize("reader", ["learner", "replay"])
def test_a_unit_taken_offline_shows_a_key_only_once_its_check_is_answered(reader, shelf):
    import asyncio

    from wise_scholar.tools import quizzes

    course, blocks = keyed_course(f"Vault keys offline for a {reader}", batch=reader == "learner")
    if reader == "replay":
        course = replayed(course, shelf)
        lesson = db.block(checks(course)["Sort them."])["lesson_id"]
        db.conn.execute("UPDATE lessons SET batch = 1 WHERE id = ?", (lesson,))
        assert asyncio.run(quizzes.pose_quiz(lesson, "Why wires?", "open", "SECRET offline key.", "SECRET as written.")).startswith("shown")
        blocks = checks(course)
    open_check = "Why sections?" if reader == "learner" else "Why wires?"
    assert db.block(blocks[open_check])["data"]["answer_key"].startswith("SECRET")
    notes = exported(course)
    assert keyless(notes) and flashcards(notes) == [] and "*not answered*" in sort_note(notes)
    answer(blocks["Which call lofts?"], "ThruSections")
    notes = exported(course)
    assert flashcards(notes) == ["Which call lofts?"] and "**ThruSections**" in everything(notes) and "SECRET why." in everything(notes)
    assert not any(key in everything(notes) for key in ("SECRET model.", "SECRET offline key.", "SECRET because.", "SECRET as written.", "SECRET tells", "item 0 → "))


def test_a_copy_of_an_answered_course_holds_no_key_in_its_vault(shelf):
    import json

    course, blocks = keyed_course("Vault keys of a copied course")
    for question, text in (("Which call lofts?", "MakePipe"), ("Why sections?", "no idea"), ("Sort them.", json.dumps({"item 0": "odd"}))):
        answer(blocks[question], text)
    assert "SECRET model." in everything(exported(course)) and len(flashcards(exported(course))) == 3
    copy = db.copy_course(course, "Vault keys of a copied course again")["id"]
    notes = exported(copy)
    assert keyless(notes) and flashcards(notes) == [] and "*not answered*" in sort_note(notes)


def test_a_learners_lesson_printed_with_solutions_holds_only_the_keys_they_answered(shelf):
    from wise_scholar import obsidian

    course, blocks = keyed_course("Vault keys inline", batch=True)
    lesson = db.block(blocks["Sort them."])["lesson_id"]

    def printed() -> str:
        vault = obsidian.Vault(course, inline=True, solutions=True)
        return "\n".join(vault.lesson_text(next(x for x in vault.lessons if x["id"] == lesson), chat=False))

    text = printed()
    assert "SECRET" not in text and "**ThruSections**" not in text and "item 0 → " not in text and text.count("*not answered*") == 3
    answer(blocks["Which call lofts?"], "ThruSections")
    text = printed()
    assert "**ThruSections**" in text and "SECRET why." in text and "SECRET model." not in text and "item 0 → " not in text


def test_a_vault_folder_note_that_held_keys_is_rewritten_without_them_and_no_file_goes(tmp_path):
    import json

    from wise_scholar import vault

    # a prepared course's notes hold its keys; the same course as a learner's holds none
    course, _ = keyed_course("Vault keys in a folder", mode="teacher")
    db.add_card(course, db.concepts(course)[0]["id"], "Cue?", "open", [], "SECRET cue.", "", scheduled=True)

    def written() -> dict[str, str]:
        folder = vault.write(course, tmp_path)
        return {p: (tmp_path / p).read_text() for p in json.loads((folder / vault.MANIFEST).read_text())}

    before = written()
    assert "SECRET model." in everything(before) and "item 0 → even" in sort_note({p.split("/", 2)[2]: t for p, t in before.items()})
    assert "SECRET cue." in next(t for p, t in before.items() if p.endswith("Units/Loft.md"))
    unit = next(p for p in before if p.endswith("Units/Loft.md"))
    own = (tmp_path / unit).with_name("My cards.md")
    own.write_text(before[unit])
    db.conn.execute("UPDATE courses SET mode = 'learner' WHERE id = ?", (course,))
    after = written()
    assert after.keys() == before.keys() and own.read_text() == before[unit]
    assert "SECRET" not in everything(after) and "item 0 → " not in everything(after)
