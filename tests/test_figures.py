import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import figures  # noqa: E402

CELL = (
    '<svg viewBox="0 0 300 200" width="300" height="200"><ellipse cx="150" cy="100" rx="130" ry="80" fill="#e1f0ee" stroke="#0b5f5a"/>'
    '<circle cx="150" cy="100" r="30" fill="#fbebd3" stroke="#6b3a00"/><text x="150" y="104" text-anchor="middle" fill="currentColor">Nucleus</text>'
    '<defs><marker id="arrow"><path d="M0,0 L4,2 L0,4z"/></marker></defs><line x1="20" y1="20" x2="60" y2="60" stroke="currentColor" marker-end="url(#arrow)"/></svg>'
)


def test_clean_keeps_shapes_text_and_local_references_and_drops_the_rest():
    out = figures.clean(CELL)
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">') and 'width="300"' not in out
    assert "Nucleus" in out and 'marker-end="url(#arrow)"' in out and "<marker" in out
    stripped = figures.clean(
        '<svg viewBox="0 0 1 1" style="background:url(http://e/x)" xmlns:h="http://www.w3.org/1999/xhtml"><image href="http://x/y.png"/>'
        '<foreignObject><div/></foreignObject><a href="http://x"><rect/></a><rect fill="URL(http://evil)"/><use href="#m"/>'
        '<style>body{display:none}</style><h:style>x</h:style></svg>'
    )
    assert stripped == '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect /><use href="#m" /></svg>'


@pytest.mark.parametrize(
    "svg, reason",
    [
        ('<svg viewBox="0 0 1 1"><script>alert(1)</script></svg>', "scripts"),
        ('<svg viewBox="0 0 1 1"><SCRIPT/></svg>', "scripts"),
        ('<svg viewBox="0 0 1 1"><rect onload="x()"/></svg>', "event"),
        ('<svg viewBox="0 0 1 1" onload="x()"/>', "event"),
        ('<svg viewBox="0 0 1 1">' + "<g>" * 100 + "</g>" * 100 + "</svg>", "nests"),
        ('<svg><rect/></svg>', "viewBox"),
        ("<div/>", "root element"),
        ('<svg viewBox="0 0 1 1"><rect></svg>', "well-formed"),
        ('<!DOCTYPE svg [<!ENTITY x "y">]><svg viewBox="0 0 1 1"/>', "well-formed"),
    ],
)
def test_clean_refuses_with_a_reason(svg, reason):
    with pytest.raises(ValueError, match=reason):
        figures.clean(svg)


def test_ids_are_prefixed_per_figure_and_label_text_is_untouched():
    out = figures.prefix_ids('<svg><marker id="m"/><use href="#m"/><rect fill="url(#g)"/></svg>', "f7-")
    assert out == '<svg><marker id="f7-m"/><use href="#f7-m"/><rect fill="url(#f7-g)"/></svg>'
    assert "Set on=1 ok" in figures.clean('<svg viewBox="0 0 1 1"><text x="1" y="1">Set on=1 ok</text></svg>')
