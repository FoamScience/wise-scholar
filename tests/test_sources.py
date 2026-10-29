import os
import tempfile
from pathlib import Path

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, search, sources  # noqa: E402


def test_files_become_searchable_sections_read_one_at_a_time(tmp_path: Path):
    md = tmp_path / "notes.md"
    md.write_text("# Ownership\n\nEach value has one owner. " * 3 + "\n\n# Borrowing\n\n" + "A reference borrows. " * 400 + "\n\n# Lifetimes\n\nShort.")
    cut = sources.sections(sources.extract(md), md.name)
    titles = [t for t, _ in cut]
    assert titles[0] == "notes.md · Ownership" and titles[1].startswith("notes.md · Borrowing · part 1") and titles[-1] == "notes.md · Lifetimes"
    assert all(len(text) <= sources.SECTION_CHARS for _, text in cut)

    import pymupdf

    pdf = tmp_path / "book.pdf"
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"Chapter {i + 1}: the borrow checker rejects dangling references.")
    doc.save(pdf)
    pages = sources.extract(pdf)
    assert len(pages) == 2 and "borrow checker" in pages[0][1]

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Src')").lastrowid
    course = db.create_course("Rust", who)["id"]
    source = db.add_source(course, "notes.md", md.stat().st_size)
    assert source["status"] == "processing"
    done = db.finish_source(source["id"], cut)
    assert done["status"] == "ready" and done["sections"] == len(cut)
    hits = search.search(course, "borrows", 3, ("source",))
    assert hits and hits[0]["title"].startswith("notes.md · Borrowing") and f"{search.MARK[0]}borrows{search.MARK[1]}" in hits[0]["snippet"]
    assert search.search(course, "dangling", 3, ("source",)) == []
    section = db.source_section(int(hits[0]["ref"]))
    assert section["course_id"] == course and "A reference borrows." in section["text"]
    db.delete_source(source["id"])
    assert search.search(course, "borrows", 3, ("source",)) == [] and db.sources(course) == []

    failed = db.finish_source(db.add_source(course, "x.bin", 1)["id"], [], "unsupported")
    assert failed["status"] == "failed" and failed["error"] == "unsupported"
    assert db.finish_source(999_999, cut) is None
    code = tmp_path / "tool.py"
    code.write_text("# a comment\nx = 1\n# another\ny = 2\n")
    assert len(sources.sections(sources.extract(code), code.name)) == 1
    assert sources.html_text("<p>a</p></script><p>b</p>") .strip() != "a"


def test_a_course_search_finds_its_cards_chats_and_code_and_follows_their_changes(monkeypatch, tmp_path: Path):
    import asyncio

    from wise_scholar import app, tutor

    monkeypatch.setattr(db, "WORKSPACE", tmp_path)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Finder')").lastrowid
    course = db.create_course("Geometry kernels", who)
    concept = db.conn.execute("INSERT INTO concepts (course_id, module, title) VALUES (?, 'Shapes', 'Faces')", (course["id"],)).lastrowid
    lesson = db.create_lesson(course["id"], "Faces", "lesson", concept)
    card = db.add_block(lesson, "prose", "A face orientation tells which side of the surface is outside.")
    chat = db.add_message(lesson, "learner", "why does the explorer visit a corner twice")
    (tmp_path / course["slug"] / "faces").mkdir(parents=True)
    (tmp_path / course["slug"] / "faces" / "orient.py").write_text("def outward(face):\n    return face.Orientation() == 0\n")
    for hidden in ("tools/fc", ".venv/lib"):
        (tmp_path / course["slug"] / hidden).mkdir(parents=True)
        (tmp_path / course["slug"] / hidden / "outward.py").write_text("outward = 1\n")

    hits = search.search(course["id"], "orientation outside", 5)
    assert hits[0]["kind"] == "card" and hits[0]["ref"] == str(card["id"]) and hits[0]["concept_id"] == concept
    assert [h["ref"] for h in search.search(course["id"], "outward", 5)] == ["faces/orient.py:1-2"]
    found = asyncio.run(tutor.search_course(course["id"], "explorer corner"))
    assert found.startswith(f"chat {chat['id']} · Faces · learner: why does the [explorer] visit a [corner]")
    assert "nothing found" in asyncio.run(tutor.search_course(course["id"], "lattice"))
    assert app.search_course(course["id"], "explorer")[0]["snippet"][1] == ("explorer", True)

    db.conn.execute("UPDATE messages SET text = 'a lattice of points' WHERE id = ?", (chat["id"],))
    db.delete_block(card["id"])
    (tmp_path / course["slug"] / "faces" / "orient.py").unlink()
    assert search.search(course["id"], "orientation outward explorer", 5) == []
    assert search.search(course["id"], "lattice", 5)[0]["ref"] == str(chat["id"])
    db.delete_course(course["id"])
    assert db.rows("SELECT id FROM passages WHERE course_id = ?", course["id"]) == []


def test_without_model2vec_a_search_goes_by_words_and_vectors_come_once_it_is_installed(monkeypatch):
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Words only')").lastrowid
    course = db.create_course("Shells", who)
    lesson = db.create_lesson(course["id"], "Shells", "lesson")
    db.add_message(lesson, "tutor", "The outer shell holds the valence electrons.")
    monkeypatch.setattr(search, "available", lambda: False)
    assert [h["kind"] for h in search.search(course["id"], "valence", 3)] == ["chat"]
    assert search.search(course["id"], "outermost electron layer", 3) == []
    assert db.row("SELECT vector FROM passages WHERE course_id = ?", course["id"])["vector"] is None
    monkeypatch.setattr(search, "available", lambda: True)
    assert search.search(course["id"], "shell electrons", 3)[0]["kind"] == "chat"
    assert db.row("SELECT vector FROM passages WHERE course_id = ?", course["id"])["vector"] is not None
