import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, diagrams, tutor  # noqa: E402

EXAMPLE = diagrams.help_text("cells").split("```")[1].strip()
sidecar = pytest.mark.skipif(not diagrams.available(), reason="diagrams/node_modules not installed")


def test_domains_come_with_notes_and_an_example():
    assert "cells" in diagrams.domains()
    assert diagrams.summary("cells") == "Cells at a phase of mitosis or meiosis, drawn with their chromosomes."
    assert "predicate Homologous(Chromosome, Chromosome)" in diagrams.help_text("cells") and "MitosisMetaphase M" in EXAMPLE
    assert asyncio.run(tutor.diagram_help("nope")).startswith("error: no diagram domain named 'nope'; the domains are cells")
    with pytest.raises(ValueError, match="no diagram domain named 'nope'"):
        diagrams.render("nope", "Cell k")


def test_render_refuses_what_cannot_run(monkeypatch):
    with pytest.raises(ValueError, match="over 3000 characters"):
        diagrams.render("cells", "Chromosome " + "x, " * 1500)
    monkeypatch.setattr(diagrams, "SIDECAR", diagrams.SIDECAR / "missing")
    with pytest.raises(ValueError, match="diagrams are not installed"):
        diagrams.render("cells", "Cell k")


def test_a_sidecar_that_cannot_start_or_answer_is_an_error_for_the_tutor(monkeypatch):
    import subprocess

    monkeypatch.setattr(diagrams, "available", lambda: True)
    monkeypatch.setattr(diagrams.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("node")))
    with pytest.raises(ValueError, match="cannot start"):
        diagrams.render("cells", "Cell k")
    monkeypatch.setattr(diagrams.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("node", 60)))
    with pytest.raises(ValueError, match="took over 60 seconds"):
        diagrams.render("cells", "Cell k")

    class Run:
        returncode, stdout, stderr = 1, "warning: something\n", "boom"

    monkeypatch.setattr(diagrams.subprocess, "run", lambda *a, **k: Run())
    with pytest.raises(ValueError, match="renderer failed"):
        diagrams.render("cells", "Cell k")
    assert asyncio.run(tutor.add_diagram(10**9, "cells", "Cell k", "c", "a")) == "error: no lesson with id 1000000000"


@sidecar
def test_the_example_lays_out_and_becomes_a_figure_block():
    svg = diagrams.render("cells", EXAMPLE)
    assert svg.startswith("<svg") and "<penrose" not in svg and 'viewBox="' in svg and svg.count("<circle") >= 10
    assert "Mitosis: metaphase" in svg and "Meiosis: metaphase I" in svg

    # The profile goes again at the end: other test modules count the profiles of this shared test database.
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Diag')").lastrowid
    try:
        course = db.create_course("Meiosis", who)["id"]
        lesson = db.create_lesson(course, "Metaphase", "lesson", None)
        reply = asyncio.run(tutor.add_diagram(lesson, "cells", EXAMPLE, "Mitosis beside meiosis I.", "two cells with four chromosomes each"))
        block = db.blocks(lesson)[-1]
        assert reply == f"shown as figure {block['id']}" and block["kind"] == "figure"
        assert block["data"]["diagram"] == {"domain": "cells", "substance": EXAMPLE} and block["data"]["credits"] == []
        assert block["data"]["svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg"') and 'viewBox="' in block["data"]["svg"] and "<title>" in block["data"]["svg"]
        assert asyncio.run(tutor.add_diagram(lesson, "cells", EXAMPLE, "c", "")) == "error: alt text is required"
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


@sidecar
def test_a_wrong_substance_is_a_compile_error_and_an_impossible_one_names_the_broken_rules():
    with pytest.raises(ValueError, match="does not exist"):
        diagrams.render("cells", "MitosisMetaphase M\nIn(a, M)")
    with pytest.raises(ValueError, match="not match"):
        diagrams.render("cells", "MitosisMetaphase M\nChromosome a\nHomologous(a, M)")
    crowded = "MitosisMetaphase M\nChromosome " + ", ".join(f"c{i}" for i in range(9)) + "\n" + "\n".join(f"In(c{i}, M)" for i in range(9))
    with pytest.raises(ValueError) as refused:
        diagrams.render("cells", crowded)
    message = str(refused.value)
    assert message.startswith("could not lay the diagram out:") and "the rules:" in message and "ensure " in message and "State fewer objects" in message


@sidecar
def test_one_cell_is_cropped_to_its_content_and_pairs_may_be_stated_either_way_round():
    one = (
        "MeiosisMetaphaseI K\nChromosome c1, c2\nIn(c1, K)\nIn(c2, K)\nMaternal(c1)\nPaternal(c2)\nHomologous(c1, c2)\n"
        'Label K "الاستوائية I"'
    )
    svg = diagrams.render("cells", one)
    _, _, width, _ = svg.split('viewBox="')[1].split('"')[0].split()
    assert float(width) < 500 and "الاستوائية I" in svg
