import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import crafted, db, figures, obsidian, tutor  # noqa: E402

EXAMPLE, LIVING = [part.split("```")[0].strip() for part in crafted.help_text().split("```js")[1:3]]
node = pytest.mark.skipif(not crafted.available(), reason="no sandbox or no node on this machine")
STAGES = """import * as k from "./kit/iso-kit.mjs";
const base = { x: 0, y: 0, w: 60, d: 40, r: 4 };
const P = k.fitProjection(k.boxCorners(base, 0, 40), 300, 200, { pad: 20 });
const at = (z) => k.figureSvg({ width: 300, height: 200, label: `a block at ${z}`, body: [
  k.solidSvg(k.slabOf(base, 0, 4, P), { tone: "lo" }),
  k.solidSvg(k.cylinder(30, 20, 8, z, 10, P, 16), { tone: "hi", lit: true }),
] });
export default [at(4), at(20), at(30)];
"""
SOFT = """import * as k from "./kit/iso-kit.mjs";
import * as G from "./kit/lathe.mjs";
import { blobOf, blobSvg, membraneOf, membraneSvg } from "./kit/blob.mjs";
const ring = (r, z, n = 10) => Array.from({ length: n }, (_, i) => [r * (1 + 0.1 * Math.sin(i)) * Math.cos((i / n) * 2 * Math.PI), r * Math.sin((i / n) * 2 * Math.PI), z]);
const P = k.fitProjection(ring(40, 0), 300, 200, { pad: 20 });
export default k.figureSvg({ width: 300, height: 200, label: "a cell", body: [
  membraneSvg(membraneOf(ring(40, 0), ring(34, 0), P, { tone: "mid" })),
  blobSvg(blobOf(ring(12, 2), P, { tone: "hi", id: "nucleus" })),
  k.solidSvg(G.sphereOf([20, 10, 4], 4, P), { tone: "mid" }),
] });
"""


def test_the_help_carries_the_kit_contract_and_the_example_imports_the_kit():
    text = crafted.help_text()
    assert "./kit/iso-kit.mjs" in text and "figureSvg" in text and "export default" in EXAMPLE
    assert all(f"`{tone}`" in text for tone in ("hi", "mid", "lo", "faint", "lit", "accent", "warm", "alert"))
    css = (crafted.KIT / "iso.css").read_text()
    assert all(f"[data-tone='{tone}']" in css for tone in ("accent", "warm", "alert")) and "--anatomy-" not in css
    assert sorted(p.name for p in crafted.KIT.glob("*.mjs")) == ["blob.mjs", "iso-kit.mjs", "lathe.mjs", "tube.mjs"]
    assert not any("--anatomy-" in p.read_text() for p in crafted.KIT.glob("*.mjs"))
    assert "Never give a thing parts it does not have" in text and "import { tubePieces, tubeSvg }" in LIVING


def test_a_long_script_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(ValueError, match="over 30000 characters"):
        asyncio.run(crafted.render("x" * 30_001, tmp_path))


def test_standalone_inlines_the_style_with_the_light_theme_values():
    out = crafted.standalone('<svg class="iso-svg" viewBox="0 0 1 1"><g class="iso-solid"/></svg>')
    assert out.startswith('<svg class="iso-svg" viewBox="0 0 1 1"><style>') and "</style><g" in out
    assert "var(--panel)" not in out and "#ffffff" in out and "var(--pulse-at, 0ms)" in out


@node
def test_the_example_script_renders_a_shaded_figure_that_the_sanitiser_keeps(tmp_path):
    (svg,) = asyncio.run(crafted.render(EXAMPLE, tmp_path))
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" class="iso-svg"') and svg.count('class="iso-solid"') == 7
    clean = figures.clean(svg, limit=crafted.MAX_SVG)
    assert 'class="iso-solid"' in clean and 'data-tone="faint"' in clean and "data-lit" in clean and 'aria-label="A knob' in clean
    (living,) = asyncio.run(crafted.render(LIVING, tmp_path))
    assert living.count('class="tb"') >= 16 and "iso-solid" not in living
    assert 'class="tb-body"' in figures.clean(living, limit=crafted.MAX_SVG)
    (soft,) = asyncio.run(crafted.render(SOFT, tmp_path))
    clean = figures.clean(soft, limit=crafted.MAX_SVG)
    assert all(mark in clean for mark in ('id="nucleus" class="bio-blob"', 'class="bio-membrane"', 'class="iso-solid" data-seamless', 'class="bio-blob-highlight"'))
    with pytest.raises(ValueError, match=r"(?s)did not run: .*Error: boom"):
        asyncio.run(crafted.render('throw new Error("boom")', tmp_path))
    with pytest.raises(ValueError, match="draws nothing from the kit"):
        asyncio.run(crafted.render('export default "<svg viewBox=\\"0 0 1 1\\"></svg>"', tmp_path))
    with pytest.raises(ValueError, match="did not run: it exported nothing"):
        asyncio.run(crafted.render("process.exit(0)", tmp_path))


