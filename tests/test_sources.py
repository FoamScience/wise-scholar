import os
import tempfile
from pathlib import Path

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, sources  # noqa: E402


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
    hits = db.search_sources(course, "borrows", 3)
    assert hits and hits[0]["title"].startswith("notes.md · Borrowing") and "[borrows]" in hits[0]["snippet"]
    assert db.search_sources(course, "dangling", 3) == []
    section = db.source_section(hits[0]["id"])
    assert section["course_id"] == course and section["text"].startswith("A reference borrows.")
    db.delete_source(source["id"])
    assert db.search_sources(course, "borrows", 3) == [] and db.sources(course) == []

    failed = db.finish_source(db.add_source(course, "x.bin", 1)["id"], [], "unsupported")
    assert failed["status"] == "failed" and failed["error"] == "unsupported"
    assert db.finish_source(999_999, cut) is None
    code = tmp_path / "tool.py"
    code.write_text("# a comment\nx = 1\n# another\ny = 2\n")
    assert len(sources.sections(sources.extract(code), code.name)) == 1
    assert sources.html_text("<p>a</p></script><p>b</p>") .strip() != "a"
