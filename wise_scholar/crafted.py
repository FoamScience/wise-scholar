"""Crafted figures: the tutor scripts a shaded isometric object against the vendored kit under kit/ (from anima, MIT),
Node runs the script in the course sandbox, and the SVG it exports is shown like any figure. The kit's classes are
coloured by kit/iso.css, which the web app loads; an export carries that style inlined."""
import json
import re
import shutil
import tempfile
from pathlib import Path

from . import figures, sandbox

KIT = Path(__file__).parent / "kit"
MAX_SCRIPT = 30_000
MAX_SVG = 120_000
MIN_STAGES, MAX_STAGES = 2, 6
SECONDS_PER_STAGE = 3
FADE = 0.4  # seconds of crossfade from one stage into the next
INSIDE = Path("/run/figure")
RUNNER = (
    'import { writeFileSync } from "node:fs";\n'
    'const figure = (await import("./figure.mjs")).default;\n'
    'writeFileSync(new URL("./figure.json", import.meta.url), JSON.stringify(Array.isArray(figure) ? figure.map(String) : [String(figure)]));\n'
)
ROOT = re.compile(r"^\s*(<svg\b[^>]*>)(.*)</svg>\s*$", re.S)
DRAWN = ('class="iso-solid', 'class="tb"', 'class="bio-blob"', 'class="bio-membrane"')
VIEWBOX = re.compile(r'viewBox="([^"]*)"')
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


async def render(script: str, workspace: Path) -> list[str]:
    """The SVG the script exports, or the stages of its animation, each a whole SVG; raises ValueError with Node's
    message when it does not run, and when a stage draws nothing from the kit or the stages differ in size."""
    if len(script) > MAX_SCRIPT:
        raise ValueError(f"the script is over {MAX_SCRIPT} characters; build fewer parts")
    with tempfile.TemporaryDirectory(prefix="wise-scholar-figure-") as folder:
        work = Path(folder)
        (work / "kit").mkdir()
        for module in KIT.glob("*.mjs"):
            shutil.copy(module, work / "kit")
        (work / "figure.mjs").write_text(script)
        (work / "run.mjs").write_text(RUNNER)
        where = INSIDE if sandbox.SANDBOX else work
        result = await sandbox.run(f"node {where / 'run.mjs'}", workspace, mounts=[(str(work), str(INSIDE))])
        drawn = work / "figure.json"
        if result["exit_code"] != 0 or not drawn.exists():
            said = "\n".join(line for line in result["output"].splitlines() if not line.startswith("    at "))
            why = "stopped at the time limit" if result["exit_code"] is None else said.strip()[-2000:] or "it exported nothing"
            raise ValueError(f"the script did not run: {why}")
        stages = json.loads(drawn.read_text())
    if len(stages) != 1 and not MIN_STAGES <= len(stages) <= MAX_STAGES:
        raise ValueError(f"an animation has {MIN_STAGES} to {MAX_STAGES} stages; the script exported {len(stages)}")
    heads = []
    for svg in stages:
        if len(svg) > MAX_SVG:
            raise ValueError(f"a figure is over {MAX_SVG} characters; build fewer or simpler parts")
        if not (root := ROOT.match(svg)):
            raise ValueError("a figure is not a whole <svg>; export what figureSvg returns, nothing before or after it")
        if not any(mark in svg for mark in DRAWN):
            raise ValueError("a figure draws nothing from the kit; build it from its prisms, tubes, turned bodies or soft bodies")
        heads.append(root[1])
    if len({(VIEWBOX.search(head) or [None, None])[1] for head in heads}) > 1:
        raise ValueError("the stages differ in size; give every stage the same figureSvg width and height and the same camera")
    return stages


def animate(stages: list[str]) -> str:
    """One SVG playing the stages in turn: each is held, the next fades in over it, and the first comes back after
    the last. The root carries the stage count and the seconds, as the diagram animations do, so the stage buttons
    can hold one. A stage's ids are prefixed with its number, so what two stages define apart stays apart."""
    n, seconds = len(stages), SECONDS_PER_STAGE * len(stages)
    fade, cut = FADE / seconds, 0.001
    groups = []
    for i, stage in enumerate(stages):
        head, body = ROOT.match(figures.prefix_ids(stage, f"s{i}-")).groups()
        start, end = i / n, (i + 1) / n
        # The stage above is opaque before this one goes, so the drawing never thins out between two stages.
        keys = ([(0, 1)] if i == 0 else [(0, 0), (start, 0), (start + fade, 1)]) + ([(1, 1)] if i == n - 1 else [(end + fade, 1), (end + fade + cut, 0), (1, 0)])
        times, values = ";".join(f"{t:.3f}" for t, _ in keys), ";".join(str(v) for _, v in keys)
        groups.append(
            f'<g opacity="{keys[0][1]}"><animate attributeName="opacity" values="{values}" keyTimes="{times}" '
            f'dur="{seconds}s" repeatCount="indefinite"/>{body}</g>'
        )
    return f'{head[:-1]} data-stages="{n}" data-seconds="{seconds}">{"".join(groups)}</svg>'


def standalone(svg: str) -> str:
    """The figure with its style inlined in the light theme, for a file or image shown outside the web app."""
    css = TOKEN.sub(lambda m: LIGHT.get(m[1], m[0]), (KIT / "iso.css").read_text())
    return svg.replace(">", f"><style>{css}</style>", 1)
