"""Curated art packs the tutor places into its figures. A pack is installed on request; each icon is normalised once
into plain shapes with presentation attributes and kept with its licence. Share-alike icons and icons that cannot be
shown safely are left out."""
import argparse
import collections
import json
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
from defusedxml import ElementTree as safe

from . import db, figures

log = logging.getLogger(__name__)

ART = db.DB_PATH.parent / "art"
# Each pack is pinned to one commit, so an install is the same set of icons every time and a changed layout upstream
# is noticed when the pin moves, not by a learner.
BIOICONS_COMMIT = "d29e766ea7580b8063c4f47b29e872db40a4d979"
PACKS = {
    "bioicons": {
        "title": "Bioicons",
        "url": "https://bioicons.com",
        "zip": f"https://codeload.github.com/duerrsimon/bioicons/zip/{BIOICONS_COMMIT}",
        "root": f"bioicons-{BIOICONS_COMMIT}/static/icons/",
        "download": "231 MB",
    },
}
DOWNLOAD_TIMEOUT = httpx.Timeout(30, read=120)
# Share-alike licences would put the figure, and the course around it, under the same licence; those icons stay out.
LICENCES = {"cc-0": "CC0", "cc-by-3.0": "CC BY 3.0", "cc-by-4.0": "CC BY 4.0", "mit": "MIT", "bsd": "BSD"}
MAX_ICON = 400_000
LIMIT = 20
DRAWN = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "use"}
ENTITY = re.compile(r'<!ENTITY\s+([-\w]+)\s+"([^"]*)"\s*>')
DOCTYPE = re.compile(r"<!DOCTYPE[^\[>]*(\[.*?\])?\s*>", re.S)
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CLASS = re.compile(r"^\.([-\w]+)$")
PROPERTY = re.compile(r"^[a-zA-Z][a-zA-Z-]*$")
_manifests: dict[str, tuple[float, list[dict], list[str]]] = {}


def installed() -> list[dict]:
    """The installed packs with their icon counts and categories, for the tutor's tools line."""
    packs = []
    for pack, info in PACKS.items():
        if icons := _manifest(pack):
            packs.append({"pack": pack, "title": info["title"], "url": info["url"], "icons": len(icons), "categories": _manifests[pack][2]})
    return packs


def search(query: str, limit: int = LIMIT) -> tuple[list[dict], bool]:
    """Icons whose name, category or author contain the query's words, best matches first, and whether more matched
    than were returned."""
    words = _tokens(query)
    if not words:
        return [], False
    found = []
    for pack in PACKS:
        for icon in _manifest(pack):
            name, rest = _tokens(icon["name"]), _tokens(f"{icon['category']} {icon['author']}")
            score = sum(2 if any(w in t for t in name) else 1 if any(w in t for t in rest) else 0 for w in words)
            if score:
                found.append((-score, icon["name"].lower(), icon))
    found.sort(key=lambda f: f[:2])
    return [icon for _, _, icon in found[:limit]], len(found) > limit


def inline(svg: str) -> tuple[str, list[dict]]:
    """The figure with every `<use href="art:ID">` resolved to an inlined symbol, and the credits it owes."""
    if "art:" not in svg:
        return svg, []
    root = safe.fromstring(svg)
    uses = [e for e in root.iter(f"{{{figures.SVG_NS}}}use") if e.get("href", "").startswith("art:")]
    if not uses:
        return svg, []
    defs = root.find(f"{{{figures.SVG_NS}}}defs")
    if defs is None:
        defs = ET.Element(f"{{{figures.SVG_NS}}}defs")
        root.insert(0, defs)
    symbols: dict[str, str] = {}
    credits = []
    for use in uses:
        icon_id = use.get("href")[4:]
        if icon_id not in symbols:
            icon = _icon(icon_id)
            symbols[icon_id] = f"art-{len(symbols) + 1}"
            defs.append(_symbol(icon, symbols[icon_id]))
            credits.append({k: icon[k] for k in ("name", "author", "licence")} | {"pack": PACKS[icon["pack"]]["title"], "url": PACKS[icon["pack"]]["url"]})
        use.set("href", f"#{symbols[icon_id]}")
    ET.register_namespace("", figures.SVG_NS)
    return ET.tostring(root, encoding="unicode"), credits


