import math
from pathlib import Path

import pytest

from wise_scholar import plots


def test_functions_are_sampled_safely():
    rows = plots.sample("sin(x)/x", [-10, 10], 5)
    assert [r["x"] for r in rows] == [-10, -5, 0, 5, 10] and rows[2]["y"] is None
    assert math.isclose(rows[0]["y"], math.sin(-10) / -10)
    assert plots.compile_fn("x^2 + 2*pi")(1) == 1 + 2 * math.pi
    assert math.isnan(plots.compile_fn("log(x)")(-1)) and math.isnan(plots.compile_fn("1/x")(0))
    for bad in ["__import__('os')", "x.real", "open('x')", "sin(x, y=1)", "y + 1", "min(1)", "sin()", "atan2(1)"]:
        with pytest.raises(ValueError):
            plots.compile_fn(bad)
    assert math.isnan(plots.compile_fn("9**9**9")(1)) and math.isnan(plots.compile_fn("pow(9, 9999999)")(1))
    with pytest.raises(ValueError, match="domain"):
        plots.sample("x", [1, 0])


def test_specs_resolve_rows_from_functions_inline_data_and_workspace_files(tmp_path: Path):
    (tmp_path / "runs.csv").write_text("t,residual,case\n0,1.0,A\n1,0.5,A\n0,2.0,B\n1,0.9,B\n")
    spec = {
        "x": {"label": "t (s)"},
        "marks": [
            {"type": "line", "fn": "exp(-x)", "domain": [0, 5], "samples": 3, "label": "decay"},
            {"type": "dot", "file": "runs.csv", "x": "t", "y": "residual", "stroke": "case"},
            {"type": "bar", "data": [{"k": "a", "v": 1}], "x": "k", "y": "v"},
            {"type": "rule", "y": 0},
        ],
    }
    out = plots.resolve(spec, tmp_path)
    assert out["marks"][0]["data"][0] == {"x": 0.0, "y": 1.0, "series": "decay"} and out["marks"][0]["stroke"] == "series"
    assert out["marks"][1]["data"][3] == {"t": 1.0, "residual": 0.9, "case": "B"}
    assert "fn" not in out["marks"][0] and "file" not in out["marks"][1]
    for bad, reason in [
        ({"marks": []}, "non-empty"),
        ({"marks": [{"type": "pie", "data": [{}]}]}, "type must be"),
        ({"marks": [{"type": "line", "data": [{"a": 1}], "x": "a"}]}, "missing \\[.y.\\]"),
        ({"marks": [{"type": "line", "file": "../../etc/passwd", "x": "a", "y": "b"}]}, "leaves"),
        ({"marks": [{"type": "line", "file": "nope.csv", "x": "a", "y": "b"}]}, "not a file"),
        ({"marks": [{"type": "rect", "data": [{"x1": 0}], "x1": "x1"}]}, "missing"),
        ({"marks": [{"type": "line", "data": [{"a": 1, "b": 2}], "x": "a", "y": "c"}]}, "not columns"),
        ({"marks": ["line"]}, "must be an object"),
    ]:
        with pytest.raises(ValueError, match=reason):
            plots.resolve(bad, tmp_path)
    ok = plots.resolve({"marks": [{"type": "rect", "data": [{"x1": 0, "x2": 1, "y1": 0, "y2": 2}], "x1": "x1", "x2": "x2", "y1": "y1", "y2": "y2"}]}, tmp_path)
    assert ok["marks"][0]["type"] == "rect"
    (tmp_path / "odd.csv").write_text("v\nnan\ninf\n1\n")
    assert [r["v"] for r in plots.load_rows(Path("odd.csv"), tmp_path)] == [None, None, 1.0]
    with pytest.raises(ValueError, match="not a file"):
        plots.load_rows(Path("."), tmp_path)
    big = (tmp_path / "big.csv")
    big.write_text("i,v\n" + "\n".join(f"{i},{i}" for i in range(5000)))
    assert len(plots.load_rows(Path("big.csv"), tmp_path)) == plots.MAX_ROWS
