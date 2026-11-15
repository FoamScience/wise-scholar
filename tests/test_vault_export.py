import os
import tempfile

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
