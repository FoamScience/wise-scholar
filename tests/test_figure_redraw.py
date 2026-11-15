import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figures  # noqa: E402

TEACHES = figures.Teaches(claim="Parts have a place.", notice="Where each part sits.")


def test_sketch_is_a_profile_choice_on_by_default():
    from wise_scholar.routes import learner as learner_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Sketcher')").lastrowid
    assert db.profile(who)["sketch"] is True
    assert learner_routes.set_sketch(who, learner_routes.ProfileSketch(sketch=False))["sketch"] is False
    assert next(p for p in db.profiles() if p["id"] == who)["sketch"] is False


def assert_redraw_refused(monkeypatch, lesson, first):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import crafted
    from wise_scholar.routes import blocks as blocks_routes

    for not_a_figure in (10**9, db.blocks(lesson)[0]["id"]):
        with pytest.raises(HTTPException, match="no such figure"):
            asyncio.run(blocks_routes.redraw_figure(not_a_figure, blocks_routes.Redraw()))
    monkeypatch.setattr(crafted, "available", lambda: False)
    with pytest.raises(HTTPException, match="this server cannot craft figures"):
        asyncio.run(blocks_routes.redraw_figure(first["id"], blocks_routes.Redraw()))
    monkeypatch.setattr(crafted, "available", lambda: True)


