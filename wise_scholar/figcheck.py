"""A drawn figure looked at before the learner sees it: a headless Chromium lays it out at the lesson's width and
reports what a reader would trip over (nothing drawn, labels past the edge, labels on top of each other, labels too
small to read). Without Playwright or a browser the figure goes out unchecked. Labels are measured in the site's
face when the machine has it installed, else in its sans-serif, which runs wider and so errs on the strict side."""
import asyncio
import importlib.util

WIDTH = 600
SMALLEST_PX = 9
# How far a label may stand past the edge, and how much of the smaller of two labels may be covered, before it counts.
EDGE_SLACK = 0.01
OVERLAP = 0.3

# Measures in the drawing's own units, so a viewBox of any size reads the same.
MEASURE = """([smallest, slack, overlap]) => {
  const svg = document.querySelector('svg')
  const vb = svg.viewBox.baseVal
  const scale = svg.getBoundingClientRect().width / vb.width
  const found = []
  const painted = [...svg.querySelectorAll('path, rect, circle, ellipse, line, polyline, polygon, text, use')]
    .some((e) => { const r = e.getBoundingClientRect(); return r.width > 0 || r.height > 0 })
  if (!painted) return ['nothing is drawn: every shape is empty or outside the viewBox']
  const boxes = []
  for (const text of svg.querySelectorAll('text')) {
    const label = text.textContent.trim()
    const r = text.getBoundingClientRect(), s = svg.getBoundingClientRect()
    if (!label || (r.width === 0 && r.height === 0)) continue
    const box = { label, x1: (r.left - s.left) / scale, y1: (r.top - s.top) / scale, x2: (r.right - s.left) / scale, y2: (r.bottom - s.top) / scale }
    const dx = vb.width * slack, dy = vb.height * slack
    if (box.x1 < -dx || box.y1 < -dy || box.x2 > vb.width + dx || box.y2 > vb.height + dy) found.push(`the label "${label}" runs past the edge of the viewBox`)
    const m = text.getScreenCTM()
    const px = parseFloat(getComputedStyle(text).fontSize) * (m ? Math.hypot(m.a, m.b) : scale)
    if (smallest && px < smallest) found.push(`the label "${label}" is ${px.toFixed(1)} px tall at ${Math.round(s.width)} px wide; make it at least ${smallest} px`)
    boxes.push(box)
  }
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j]
      const w = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1), h = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1)
      const smaller = Math.min((a.x2 - a.x1) * (a.y2 - a.y1), (b.x2 - b.x1) * (b.y2 - b.y1))
      if (w > 0 && h > 0 && w * h > overlap * smaller) found.push(`the labels "${a.label}" and "${b.label}" overlap`)
    }
  return found
}"""

_checking = asyncio.Lock()


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


async def problems(drawings: list[str], small_text: bool = True) -> list[str]:
    """What is wrong with scrubbed drawings (a figure, or the stages of one) laid out at the lesson's width; empty when
    nothing is, or nothing could look. small_text: whether labels under the readable size count."""
    if not available():
        return []
    from playwright.async_api import async_playwright

    from .book import NoBrowser, launch

    found = []
    async with _checking, async_playwright() as p:
        try:
            browser = await launch(p.chromium)
        except NoBrowser:
            return []
        try:
            tab = await browser.new_page()
            await tab.route("**/*", lambda route: route.abort())
            for n, svg in enumerate(drawings):
                await tab.set_content(
                    f'<!doctype html><style>body {{ margin: 0; width: {WIDTH}px; font: 16px "Instrument Sans", "IBM Plex Sans Arabic", sans-serif }} svg {{ width: 100%; height: auto; display: block }}</style>{svg}'
                )
                stage = f"stage {n + 1}: " if len(drawings) > 1 else ""
                found += [stage + f for f in await tab.evaluate(MEASURE, [SMALLEST_PX if small_text else 0, EDGE_SLACK, OVERLAP])]
        finally:
            await browser.close()
    return found


def report(found: list[str]) -> str:
    return "the figure was not shown; fix these and draw it again: " + "; ".join(found[:8])
