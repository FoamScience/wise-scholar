import json
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import art, figures  # noqa: E402

STYLED = """<?xml version="1.0"?>
<!DOCTYPE svg [<!ENTITY ns_svg "http://www.w3.org/2000/svg"><!ENTITY shade "#2a2617">]>
<svg xmlns="&ns_svg;" width="120px" height="60px" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
<style>/* AI export */ .st0, .st1 {fill:#FFFEFE; stroke: #000 !important} .st1{fill:&shade;} g .st2{fill:red}</style>
<defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs>
<g inkscape:label="layer"><path class="st0" d="M0 0h10v10z"/><circle class="st1" style="fill:url(#g);-inkscape-stroke:none" r="4"/>
<rect class="st2" width="1" height="1"/><image href="data:image/png;base64,AAAA"/></g></svg>"""


def test_normalise_turns_styles_into_attributes_expands_entities_and_finds_a_viewbox():
    out = art.normalise(STYLED)
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120.0 60.0">')
    assert '<path d="M0 0h10v10z" fill="#FFFEFE" stroke="#000" />' in out
    assert '<circle r="4" fill="url(#g)" stroke="#000" />' in out  # the inline style wins over the class, the odd property goes
    assert '<rect width="1" height="1" />' in out  # a descendant selector is not applied
    assert "image" not in out and "style" not in out and "inkscape" not in out and "DOCTYPE" not in out


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="x.png"/></svg>',  # raster only
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1"/></svg>',  # no size at all
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>1</script><path d="M0 0h1"/></svg>',
        "<svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="' + "M0 0h1 " * 70_000 + '"/></svg>',
    ],
)
def test_normalise_leaves_out_what_cannot_be_shown(svg):
    assert art.normalise(svg) is None


@pytest.fixture
def pack(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "ART", tmp_path)
    art._manifests.clear()
    icons = {
        "cc-by-3.0/Intracellular_components/Servier/nucleus": '<svg xmlns="http://www.w3.org/2000/svg" id="svg1" viewBox="0 0 40 20"><defs><linearGradient id="g"/></defs><circle id="c" r="9" fill="url(#g)"/></svg>',
        "cc-0/Animals/James-Lloyd/FruitFly": '<svg xmlns="http://www.w3.org/2000/svg" id="svg1" viewBox="0 0 10 10"><defs><linearGradient id="g"/></defs><path d="M0 0h1" fill="url(#g)"/></svg>',
        "cc-by-4.0/Viruses/DBCLS/adeno-virus": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h1"/></svg>',
    }
    manifest = []
    for icon_id, svg in icons.items():
        path = tmp_path / "bioicons" / f"{icon_id}.svg"
        path.parent.mkdir(parents=True)
        path.write_text(svg)
        licence, category, author, name = icon_id.split("/")
        manifest.append({"id": f"bioicons/{icon_id}", "name": name.replace("_", " "), "category": category.replace("_", " "), "author": author.replace("-", " "), "licence": art.LICENCES[licence], "ratio": art._ratio(svg)})
    (tmp_path / "bioicons" / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_search_matches_words_inside_names_and_ranks_names_over_categories(pack):
    assert [i["name"] for i in art.search("virus")[0]] == ["adeno-virus"]
    assert [i["name"] for i in art.search("fly animal")[0]] == ["FruitFly"]
    assert [i["name"] for i in art.search("cell")[0]] == ["nucleus"]  # Intracellular components, by category
    assert art.search("") == ([], False) and art.search("zebra") == ([], False)
    assert art.search("s", limit=2) == ([pack[2] | {"pack": "bioicons"}, pack[0] | {"pack": "bioicons"}], True)  # names first, then by name; FruitFly only by author
    assert art.installed() == [{"pack": "bioicons", "title": "Bioicons", "url": "https://bioicons.com", "icons": 3, "categories": ["Animals", "Intracellular components", "Viruses"]}]


def test_art_is_not_installed_without_a_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "ART", tmp_path / "none")
    art._manifests.clear()
    assert art.installed() == [] and art.search("nucleus") == ([], False)