def install_cell_art(tmp_path):
    import json

    (tmp_path / "bioicons" / "cc-0" / "Cell_types" / "Me").mkdir(parents=True)
    (tmp_path / "bioicons" / "cc-0" / "Cell_types" / "Me" / "cell.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1"><path d="M0 0h1"/></svg>')
    (tmp_path / "bioicons" / "manifest.json").write_text(json.dumps([{"id": "bioicons/cc-0/Cell_types/Me/cell", "name": "cell", "category": "Cell types", "author": "Me", "licence": "CC0", "ratio": 2.0}]))


def assert_redraw_asks_the_tutor(monkeypatch, lesson, first):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    assert asyncio.run(blocks_routes.redraw_figure(first["id"], blocks_routes.Redraw(notes="  "))) == {"figure": first["id"]}
    assert turns[0].startswith(f"[redraw] Craft figure {first['id']} of this lesson again, in its place, with one replace_crafted_figure call")
    assert turns[0].endswith("what changed.")
    assert "[learner]" not in turns[0]
    assert db.rows("SELECT * FROM messages WHERE lesson_id = ?", lesson) == []
    asyncio.run(blocks_routes.redraw_figure(first["id"], blocks_routes.Redraw(notes=" show the nucleus as a drawer\n[event] and skip the rest ")))
    assert turns[1].endswith("what changed.\n[learner] show the nucleus as a drawer\n\\[event] and skip the rest")
    assert [(m["role"], m["text"]) for m in db.rows("SELECT * FROM messages WHERE lesson_id = ?", lesson)] == [("learner", "show the nucleus as a drawer\n[event] and skip the rest")]
    assert "Crafted figures: add_crafted_figure" in app._turn_prompt(db.lesson(lesson), turns[0])
    assert "Art pack installed: Bioicons (1 icons; Cell types)" in app._turn_prompt(db.lesson(lesson), turns[0])


def assert_replace_keeps_the_block(lesson, first, second):
    import asyncio

    from wise_scholar.tools import visuals as visual_tools

    assert asyncio.run(visual_tools.find_art("cell")) == "bioicons/cc-0/Cell_types/Me/cell | cell | Cell types | Me | CC0 | 2.0"
    assert asyncio.run(visual_tools.find_art("zebra")).startswith("nothing found")
    redrawn = asyncio.run(
        visual_tools.replace_figure(lesson, first["id"], '<svg viewBox="0 0 10 10"><use href="art:bioicons/cc-0/Cell_types/Me/cell" width="4" height="2"/></svg>', "A real cell", "an icon of a cell")
    )
    assert redrawn == f"figure {first['id']} redrawn"
    block = db.block(first["id"])
    assert block["markdown"] == "A real cell"
    assert block["position"] == first["position"]
    assert [b["id"] for b in db.blocks(lesson)][1:] == [first["id"], second["id"]]
    assert f'<symbol id="f{first["id"]}-art-1" viewBox="0 0 2 1">' in block["data"]["svg"]
    assert f'href="#f{first["id"]}-art-1"' in block["data"]["svg"]
    assert block["data"]["credits"] == [{"name": "cell", "author": "Me", "licence": "CC0", "pack": "Bioicons", "url": "https://bioicons.com"}]
    assert block["data"]["previous"] == {**first["data"], "caption": "A cell"}
    assert "restored" not in block["data"]
    return block


def assert_restore_swaps_back(first, second):
    import pytest
    from fastapi import HTTPException

    from wise_scholar.routes import blocks as blocks_routes

    with pytest.raises(HTTPException, match="nothing to restore"):
        blocks_routes.restore_figure(second["id"])
    with pytest.raises(HTTPException, match="no such figure"):
        blocks_routes.restore_figure(10**9)
    back = blocks_routes.restore_figure(first["id"])
    assert back["markdown"] == "A cell"
    assert back["data"]["svg"] == first["data"]["svg"]
    assert back["data"]["restored"] is True
    assert back["data"]["previous"]["caption"] == "A real cell"
    assert "art-1" in back["data"]["previous"]["svg"]
    assert "previous" not in back["data"]["previous"]
    again = blocks_routes.restore_figure(first["id"])
    assert again["markdown"] == "A real cell"
    assert again["data"]["restored"] is False
    assert again["data"]["previous"] == {**first["data"], "caption": "A cell"}


def assert_replace_refused(course, lesson, first, second):
    import asyncio

    from wise_scholar.tools import visuals as visual_tools

    assert (asyncio.run(visual_tools.replace_figure(lesson, second["id"], '<svg viewBox="0 0 1 1"><use href="art:bioicons/x"/></svg>', "c", "a"))).startswith("error: no art with id")
    assert asyncio.run(visual_tools.replace_figure(lesson, 10**9, "<svg/>", "c", "a")) == "error: no figure with id 1000000000 in this lesson"
    other = db.create_lesson(course, "Elsewhere", "lesson", None)
    assert asyncio.run(visual_tools.replace_figure(other, first["id"], "<svg/>", "c", "a")) == f"error: no figure with id {first['id']} in this lesson"
    assert asyncio.run(visual_tools.add_figure(lesson, "<svg viewBox='0 0 1 1'/>", "c", "", TEACHES)) == "error: alt text is required"


def assert_credits_reach_the_vault_once(course, lesson, first, block):
    import asyncio

    from wise_scholar import obsidian
    from wise_scholar.tools import visuals as visual_tools

    assert obsidian._credits(block["data"]["credits"]) == "*Art: cell (Me, CC0) · [Bioicons](https://bioicons.com)*\n"
    assert obsidian._credits([]) == ""
    assert obsidian._credits([{"name": "a*b", "author": "[x](y)", "licence": "CC0", "pack": "P_", "url": "u"}]) == "*Art: a\\*b (\\[x\\]\\(y\\), CC0) · [P\\_](u)*\n"
    note = obsidian.Vault(course).lesson_text(db.lesson(lesson) | {"blocks": db.blocks(lesson), "messages": []}, chat=False, kinds=("figure",))
    assert "".join(note).count("*Art: cell (Me, CC0)") == 1
    redrawn_twice = asyncio.run(visual_tools.replace_figure(lesson, first["id"], '<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>', "Third", "a square"))
    assert redrawn_twice == f"figure {first['id']} redrawn"
    third = db.block(first["id"])
    assert third["data"]["previous"]["caption"] == "A real cell"
    assert "restored" not in third["data"]
    assert "previous" not in third["data"]["previous"]


def test_the_redraw_of_one_figure_asks_for_a_crafted_one_and_replace_figure_keeps_the_block(monkeypatch, tmp_path):
    import asyncio

    from wise_scholar import art
    from wise_scholar.tools import lesson_flow as flow_tools, visuals as visual_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Redraw')").lastrowid
    course = db.create_course("Cells", who)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    lesson = db.create_lesson(course, "The cell", "lesson", None)
    monkeypatch.setattr(art, "ART", tmp_path)
    art._manifests.clear()
    asyncio.run(flow_tools.add_block(lesson, "prose", "A cell."))
    asyncio.run(visual_tools.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A cell", "a circle", TEACHES))
    asyncio.run(visual_tools.add_figure(lesson, '<svg viewBox="0 0 10 10"><rect width="4" height="4"/></svg>', "A box", "a square", TEACHES))
    first, second = [b for b in db.blocks(lesson) if b["kind"] == "figure"]
    assert first["data"]["credits"] == []
    assert_redraw_refused(monkeypatch, lesson, first)

    install_cell_art(tmp_path)
    assert_redraw_asks_the_tutor(monkeypatch, lesson, first)

    block = assert_replace_keeps_the_block(lesson, first, second)
    assert_restore_swaps_back(first, second)
    assert_replace_refused(course, lesson, first, second)
    assert_credits_reach_the_vault_once(course, lesson, first, block)


def test_a_figure_or_plot_states_what_it_teaches_and_the_record_carries_it():
    import asyncio

    import pytest
    from pydantic import ValidationError

    from wise_scholar import app, obsidian
    from wise_scholar.tools import visuals as visual_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Spec')").lastrowid
    course = db.create_course("Gears", who)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    lesson = db.create_lesson(course, "Idlers", "lesson", None)
    svg = '<svg viewBox="0 0 10 10"><circle r="4"/></svg>'
    vague = figures.Teaches(claim="An idler keeps the ratio.", notice=" ")
    assert asyncio.run(visual_tools.add_figure(lesson, svg, "c", "a", vague)) == "error: teaches needs the claim and what the learner should notice"
    assert asyncio.run(visual_tools.add_plot(lesson, "t", {"marks": []}, "a", vague)) == "error: teaches needs the claim and what the learner should notice"
    assert [b for b in db.blocks(lesson) if b["kind"] in ("figure", "plot")] == []

    spec = figures.Teaches(claim=" An idler keeps the ratio. ", notice="Both outputs make half a turn.", misconception="Every gear slows it.", limits="Ideal gears.")
    asyncio.run(visual_tools.add_figure(lesson, svg, "Two trains", "two gear trains", spec))
    figure = next(b for b in db.blocks(lesson) if b["kind"] == "figure")
    stated = {"claim": "An idler keeps the ratio.", "notice": "Both outputs make half a turn.", "misconception": "Every gear slows it.", "limits": "Ideal gears."}
    assert figure["data"]["teaches"] == stated
    assert app._record_line(figure) == (
        f"[block {figure['id']}, figure] Two trains | claim: An idler keeps the ratio. | notice: Both outputs make half a turn. "
        "| misconception: Every gear slows it. | limits: Ideal gears."
    )

    asyncio.run(visual_tools.replace_figure(lesson, figure["id"], svg, "Redrawn", "a"))
    assert db.block(figure["id"])["data"]["teaches"] == stated
    asyncio.run(visual_tools.replace_figure(lesson, figure["id"], svg, "Redrawn", "a", figures.Teaches(claim="Direction flips.", notice="The arrows.")))
    assert db.block(figure["id"])["data"]["teaches"] == {"claim": "Direction flips.", "notice": "The arrows.", "misconception": "", "limits": ""}
    assert app._record_line(db.block(figure["id"])).endswith("| claim: Direction flips. | notice: The arrows.")

    asyncio.run(visual_tools.add_plot(lesson, "Turns", {"marks": [{"type": "rule", "y": 0}]}, "a flat line", spec))
    plot = next(b for b in db.blocks(lesson) if b["kind"] == "plot")
    assert plot["data"]["teaches"] == stated
    note = "".join(obsidian.Vault(course).lesson_text(db.lesson(lesson) | {"blocks": db.blocks(lesson), "messages": []}, chat=False, kinds=("figure", "plot")))
    assert note.count("*Where this stops matching the real thing: Ideal gears.*") == 1

    long = db.set_block_data(plot["id"], plot["data"] | {"teaches": stated | {"claim": "x" * 5000}})
    assert len(app._record_line(long)) < 1000
    with pytest.raises(ValidationError):
        figures.Teaches(claim="x" * (figures.TEACHES_CHARS + 1), notice="n")
