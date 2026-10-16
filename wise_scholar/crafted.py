"""Crafted figures: the tutor scripts a shaded isometric object against the vendored kit under kit/ (from anima, MIT),
Node runs the script in the course sandbox, and the SVG it exports is shown like any figure. The kit's classes are
coloured by kit/iso.css, which the web app loads; an export carries that style inlined."""
import re
import shutil
import tempfile
from pathlib import Path

from . import sandbox

KIT = Path(__file__).parent / "kit"
MAX_SCRIPT = 30_000
MAX_SVG = 120_000
INSIDE = Path("/run/figure")
RUNNER = (
    'import { writeFileSync } from "node:fs";\n'
    'const figure = (await import("./figure.mjs")).default;\n'
    'writeFileSync(new URL("./figure.svg", import.meta.url), String(figure));\n'
)
# The light theme's values of the tokens iso.css reads, for an SVG shown outside the web app.
LIGHT = {
    "--panel": "#ffffff", "--ink": "#14202b", "--line": "#d5dbe1", "--line-strong": "#8794a1",
    "--teal": "#0b5f5a", "--amber": "#6b3a00", "--danger": "#8f2d0f", "--mono": "'JetBrains Mono', ui-monospace, monospace",
}  # fmt: skip
TOKEN = re.compile(r"var\((--[\w-]+)\)")


def available() -> bool:
    """Whether figures can be crafted: the server runs commands, and Node is on its path."""
    return sandbox.commands() and shutil.which("node") is not None


def help_text() -> str:
    return (KIT / "craft.md").read_text()


async def render(script: str, workspace: Path) -> str:
    """The SVG the script exports; raises ValueError with Node's message when it does not run or draws no solid."""
    if len(script) > MAX_SCRIPT:
        raise ValueError(f"the script is over {MAX_SCRIPT} characters; build fewer parts")
    with tempfile.TemporaryDirectory(prefix="wise-scholar-figure-") as folder:
        work = Path(folder)
        (work / "kit").mkdir()
        shutil.copy(KIT / "iso-kit.mjs", work / "kit")
        (work / "figure.mjs").write_text(script)
        (work / "run.mjs").write_text(RUNNER)
        where = INSIDE if sandbox.SANDBOX else work
        result = await sandbox.run(f"node {where / 'run.mjs'}", workspace, mounts=[(str(work), str(INSIDE))])
        drawn = work / "figure.svg"
        if result["exit_code"] != 0 or not drawn.exists():
            said = "\n".join(line for line in result["output"].splitlines() if not line.startswith("    at "))
            why = "stopped at the time limit" if result["exit_code"] is None else said.strip()[-2000:] or "it exported nothing"
            raise ValueError(f"the script did not run: {why}")
        svg = drawn.read_text()
    if len(svg) > MAX_SVG:
        raise ValueError(f"the figure is over {MAX_SVG} characters; build fewer or simpler parts")
    if "iso-solid" not in svg:
        raise ValueError("the figure has no solid in it; build it from the kit's slabs and cylinders")
    return svg


def standalone(svg: str) -> str:
    """The figure with its style inlined in the light theme, for a file or image shown outside the web app."""
    css = TOKEN.sub(lambda m: LIGHT.get(m[1], m[0]), (KIT / "iso.css").read_text())
    return svg.replace(">", f"><style>{css}</style>", 1)
