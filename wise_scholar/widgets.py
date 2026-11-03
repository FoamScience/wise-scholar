"""Widgets the learner operates: sliders that set a model's inputs, readouts, a plot and a drawing that follow them.
The tutor states the model as expressions; the server evaluates every reachable setting with the plots evaluator, so
the browser only looks values up and runs nothing the tutor wrote. A drawing is a scrubbed SVG whose numbers the
browser fills in from the setting's state."""
import hashlib
import itertools
import math
import re

from . import figures, plots

MAX_CONTROLS = 3
MAX_STEPS = 101
MAX_STATES = 400
MAX_READOUTS = 4
MAX_MARKS = 4
SAMPLES = 100
# Every sampled curve value of every setting together; it bounds the block sent to the browser.
MAX_POINTS = 40_000
# Places in a drawing that follow the sliders: `{{expr}}` in the tutor's SVG, a token after the scrub.
MAX_PLACES = 30
PLACE = re.compile(r"\{\{([^{}]{1,200})\}\}")
TOKEN = re.compile(r"__w(\d+)__")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
RESERVED = {"x", *plots.NAMES, *plots.FUNCTIONS}


def _finite(value: float) -> float | None:
    return float(f"{value:.6g}") if math.isfinite(value) else None


def index_of(widget: dict, at: list[int]) -> int:
    """The index in `states` of the sliders at these positions: row-major, the first slider slowest."""
    if len(at) != len(widget["controls"]) or any(not 0 <= p < len(c["values"]) for c, p in zip(widget["controls"], at)):
        raise ValueError("not a setting of this widget")
    index = 0
    for c, p in zip(widget["controls"], at):
        index = index * len(c["values"]) + p
    return index


def start_index(widget: dict) -> int:
    return index_of(widget, [c["start"] for c in widget["controls"]])


def setting(widget: dict, at: list[int]) -> str:
    """The sliders' values at these positions, in words."""
    return ", ".join(f"{c['label']} = {c['values'][p]:g}" + (f" {c['unit']}" if c["unit"] else "") for c, p in zip(widget["controls"], at))


def describe(widget: dict, at: list[int]) -> str:
    """One setting in words, for the tutor: each slider's value, then what the readouts showed."""
    def unit(u: str) -> str:
        return f" {u}" if u else ""
    sliders = setting(widget, at)
    shown = widget["states"][index_of(widget, at)]["readouts"]
    readouts = []
    for r, value in zip(widget["readouts"], shown):
        digits = r["digits"]
        readouts.append(f"{r['label']} " + ("not defined" if value is None else f"{value:.{digits}f}{unit(r['unit'])}"))
    return f"{sliders} -> {', '.join(readouts)}"


def _controls(raw) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CONTROLS:
        raise ValueError(f"controls must be a list of 1 to {MAX_CONTROLS} sliders")
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise ValueError(f"control {i}: must be an object")
        name = c.get("name")
        if not isinstance(name, str) or not NAME.match(name) or name in RESERVED:
            raise ValueError(f"control {i}: name must be a short lowercase identifier other than x and the math names")
        if any(o["name"] == name for o in out):
            raise ValueError(f"control {i}: the name {name!r} is used twice")
        try:
            low, high, step, value = (float(c[k]) for k in ("min", "max", "step", "value"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"control {name}: min, max, step and value must be numbers") from None
        if not (low < high and step > 0):
            raise ValueError(f"control {name}: needs min < max and step > 0")
        count = math.floor((high - low) / step + 1e-9) + 1
        if count > MAX_STEPS:
            raise ValueError(f"control {name}: at most {MAX_STEPS} positions; make the step larger")
        values = [round(low + k * step, 10) for k in range(count)]
        start = min(range(count), key=lambda k: abs(values[k] - value))
        if abs(values[start] - value) > step * 1e-6:
            raise ValueError(f"control {name}: value {value:g} is not one of the slider's positions")
        out.append({"name": name, "label": str(c.get("label") or name), "unit": str(c.get("unit", "")), "values": values, "start": start})
    if math.prod(len(c["values"]) for c in out) > MAX_STATES:
        raise ValueError(f"the sliders reach more than {MAX_STATES} settings together; use fewer positions")
    return out


def _readouts(raw, names: tuple[str, ...]) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_READOUTS:
        raise ValueError(f"readouts must be a list of 1 to {MAX_READOUTS} values")
    out = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict) or not isinstance(r.get("expr"), str) or not r.get("label"):
            raise ValueError(f"readout {i}: needs a label and an expr")
        digits = r.get("digits", 2)
        if not isinstance(digits, int) or not 0 <= digits <= 6:
            raise ValueError(f"readout {i}: digits must be a whole number from 0 to 6")
        out.append({"label": str(r["label"]), "unit": str(r.get("unit", "")), "digits": digits, "fn": plots.compile_fn(r["expr"], names)})
    return out


def _marks(raw, names: tuple[str, ...]) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_MARKS:
        raise ValueError(f"plot.marks must be a list of 1 to {MAX_MARKS} marks")
    out = []
    for i, m in enumerate(raw):
        kind = m.get("type") if isinstance(m, dict) else None
        if kind in ("line", "area"):
            domain = m.get("domain")
            if not (isinstance(domain, list) and len(domain) == 2 and all(isinstance(v, (int, float)) for v in domain) and domain[0] < domain[1]):
                raise ValueError(f"mark {i}: a {kind} needs domain [start, end] with start < end")
            if not isinstance(m.get("fn"), str):
                raise ValueError(f"mark {i}: a {kind} needs fn, an expression of x and the sliders")
            xs = [domain[0] + (domain[1] - domain[0]) * k / (SAMPLES - 1) for k in range(SAMPLES)]
            out.append({"type": kind, "label": str(m.get("label") or m["fn"]), "xs": xs, "fn": plots.compile_fn(m["fn"], ("x", *names))})
        elif kind == "rule" and ("x" in m) != ("y" in m):
            axis = "x" if "x" in m else "y"
            out.append({"type": "rule", "axis": axis, "label": str(m.get("label", "")), "fn": plots.compile_fn(str(m[axis]), names)})
        else:
            raise ValueError(f"mark {i}: type must be line, area, or rule with one of x or y")
    return out