def fetch(pack: str) -> int:
    """Downloads the pack and normalises its icons under ART/<pack>, replacing an earlier install only once the
    whole pack is ready; returns how many icons are usable."""
    info = PACKS[pack]
    ART.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory(dir=ART, prefix=f".{pack}-") as staging:
        archive = Path(tmp) / "pack.zip"
        with httpx.stream("GET", info["zip"], follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as response, archive.open("wb") as out:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                out.write(chunk)
        icons, skipped = [], collections.Counter()
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not (name.startswith(info["root"]) and name.endswith(".svg")):
                    continue
                parts = name[len(info["root"]) : -4].split("/")
                if len(parts) != 4:
                    skipped["not licence/category/author/name"] += 1
                    continue
                licence, category, author, title = parts
                if licence not in LICENCES:
                    skipped[f"licence {licence}"] += 1
                    continue
                drawing = normalise(z.read(name).decode("utf-8", "replace"))
                if drawing is None:
                    skipped["not showable (size, raster, script or shape)"] += 1
                    continue
                path = Path(staging) / licence / category / author / f"{title}.svg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(drawing)
                icons.append({
                    "id": f"{pack}/{licence}/{category}/{author}/{title}",
                    "name": title.replace("_", " "),
                    "category": category.replace("_", " "),
                    "author": author.replace("--", " ").replace("-", " ").strip(),
                    "licence": LICENCES[licence],
                    "ratio": _ratio(drawing),
                })
        if not icons:
            raise RuntimeError(f"{info['title']}: no usable icon in the archive; its layout may have changed")
        icons.sort(key=lambda i: i["id"])
        (Path(staging) / "manifest.json").write_text(json.dumps(icons, ensure_ascii=False))
        shutil.rmtree(ART / pack, ignore_errors=True)
        shutil.move(staging, ART / pack)
    _manifests.pop(pack, None)
    log.info("%s: %d icons installed; left out: %s", info["title"], len(icons), ", ".join(f"{n} {why}" for why, n in skipped.most_common()) or "none")
    return len(icons)


def normalise(svg: str) -> str | None:
    """The icon as the figure allowlist accepts it: entities expanded, class and inline styles turned into
    presentation attributes, a viewBox from width and height when there is none; None when nothing drawable
    is left, or the drawing is too large."""
    entities = dict(ENTITY.findall(svg))
    svg = DOCTYPE.sub("", svg)
    if entities:
        svg = re.sub(r"&([-\w]+);", lambda m: entities.get(m.group(1), m.group(0)), svg)
    try:
        root = safe.fromstring(svg.strip(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception:
        return None
    if figures._split(root.tag)[1] != "svg":
        return None
    if "viewBox" not in root.attrib:
        width, height = _length(root.get("width")), _length(root.get("height"))
        if not (width and height):
            return None
        root.set("viewBox", f"0 0 {width} {height}")
    if _box(root.get("viewBox")) is None:
        return None
    classes = _class_rules(root)
    for element in root.iter():
        declared = {}
        for name in element.get("class", "").split():
            declared.update(classes.get(name, {}))
        declared.update(_declarations(element.get("style", "")))
        for prop, value in declared.items():
            element.set(prop, value)
        element.attrib.pop("class", None)
        element.attrib.pop("style", None)
    try:
        drawing = figures.clean(ET.tostring(root, encoding="unicode"), limit=MAX_ICON)
    except ValueError:
        return None
    cleaned = safe.fromstring(drawing)
    if not any(figures._split(e.tag)[1] in DRAWN for e in cleaned.iter()):
        return None
    return drawing


def _class_rules(root: ET.Element) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    for style in root.iter():
        if figures._split(style.tag)[1] != "style":
            continue
        css = re.sub(r"/\*.*?\*/", "", style.text or "", flags=re.S)
        for selectors, body in RULE.findall(css):
            declarations = _declarations(body)
            for selector in selectors.split(","):
                if m := CLASS.match(selector.strip()):
                    rules.setdefault(m.group(1), {}).update(declarations)
    return rules


def _declarations(css: str) -> dict[str, str]:
    out = {}
    for declaration in css.split(";"):
        prop, _, value = declaration.partition(":")
        prop, value = prop.strip(), value.replace("!important", "").strip()
        if prop and value and PROPERTY.match(prop):
            out[prop] = value
    return out


def _length(value: str | None) -> float | None:
    if not value:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(px)?\s*$", value)
    return float(m.group(1)) if m else None


def _box(view_box: str | None) -> tuple[float, float, float, float] | None:
    try:
        x, y, w, h = (float(v) for v in (view_box or "").replace(",", " ").split())
    except ValueError:
        return None
    return (x, y, w, h) if w > 0 and h > 0 else None


def _ratio(drawing: str) -> float:
    _, _, w, h = _box(safe.fromstring(drawing).get("viewBox"))
    return round(w / h, 2)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).lower())


def _manifest(pack: str) -> list[dict]:
    path = ART / pack / "manifest.json"
    if not path.exists():
        return []
    stamp = path.stat().st_mtime
    cached = _manifests.get(pack)
    if cached is None or cached[0] != stamp:
        icons = json.loads(path.read_text())
        for icon in icons:
            icon["pack"] = pack
        _manifests[pack] = (stamp, icons, sorted({i["category"] for i in icons}))
    return _manifests[pack][1]


def _icon(icon_id: str) -> dict:
    pack = icon_id.partition("/")[0]
    for icon in _manifest(pack) if pack in PACKS else []:
        if icon["id"] == icon_id:
            return icon
    raise ValueError(f"no art with id {icon_id!r}; find ids with find_art")


def _symbol(icon: dict, symbol_id: str) -> ET.Element:
    """The icon as a <symbol>; its own ids get the symbol's prefix, since icons of one figure share the page's DOM."""
    root = safe.fromstring(figures.prefix_ids((ART / f"{icon['id']}.svg").read_text(), f"{symbol_id}-"))
    symbol = ET.Element(f"{{{figures.SVG_NS}}}symbol", {"id": symbol_id, "viewBox": root.get("viewBox")})
    for attr, value in root.attrib.items():
        if attr not in ("id", "viewBox", "width", "height"):
            symbol.set(attr, value)
    symbol.extend(list(root))
    return symbol


def main() -> None:
    parser = argparse.ArgumentParser(description="install the art packs the tutor may place into its figures")
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("fetch", help="download and install a pack")
    get.add_argument("pack", choices=sorted(PACKS))
    sub.add_parser("list", help="show the packs and whether they are installed")
    args = parser.parse_args()
    if args.command == "fetch":
        print(f"{PACKS[args.pack]['title']}: {fetch(args.pack)} icons installed under {ART / args.pack}")
    else:
        have = {p["pack"]: p for p in installed()}
        for pack, info in PACKS.items():
            state = f"{have[pack]['icons']} icons installed" if pack in have else f"not installed ({info['download']} download)"
            print(f"{pack}: {info['title']}, {state}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
