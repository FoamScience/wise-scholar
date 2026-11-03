"""Widgets the learner operates: sliders that set a model's inputs, readouts and a plot that follow them. The tutor
states the model as expressions; the server evaluates every reachable setting with the plots evaluator, so the
browser only looks values up and runs nothing the tutor wrote."""
import itertools
import math
import re

from . import plots

MAX_CONTROLS = 3
MAX_STEPS = 101
MAX_STATES = 400
MAX_READOUTS = 4
MAX_MARKS = 4
SAMPLES = 100
# Every sampled curve value of every setting together; it bounds the block sent to the browser.
MAX_POINTS = 40_000
NAME = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
RESERVED = {"x", *plots.NAMES, *plots.FUNCTIONS}


def _finite(value: float) -> float | None:
    return float(f"{value:.6g}") if math.isfinite(value) else None


def start_index(widget: dict) -> int:
    """The index in `states` of the setting the sliders start at: row-major, the first slider slowest."""
    index = 0
    for c in widget["controls"]:
        index = index * len(c["values"]) + c["start"]
    return index


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
    return out
