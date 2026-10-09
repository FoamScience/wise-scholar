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
        assert block["data"]["svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg"') and 'viewBox="' in block["data"]["svg"] and "<title>" not in block["data"]["svg"]
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


STAGES = [
    "MeiosisMetaphaseI K\nChromosome c1, c2, d1, d2\nIn(c1, K)\nIn(c2, K)\nIn(d1, K)\nIn(d2, K)\nPaternal(c1)\nMaternal(c2)\nPaternal(d1)\nMaternal(d2)\n"
    'Short(d1)\nShort(d2)\nHomologous(c1, c2)\nHomologous(d1, d2)\nLabel K "Metaphase I"',
]
STAGES += [STAGES[0].replace("MeiosisMetaphaseI K", "MeiosisAnaphaseI K").replace("Metaphase I", "Anaphase I")]
STAGES += [STAGES[0].replace("MeiosisMetaphaseI K", "MeiosisLateAnaphaseI K").replace("Metaphase I", "Late anaphase I")]


def test_an_animation_needs_two_to_six_stages():
    with pytest.raises(ValueError, match="2 to 6 stages"):
        diagrams.animate("cells", STAGES[:1])
    with pytest.raises(ValueError, match="2 to 6 stages"):
        diagrams.animate("cells", STAGES * 3)


@sidecar
def test_stages_become_one_animated_figure_with_its_frames_kept_for_print():
    import re

    from wise_scholar import figures, obsidian

    svg, frames = diagrams.animate("cells", STAGES)
    assert len(frames) == 3 and all(f.startswith("<svg") and "<title>" not in f and "<animate" not in f for f in frames)
    assert svg.count("<animate ") >= 10 and 'data-stages="3"' in svg and 'data-seconds="9"' in svg and "<title>" not in svg
    assert 'attributeName="x"' in svg and 'keyTimes="0.000;0.100;0.333;0.433;0.667;0.767;1"' in svg
    assert "Metaphase I" in svg and "Anaphase I" in svg and "Late anaphase I" in svg  # the label switches
    assert "<animate" in figures.clean(svg)  # SMIL passes the allowlist, so the stored figure still moves
    # The frames glide: every animated x moves by less than half the canvas between consecutive stages.
    for values in re.findall(r'attributeName="x" values="([^"]+)"', svg):
        numbers = [float(v) for v in values.split(";")]
        assert all(abs(a - b) < 450 for a, b in zip(numbers, numbers[1:]))

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Anim')").lastrowid
    try:
        course = db.create_course("Meiosis", who)["id"]
        lesson = db.create_lesson(course, "Anaphase", "lesson", None)
        reply = asyncio.run(tutor.add_animation(lesson, "cells", STAGES, "Meiosis I unfolds.", "a cell from metaphase I to late anaphase I"))
        block = db.blocks(lesson)[-1]
        assert reply == f"shown as figure {block['id']}, animated over 3 stages"
        assert block["data"]["diagram"] == {"domain": "cells", "stages": STAGES} and len(block["data"]["frames"]) == 3
        assert "<animate" in block["data"]["svg"] and "<animate" not in block["data"]["frames"][0]
        vault = obsidian.Vault(course)
        note = "".join(vault.lesson_text(db.lesson(lesson) | {"blocks": db.blocks(lesson), "messages": []}, chat=False, kinds=("figure",)))
        assert note.count("![[") == 3 and f"attachments/figure-{block['id']}-3.svg" in note
        assert sum(1 for p in vault.files if f"figure-{block['id']}-" in p) == 3
        assert asyncio.run(tutor.add_animation(lesson, "cells", STAGES[:1], "c", "a")) == "error: an animation has 2 to 6 stages"
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))
