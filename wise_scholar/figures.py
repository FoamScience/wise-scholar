"""Figures the tutor draws as SVG: an allowlist keeps them to shapes, paths and text before they are shown inline."""
import re
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as safe

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ELEMENTS = {
    "svg", "g", "defs", "title", "desc", "symbol", "use", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "textPath", "marker", "clipPath", "mask", "pattern", "linearGradient", "radialGradient",
    "stop",
}
MAX_CHARS = 60_000
MAX_DEPTH = 64
LOCAL_REF = re.compile(r"url\(\s*#[-\w]+\s*\)")


def clean(svg: str) -> str:
    """The SVG with everything outside the allowlist removed; raises ValueError when it cannot be shown."""
    if len(svg) > MAX_CHARS:
        raise ValueError(f"the SVG is over {MAX_CHARS} characters; simplify the drawing")
    try:
        root = safe.fromstring(svg.strip(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as e:
        raise ValueError(f"not well-formed SVG: {e}") from None
    if _split(root.tag) != (SVG_NS, "svg") and _split(root.tag) != ("", "svg"):
        raise ValueError("the root element must be <svg>")
    if "viewBox" not in root.attrib:
        raise ValueError("the <svg> needs a viewBox")
    _refuse_active_content(root, 0)
    _scrub(root)
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    root.tag = f"{{{SVG_NS}}}svg"
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode")


def prefix_ids(svg: str, prefix: str) -> str:
    """Ids and their local references made unique to one figure, since figures share the page's DOM."""
    svg = re.sub(r'\bid="([-\w]+)"', lambda m: f'id="{prefix}{m.group(1)}"', svg)
    svg = re.sub(r'href="#([-\w]+)"', lambda m: f'href="#{prefix}{m.group(1)}"', svg)
    return re.sub(r"url\(\s*#([-\w]+)\s*\)", lambda m: f"url(#{prefix}{m.group(1)})", svg)


def _split(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _refuse_active_content(element: ET.Element, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValueError(f"the drawing nests more than {MAX_DEPTH} levels deep")
    if _split(element.tag)[1].lower() == "script":
        raise ValueError("scripts are not allowed in a figure")
    for attr in element.attrib:
        if _split(attr)[1].lower().startswith("on"):
            raise ValueError("event attributes are not allowed in a figure")
    for child in element:
        _refuse_active_content(child, depth + 1)


def _scrub(element: ET.Element) -> None:
    _scrub_attributes(element)
    for child in list(element):
        ns, name = _split(child.tag)
        if ns not in ("", SVG_NS) or name not in ELEMENTS:
            element.remove(child)
            continue
        child.tag = f"{{{SVG_NS}}}{name}"
        _scrub(child)


def _scrub_attributes(element: ET.Element) -> None:
    for attr, value in list(element.attrib.items()):
        ns, local = _split(attr)
        low = value.lower()
        if local == "href":
            if ns not in ("", XLINK_NS) or not value.startswith("#"):
                del element.attrib[attr]
            elif ns == XLINK_NS:
                del element.attrib[attr]
                element.set("href", value)
        elif ns:
            del element.attrib[attr]
        elif "url(" in low and not LOCAL_REF.fullmatch(value.strip()):
            del element.attrib[attr]
        elif local == "style" and ("url(" in low or "@import" in low or "expression" in low):
            del element.attrib[attr]