def test_inline_puts_the_icons_in_as_symbols_and_owes_their_credits(pack):
    drawing = figures.clean(
        '<svg viewBox="0 0 300 200"><use href="art:bioicons/cc-by-3.0/Intracellular_components/Servier/nucleus" x="10" y="10" width="100" height="50"/>'
        '<use href="art:bioicons/cc-by-3.0/Intracellular_components/Servier/nucleus" x="150" y="10" width="100" height="50"/>'
        '<use href="art:bioicons/cc-0/Animals/James-Lloyd/FruitFly" width="20" height="20"/><text x="1" y="1">Nucleus</text></svg>'
    )
    out, credits = art.inline(drawing)
    assert out.count("<symbol") == 2 and '<symbol id="art-1" viewBox="0 0 40 20">' in out and '<symbol id="art-2" viewBox="0 0 10 10">' in out
    assert out.count('href="#art-1"') == 2 and out.count('href="#art-2"') == 1 and "art:" not in out
    assert out.index("<defs>") < out.index("<use")
    # Each icon keeps its own gradient: the two ids called g no longer collide, and the icons' root ids do not rename the symbols.
    assert 'id="art-1-g"' in out and 'fill="url(#art-1-g)"' in out and 'id="art-2-g"' in out and 'fill="url(#art-2-g)"' in out and "svg1" not in out
    assert credits == [
        {"name": "nucleus", "author": "Servier", "licence": "CC BY 3.0", "pack": "Bioicons", "url": "https://bioicons.com"},
        {"name": "FruitFly", "author": "James Lloyd", "licence": "CC0", "pack": "Bioicons", "url": "https://bioicons.com"},
    ]
    prefixed = figures.prefix_ids(out, "f9-")
    assert 'id="f9-art-1"' in prefixed and 'href="#f9-art-1"' in prefixed and 'url(#f9-art-1-g)' in prefixed and 'id="f9-art-2-g"' in prefixed


def test_inline_leaves_a_plain_figure_alone_and_refuses_an_unknown_icon(pack):
    plain = figures.clean('<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>')
    assert art.inline(plain) == (plain, [])
    with pytest.raises(ValueError, match="no art with id 'bioicons/cc-0/x/y/z'"):
        art.inline(figures.clean('<svg viewBox="0 0 1 1"><use href="art:bioicons/cc-0/x/y/z"/></svg>'))
    with pytest.raises(ValueError, match="no art with id"):
        art.inline(figures.clean('<svg viewBox="0 0 1 1"><use href="art:other/x"/></svg>'))


def test_normalise_refuses_a_viewbox_that_is_not_four_numbers():
    assert art.normalise('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10"><path d="M0 0h1"/></svg>') is None
    assert art.normalise('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 0"><path d="M0 0h1"/></svg>') is None
    assert art.normalise('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,10,5"><path d="M0 0h1"/></svg>').startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,10,5">')


def test_fetch_keeps_only_showable_icons_under_allowed_licences_and_replaces_an_old_install(tmp_path, monkeypatch):
    import io
    import zipfile
    from contextlib import contextmanager

    root = art.PACKS["bioicons"]["root"]
    good = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 5"><path d="M0 0h1"/></svg>'
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"{root}cc-0/Animals/Me/fly.svg", good)
        z.writestr(f"{root}cc-by-4.0/Viruses/DBCLS/adeno_virus.svg", good)
        z.writestr(f"{root}cc-by-sa-4.0/Animals/Me/shared.svg", good)  # share-alike: out
        z.writestr(f"{root}cc-0/Animals/Me/raster.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="x.png"/></svg>')
        z.writestr(f"{root}cc-0/Animals/odd.svg", good)  # not licence/category/author/name
        z.writestr(f"{root}icons.json", "[]")
        z.writestr("elsewhere/cc-0/Animals/Me/outside.svg", good)

    @contextmanager
    def stream(method, url, **kwargs):
        assert method == "GET" and url == art.PACKS["bioicons"]["zip"] and kwargs["timeout"] is art.DOWNLOAD_TIMEOUT

        class Response:
            def raise_for_status(self):
                pass

            def iter_bytes(self):
                yield archive.getvalue()

        yield Response()

    monkeypatch.setattr(art, "ART", tmp_path / "art")
    monkeypatch.setattr(art.httpx, "stream", stream)
    art._manifests.clear()
    stale = tmp_path / "art" / "bioicons" / "cc-0" / "Animals" / "Me" / "gone.svg"
    stale.parent.mkdir(parents=True)
    stale.write_text(good)
    assert art.fetch("bioicons") == 2
    assert not stale.exists() and not [p for p in (tmp_path / "art").iterdir() if p.name.startswith(".")]
    assert [i["id"] for i in art._manifest("bioicons")] == ["bioicons/cc-0/Animals/Me/fly", "bioicons/cc-by-4.0/Viruses/DBCLS/adeno_virus"]
    assert art.installed()[0]["categories"] == ["Animals", "Viruses"] and art._manifest("bioicons")[1]["name"] == "adeno virus"
    assert (tmp_path / "art" / "bioicons" / "cc-0" / "Animals" / "Me" / "fly.svg").read_text() == art.normalise(good)

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("README.md", "")
    archive = empty
    with pytest.raises(RuntimeError, match="no usable icon"):
        art.fetch("bioicons")
    assert art.installed()[0]["icons"] == 2  # the old install stays when a fetch yields nothing