@node
def test_a_mounted_folder_is_the_command_s_to_write_and_comes_back_to_the_server(tmp_path):
    from wise_scholar import sandbox

    out, course = tmp_path / "out", tmp_path / "course"
    out.mkdir()
    course.mkdir()
    where = "/run/out" if sandbox.SANDBOX else str(out)
    result = asyncio.run(sandbox.run(f"echo made > {where}/file && cat {where}/file", course, mounts=((str(out), "/run/out"),)))
    assert result["exit_code"] == 0 and result["output"].strip() == "made" and (out / "file").read_text() == "made\n"


@node
def test_the_tool_keeps_the_script_and_the_export_styles_the_figure():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Craft')").lastrowid
    try:
        course = db.create_course("Mechanics", who)["id"]
        lesson = db.create_lesson(course, "A knob", "lesson", None)
        assert asyncio.run(tutor.add_crafted_figure(lesson, EXAMPLE, "c", "")) == "error: alt text is required"
        assert asyncio.run(tutor.add_crafted_figure(lesson, "nonsense(", "c", "a")).startswith("error: the script did not run: ")
        reply = asyncio.run(tutor.add_crafted_figure(lesson, EXAMPLE, "A knob on a post.", "a post with a knob on a base plate"))
        block = db.blocks(lesson)[-1]
        assert reply == f"shown as figure {block['id']}" and block["data"]["crafted"] == {"script": EXAMPLE}
        assert block["data"]["svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg" class="iso-svg"')
        vault = obsidian.Vault(course)
        vault._block_text(db.lesson(lesson), block)
        exported = next(data for path, data in vault.files.items() if path.endswith(f"figure-{block['id']}.svg"))
        assert exported.startswith(b'<svg xmlns="http://www.w3.org/2000/svg" class="iso-svg"') and b"<style>" in exported and b"#ffffff" in exported
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


@node
def test_stages_become_one_crossfaded_animation_with_their_frames_kept(tmp_path):
    stages = asyncio.run(crafted.render(STAGES, tmp_path))
    assert len(stages) == 3 and all(s.startswith("<svg") and "iso-solid" in s for s in stages)
    svg = figures.clean(crafted.animate(stages), limit=crafted.MAX_SVG * 3)
    assert 'data-stages="3"' in svg and 'data-seconds="9"' in svg and svg.count('<animate attributeName="opacity"') == 3
    assert 'values="1;1;0;0" keyTimes="0.000;0.378;0.379;1.000" dur="9s" repeatCount="indefinite"' in svg
    assert 'values="0;0;1;1;0;0" keyTimes="0.000;0.333;0.378;0.711;0.712;1.000"' in svg
    assert 'values="0;0;1;1" keyTimes="0.000;0.667;0.711;1.000"' in svg and svg.count("<g opacity=") == 3
    one = asyncio.run(crafted.render(STAGES.replace("[at(4), at(20), at(30)]", "[at(4)]"), tmp_path))
    assert len(one) == 1
    with pytest.raises(ValueError, match="not a whole <svg>"):
        asyncio.run(crafted.render(STAGES.replace("[at(4), at(20), at(30)]", "['<!-- x -->' + at(4), at(20)]"), tmp_path))
    with pytest.raises(ValueError, match="2 to 6 stages; the script exported 7"):
        asyncio.run(crafted.render(STAGES.replace("[at(4), at(20), at(30)]", "[4, 5, 6, 7, 8, 9, 10].map(at)"), tmp_path))
    with pytest.raises(ValueError, match="differ in size"):
        asyncio.run(crafted.render(STAGES.replace("at(30)]", "at(30).replace('0 0 300 200', '0 0 300 201')]"), tmp_path))


@node
def test_a_figure_is_redrawn_in_place_as_an_animation_and_the_old_drawing_is_kept():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Recraft')").lastrowid
    try:
        course = db.create_course("Mechanics", who)["id"]
        lesson = db.create_lesson(course, "A press", "lesson", None)
        asyncio.run(tutor.add_figure(lesson, '<svg viewBox="0 0 10 10"><rect width="4" height="4"/></svg>', "Flat.", "a square"))
        old = db.blocks(lesson)[-1]
        assert asyncio.run(tutor.replace_crafted_figure(lesson, old["id"] + 1000, STAGES, "c", "a")) == f"error: no figure with id {old['id'] + 1000} in this lesson"
        assert asyncio.run(tutor.replace_crafted_figure(lesson, old["id"], STAGES, "The press closes.", "a block lifting in three steps")) == f"figure {old['id']} redrawn, animated over 3 stages"
        block = db.block(old["id"])
        assert block["markdown"] == "The press closes." and len(block["data"]["frames"]) == 3 and 'data-stages="3"' in block["data"]["svg"]
        assert block["data"]["crafted"] == {"script": STAGES} and block["data"]["previous"]["svg"] == old["data"]["svg"] and block["data"]["previous"]["caption"] == "Flat."
        reply = asyncio.run(tutor.add_crafted_figure(lesson, STAGES, "c", "a"))
        assert reply == f"shown as figure {db.blocks(lesson)[-1]['id']}, animated over 3 stages"
        assert asyncio.run(tutor.replace_crafted_figure(lesson, old["id"], EXAMPLE, "Still.", "a knob")) == f"figure {old['id']} redrawn"
        block = db.block(old["id"])
        assert "frames" not in block["data"] and len(block["data"]["previous"]["frames"]) == 3 and "previous" not in block["data"]["previous"]
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))
