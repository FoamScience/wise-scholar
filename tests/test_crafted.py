import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import crafted, db, figures, obsidian, tutor  # noqa: E402

EXAMPLE = crafted.help_text().split("```js")[1].split("```")[0].strip()
node = pytest.mark.skipif(not crafted.available(), reason="no sandbox or no node on this machine")


def test_the_help_carries_the_kit_contract_and_the_example_imports_the_kit():
    text = crafted.help_text()
    assert "./kit/iso-kit.mjs" in text and "figureSvg" in text and "export default" in EXAMPLE
    assert all(f"`{tone}`" in text for tone in ("hi", "mid", "lo", "faint", "lit", "accent", "warm", "alert"))
    css = (crafted.KIT / "iso.css").read_text()
    assert all(f"[data-tone='{tone}']" in css for tone in ("accent", "warm", "alert")) and "--anatomy-" not in css
    assert "--anatomy-" not in (crafted.KIT / "iso-kit.mjs").read_text()


def test_a_long_script_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(ValueError, match="over 30000 characters"):
        asyncio.run(crafted.render("x" * 30_001, tmp_path))


def test_standalone_inlines_the_style_with_the_light_theme_values():
    out = crafted.standalone('<svg class="iso-svg" viewBox="0 0 1 1"><g class="iso-solid"/></svg>')
    assert out.startswith('<svg class="iso-svg" viewBox="0 0 1 1"><style>') and "</style><g" in out
    assert "var(--panel)" not in out and "#ffffff" in out and "var(--pulse-at, 0ms)" in out


@node
def test_the_example_script_renders_a_shaded_figure_that_the_sanitiser_keeps(tmp_path):
    svg = asyncio.run(crafted.render(EXAMPLE, tmp_path))
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" class="iso-svg"') and svg.count('class="iso-solid"') == 7
    clean = figures.clean(svg, limit=crafted.MAX_SVG)
    assert 'class="iso-solid"' in clean and 'data-tone="faint"' in clean and "data-lit" in clean and 'aria-label="A knob' in clean
    with pytest.raises(ValueError, match=r"(?s)did not run: .*Error: boom"):
        asyncio.run(crafted.render('throw new Error("boom")', tmp_path))
    with pytest.raises(ValueError, match="no solid"):
        asyncio.run(crafted.render('export default "<svg/>"', tmp_path))
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
