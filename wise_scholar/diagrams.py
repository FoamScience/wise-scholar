"""Diagrams the tutor states in Penrose's Substance language and the server lays out: the domains live under
wise_scholar/penrose/ as <name>.domain, <name>.style and <name>.md (what the tutor reads), the layout runs in the Node
sidecar under diagrams/ once its dependencies are installed."""
import json
import logging
import re
import subprocess
from pathlib import Path

from . import db

log = logging.getLogger(__name__)

HERE = Path(__file__).parent / "penrose"
SIDECAR = db.ROOT / "diagrams"
ATTEMPTS = 12
TIMEOUT = 60
MAX_SUBSTANCE = 3000
SENTENCE = re.compile(r"^(.*?\.)(?:\s|$)")


def available() -> bool:
    """Whether the sidecar can run: its dependencies were installed by `make build`."""
    return (SIDECAR / "node_modules" / "@penrose" / "core" / "package.json").exists()


def domains() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.domain") if (HERE / f"{p.stem}.style").exists())


def summary(name: str) -> str:
    """The first sentence of the domain's notes, for the tools line."""
    notes = HERE / f"{name}.md"
    if not notes.exists():
        return name
    first = notes.read_text().strip().partition("\n")[0]
    return (SENTENCE.match(first) or [first, first])[1]


def help_text(name: str) -> str:
    """What the tutor needs to write a Substance for the domain: the notes with the example, then the domain itself."""
    return f"{(HERE / f'{name}.md').read_text().strip()}\n\nDomain:\n```\n{(HERE / f'{name}.domain').read_text().strip()}\n```"


def render(name: str, substance: str) -> str:
    """The diagram as SVG; raises ValueError with the compiler's message or the rules that stayed broken."""
    if name not in domains():
        raise ValueError(f"no diagram domain named {name!r}; the domains are {', '.join(domains())}")
    if len(substance) > MAX_SUBSTANCE:
        raise ValueError(f"the Substance is over {MAX_SUBSTANCE} characters; fewer objects")
    if not available():
        raise ValueError("diagrams are not installed on this server")
    trio = {
        "domain": (HERE / f"{name}.domain").read_text(),
        "style": (HERE / f"{name}.style").read_text(),
        "substance": substance,
        "attempts": ATTEMPTS,
    }
    try:
        run = subprocess.run(
            ["node", str(SIDECAR / "render.mjs")],
            input=json.dumps(trio),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT,
            cwd=SIDECAR,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"the layout took over {TIMEOUT} seconds; fewer objects") from None
    except OSError as e:
        log.error("diagram sidecar cannot start: %s", e)
        raise ValueError("the diagram renderer cannot start (is node installed?); the server log has the details") from None
    try:
        result = json.loads(run.stdout)
        ok, error, rules = result["ok"], result.get("error", ""), result.get("rules", [])
        svg = result["svg"] if ok else ""
    except (ValueError, KeyError, TypeError):
        log.error("diagram sidecar gave no usable answer (exit %s): %s %s", run.returncode, run.stdout[-500:], run.stderr[-2000:])
        raise ValueError("the diagram renderer failed; the server log has the details") from None
    if not ok:
        listed = "".join(f"\n- {r}" for r in rules)
        raise ValueError(error + (f"; the rules:{listed}\nState fewer objects rather than retrying as is." if rules else ""))
    return svg
