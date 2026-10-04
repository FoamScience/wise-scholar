"""Plot specs the tutor writes as JSON, resolved on the server: functions are sampled here, files read here,
so the browser only draws rows it is given."""
import ast
import csv
import io
import math
from pathlib import Path

from . import course_files

MARKS = {"line", "dot", "bar", "area", "rule", "text", "rect"}
MAX_ROWS = 2000
DEFAULT_SAMPLES = 200
MAX_SAMPLES = 2000
FUNCTIONS = {
    name: getattr(math, name)
    for name in ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "exp", "log", "log10", "log2",
                 "sqrt", "floor", "ceil", "pow", "hypot", "gamma", "erf")
} | {"abs": abs, "min": min, "max": max, "pow": lambda a, b: float(a) ** float(b)}
NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}
# Floats throughout: a float power overflows at once instead of grinding through a huge integer.
OPERATORS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
             ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: float(a) ** float(b), ast.Mod: lambda a, b: a % b}


def compile_fn(expression: str):
    """A function of x from an expression using numbers, + - * / ** %, and the math names above; nothing else."""
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"cannot read the expression {expression!r}: {e.msg}") from None

    def check(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            pass
        elif isinstance(node, ast.Name) and (node.id == "x" or node.id in NAMES):
            pass
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            check(node.operand)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            for arg in node.args:
                check(arg)
        else:
            raise ValueError(f"the expression {expression!r} uses something outside x, numbers, + - * / ** and {sorted(FUNCTIONS)}")

    check(tree)

    def evaluate(node: ast.AST, x: float) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, x)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return x if node.id == "x" else NAMES[node.id]
        if isinstance(node, ast.BinOp):
            return OPERATORS[type(node.op)](evaluate(node.left, x), evaluate(node.right, x))
        if isinstance(node, ast.UnaryOp):
            value = evaluate(node.operand, x)
            return -value if isinstance(node.op, ast.USub) else value
        return FUNCTIONS[node.func.id](*(evaluate(a, x) for a in node.args))

    def fn(x: float) -> float:
        try:
            value = evaluate(tree, x)
        except (ValueError, ZeroDivisionError, OverflowError):
            return math.nan
        return value if isinstance(value, (int, float)) and math.isfinite(value) else math.nan

    try:
        evaluate(tree, 1.0)
    except TypeError:
        raise ValueError(f"a function in {expression!r} is called with the wrong number of arguments") from None
    except (ValueError, ZeroDivisionError, OverflowError):
        pass
    return fn


def sample(expression: str, domain: list[float], samples: int = DEFAULT_SAMPLES) -> list[dict]:
    if not (isinstance(domain, list) and len(domain) == 2 and domain[0] < domain[1]):
        raise ValueError("domain must be [start, end] with start < end")
    samples = max(2, min(int(samples), MAX_SAMPLES))
    fn = compile_fn(expression)
    a, b = domain
    rows = []
    for i in range(samples):
        x = a + (b - a) * i / (samples - 1)
        y = fn(x)
        rows.append({"x": x, "y": None if math.isnan(y) else y})
    return rows


def load_rows(path: Path, workspace: Path) -> list[dict]:
    """Rows of a CSV or TSV in the course workspace, numbers parsed, thinned to MAX_ROWS."""
    text = course_files.read_text(workspace, str(path))
    if text is None:
        raise ValueError(f"{path} is not a file in the workspace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [{k.strip(): _number(v) for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)]
    if len(rows) > MAX_ROWS:
        step = len(rows) / MAX_ROWS
        rows = [rows[int(i * step)] for i in range(MAX_ROWS)]
    return rows


def _number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return value.strip()
    return number if math.isfinite(number) else None


def resolve(spec: dict, workspace: Path) -> dict:
    """The spec with every mark's rows attached; raises ValueError for anything the browser could not draw."""
    marks = spec.get("marks")
    if not isinstance(marks, list) or not marks:
        raise ValueError("spec.marks must be a non-empty list")
    out = []
    for i, mark in enumerate(marks):
        if not isinstance(mark, dict):
            raise ValueError(f"mark {i}: must be an object")
        kind = mark.get("type")
        if kind not in MARKS:
            raise ValueError(f"mark {i}: type must be one of {sorted(MARKS)}, got {kind!r}")
        resolved = {k: v for k, v in mark.items() if k not in ("fn", "file", "domain", "samples")}
        if "fn" in mark:
            label = mark.get("label") or mark["fn"]
            rows = [{**r, "series": label} for r in sample(mark["fn"], mark.get("domain", [-10, 10]), mark.get("samples", DEFAULT_SAMPLES))]
            resolved.update(data=rows, x="x", y="y", stroke=mark.get("stroke", "series"))
        elif "file" in mark:
            resolved["data"] = load_rows(Path(mark["file"]), workspace)
        elif kind == "rule":
            if "x" not in mark and "y" not in mark:
                raise ValueError(f"mark {i}: a rule needs x or y")
        else:
            data = mark.get("data")
            if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data):
                raise ValueError(f"mark {i}: data must be a list of row objects (or use fn/file)")
            if len(data) > MAX_ROWS:
                raise ValueError(f"mark {i}: at most {MAX_ROWS} rows inline; put larger data in a workspace file")
        needed = {"line": ("x", "y"), "dot": ("x", "y"), "bar": ("x", "y"), "area": ("x", "y"), "text": ("x", "y", "text"),
                  "rect": ("x1", "x2", "y1", "y2"), "rule": ()}[kind]
        if missing := [k for k in needed if k not in resolved]:
            raise ValueError(f"mark {i}: a {kind} needs the fields {list(needed)}; missing {missing}")
        if kind != "rule":
            columns = set().union(*(r.keys() for r in resolved["data"]))
            if unknown := [resolved[k] for k in needed if isinstance(resolved[k], str) and resolved[k] not in columns]:
                raise ValueError(f"mark {i}: the fields {unknown} are not columns of the data; columns are {sorted(columns)}")
            for extra in ("stroke", "fill"):
                if isinstance(resolved.get(extra), str) and resolved[extra] not in columns and not resolved[extra].startswith("#"):
                    raise ValueError(f"mark {i}: {extra} {resolved[extra]!r} is neither a column nor a #colour")
        out.append(resolved)
    return {**spec, "marks": out}