def _axis(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("an axis must be an object")
    return {k: raw[k] for k in ("label", "domain", "type") if k in raw}


def _drawing(svg, names: tuple[str, ...]) -> tuple[str, list]:
    """The drawing scrubbed with a token for each `{{expr}}`, and the expressions in token order."""
    if not isinstance(svg, str):
        raise ValueError("figure must be an SVG string")
    if TOKEN.search(svg):
        raise ValueError("figure may not contain text like __w0__; the server uses it to mark the places")
    exprs = PLACE.findall(svg)
    if not 1 <= len(exprs) <= MAX_PLACES:
        raise ValueError(f"figure needs 1 to {MAX_PLACES} places written {{{{expr}}}} that follow the sliders")
    places = iter(range(len(exprs)))
    template = figures.clean(PLACE.sub(lambda m: f"__w{next(places)}__", svg))
    if missing := [exprs[i] for i in range(len(exprs)) if f"__w{i}__" not in template]:
        raise ValueError(f"the places {missing} sit where the figure's scrub removed them; put places only in attribute values and text")
    # Ids made unique to this drawing, so two widgets or a widget and a figure on one page stay apart.
    template = figures.prefix_ids(template, f"w{hashlib.sha256(template.encode()).hexdigest()[:8]}-")
    return template, [_place(e, names) for e in exprs]


def _place(text: str, names: tuple[str, ...]):
    """One place's value at a setting: `expr`, or `expr|2` rounded to two decimals for a number shown as text."""
    expr, _, digits = text.rpartition("|") if re.search(r"\|\s*\d\s*$", text) else (text, "", "")
    fn = plots.compile_fn(expr, names)
    if not digits:
        return fn

    def rounded(*setting: float) -> float:
        value = fn(*setting)
        return round(value, int(digits)) if math.isfinite(value) else value
    return rounded


def filled(widget: dict, at: list[int]) -> str:
    """The widget's drawing at one setting, as the browser shows it."""
    values = widget["states"][index_of(widget, at)]["figure"]
    return TOKEN.sub(lambda m: f"{values[int(m.group(1))] or 0:g}", widget["figure"])


def _heights(marks: list[dict], states: list[dict]) -> list[float]:
    ys = []
    for state in states:
        for m, v in zip(marks, state["marks"]):
            if m["type"] != "rule":
                ys += [y for y in v if y is not None]
            elif m["axis"] == "y" and v is not None:
                ys.append(v)
    return ys


def resolve(spec: dict) -> dict:
    """The widget with every setting evaluated; raises ValueError for anything it cannot show."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    controls = _controls(spec.get("controls"))
    names = tuple(c["name"] for c in controls)
    readouts = _readouts(spec.get("readouts"), names)
    plot = spec.get("plot")
    if plot is not None and not isinstance(plot, dict):
        raise ValueError("plot must be an object")
    marks = _marks(plot.get("marks"), names) if plot else []
    drawing, places = _drawing(spec["figure"], names) if "figure" in spec else (None, [])
    settings = math.prod(len(c["values"]) for c in controls)
    if settings * SAMPLES * sum(m["type"] != "rule" for m in marks) > MAX_POINTS:
        raise ValueError(f"the curves over every setting pass {MAX_POINTS} points; use fewer slider positions or fewer curves")
    states = []
    for setting in itertools.product(*(c["values"] for c in controls)):
        state = {"readouts": [_finite(r["fn"](*setting)) for r in readouts], "marks": []}
        for m in marks:
            if m["type"] == "rule":
                state["marks"].append(_finite(m["fn"](*setting)))
            else:
                state["marks"].append([_finite(m["fn"](x, *setting)) for x in m["xs"]])
        if drawing:
            state["figure"] = [_finite(fn(*setting)) for fn in places]
        states.append(state)
    out = {
        "controls": [{k: c[k] for k in ("name", "label", "unit", "values", "start")} for c in controls],
        "readouts": [{k: r[k] for k in ("label", "unit", "digits")} for r in readouts],
        "states": states,
    }
    if plot:
        x, y = _axis(plot.get("x")), _axis(plot.get("y"))
        # One y range over every setting, so moving a slider moves the curve, not the axis.
        if "domain" not in y and (ys := _heights(marks, states)):
            y["domain"] = [min(ys), max(ys)] if min(ys) < max(ys) else [min(ys) - 1, max(ys) + 1]
        out["plot"] = {"x": x, "y": y, "marks": [{k: m[k] for k in ("type", "label", "xs", "axis") if k in m} for m in marks]}
    if drawing:
        out["figure"] = drawing
    return out


def extremes(widget: dict) -> list[list[int]]:
    """The settings worth looking at before the learner does: the start, every slider at its least, at its most."""
    start = [c["start"] for c in widget["controls"]]
    least = [0] * len(widget["controls"])
    most = [len(c["values"]) - 1 for c in widget["controls"]]
    return [at for i, at in enumerate((start, least, most)) if at not in (start, least, most)[:i]]
