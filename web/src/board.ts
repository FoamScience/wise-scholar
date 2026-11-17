// A figure played as a whiteboard: its `data-part` groups drawn step by step, strokes traced by a pen, text and icons
// faded in under it, erased parts wiped. The figure shown at rest is the board after its last step.
export type BoardStep = { say: string; draw: string[]; erase: string[] }
export type Run = { cancelled: boolean }

const LEAVES = 'path, line, rect, circle, ellipse, polyline, polygon, text, use, image'
const UNDRAWN = 'defs, marker, symbol, clipPath, mask, pattern'
const MARKERS = ['marker-start', 'marker-mid', 'marker-end']
const ERASE_MS = 300
const FILL_MS = 150
// A part takes about as long as tracing its strokes across the figure's width in this many seconds, within bounds.
const WIDTH_SECONDS = 1.2
const PART_MS = [300, 2400]

export class Cancelled extends Error {}

/** Which of the parts the steps name are on the board after the first `n` steps; the others are not. */
export function onBoard(steps: BoardStep[], n: number): Map<string, boolean> {
  const drawn = new Set(steps.flatMap((s) => s.draw))
  const on = new Map<string, boolean>()
  for (const s of steps) for (const p of [...s.draw, ...s.erase]) on.set(p, !drawn.has(p))
  for (const s of steps.slice(0, n)) {
    for (const p of s.erase) on.set(p, false)
    for (const p of s.draw) on.set(p, true)
  }
  return on
}

function partElements(svg: SVGSVGElement, id: string): SVGElement[] {
  return [...svg.querySelectorAll<SVGElement>(`[data-part="${CSS.escape(id)}"]`)]
}

function leaves(el: SVGElement): SVGGraphicsElement[] {
  const found = el.matches(LEAVES) ? [el] : [...el.querySelectorAll<SVGElement>(LEAVES)]
  return found.filter((e) => !e.parentElement?.closest(UNDRAWN)) as SVGGraphicsElement[]
}

const markers = new WeakMap<Element, [string, string][]>()

function hideMarkers(el: Element) {
  const kept = MARKERS.filter((m) => el.hasAttribute(m)).map((m): [string, string] => [m, el.getAttribute(m)!])
  if (!kept.length) return
  markers.set(el, kept)
  kept.forEach(([m]) => el.removeAttribute(m))
}

function settle(el: SVGElement) {
  el.style.removeProperty('opacity')
  el.style.removeProperty('stroke-dasharray')
  el.style.removeProperty('stroke-dashoffset')
  el.style.removeProperty('fill-opacity')
  markers.get(el)?.forEach(([m, v]) => el.setAttribute(m, v))
  markers.delete(el)
}

/** The board after its first `n` steps, at once: whatever a cut-short drawing left half done is settled. */
export function show(svg: SVGSVGElement, steps: BoardStep[], n: number) {
  for (const [id, on] of onBoard(steps, n)) {
    for (const el of partElements(svg, id)) {
      el.style.visibility = on ? '' : 'hidden'
      settle(el)
      leaves(el).forEach(settle)
    }
  }
  pen(svg).style.display = 'none'
}

function pen(svg: SVGSVGElement): SVGCircleElement {
  let dot = svg.querySelector<SVGCircleElement>(':scope > .board-pen')
  if (!dot) {
    dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    dot.setAttribute('class', 'board-pen')
    dot.setAttribute('r', String((svg.viewBox.baseVal.width || 600) * 0.008))
    dot.style.display = 'none'
    svg.append(dot)
  }
  return dot
}

function animate(ms: number, run: Run, tick: (t: number) => void): Promise<void> {
  return new Promise((done, fail) => {
    const start = performance.now()
    const frame = (now: number) => {
      if (run.cancelled) return fail(new Cancelled())
      const t = Math.min(1, (now - start) / ms)
      tick(t)
      if (t < 1) requestAnimationFrame(frame)
      else done()
    }
    requestAnimationFrame(frame)
  })
}

/** Moves the pen to a point given in the element's own coordinates. */
function penAt(svg: SVGSVGElement, el: SVGGraphicsElement, x: number, y: number) {
  const outer = svg.getScreenCTM()
  const inner = el.getScreenCTM()
  const dot = pen(svg)
  if (!outer || !inner) return void (dot.style.display = 'none')
  const p = new DOMPoint(x, y).matrixTransform(outer.inverse().multiply(inner))
  dot.style.display = ''
  dot.setAttribute('cx', String(p.x))
  dot.setAttribute('cy', String(p.y))
}

function stroked(el: SVGGraphicsElement): number {
  if (!(el instanceof SVGGeometryElement) || getComputedStyle(el).stroke === 'none') return 0
  return el.getTotalLength()
}

async function trace(svg: SVGSVGElement, el: SVGGeometryElement, length: number, ms: number, run: Run) {
  const style = getComputedStyle(el)
  const filled = style.fill !== 'none'
  const fillOpacity = Number.isNaN(Number(style.fillOpacity)) ? 1 : Number(style.fillOpacity)
  hideMarkers(el)
  el.style.strokeDasharray = `${length} ${length}`
  el.style.strokeDashoffset = String(length)
  if (filled) el.style.fillOpacity = '0'
  el.style.removeProperty('opacity')
  await animate(ms, run, (t) => {
    el.style.strokeDashoffset = String(length * (1 - t))
    const p = el.getPointAtLength(length * t)
    penAt(svg, el, p.x, p.y)
  })
  if (filled) await animate(FILL_MS, run, (t) => (el.style.fillOpacity = String(t * fillOpacity)))
  settle(el)
}

async function write(svg: SVGSVGElement, el: SVGGraphicsElement, ms: number, run: Run) {
  const box = el.getBBox()
  await animate(ms, run, (t) => {
    el.style.opacity = String(t)
    penAt(svg, el, box.x + box.width * t, box.y + box.height / 2)
  })
  settle(el)
}

async function drawPart(svg: SVGSVGElement, id: string, run: Run, still: boolean) {
  const all = partElements(svg, id)
  all.forEach((el) => (el.style.visibility = ''))
  if (still) return
  // a part inside this one that a later step draws stays hidden, and takes no time now
  const marks = [...new Set(all.flatMap(leaves))].filter((el) => getComputedStyle(el).visibility !== 'hidden')
  marks.forEach((el) => (el.style.opacity = '0'))
  const weights = marks.map((el) => {
    const length = stroked(el)
    return { el, length, weight: length || Math.max(el.getBBox().width, 1) }
  })
  const total = weights.reduce((sum, w) => sum + w.weight, 0)
  const width = svg.viewBox.baseVal.width || 600
  const ms = Math.min(PART_MS[1], Math.max(PART_MS[0], (total / width) * WIDTH_SECONDS * 1000))
  for (const { el, length, weight } of weights) {
    const share = Math.max(60, (ms * weight) / total)
    if (length) await trace(svg, el as SVGGeometryElement, length, share, run)
    else await write(svg, el, share, run)
  }
}

async function erasePart(svg: SVGSVGElement, id: string, run: Run, still: boolean) {
  const all = partElements(svg, id)
  if (!still) await animate(ERASE_MS, run, (t) => all.forEach((el) => (el.style.opacity = String(1 - t))))
  all.forEach((el) => {
    el.style.visibility = 'hidden'
    el.style.removeProperty('opacity')
  })
}

/** Plays step `n` on a board showing the steps before it; rejects with Cancelled when the run is cancelled. */
export async function play(svg: SVGSVGElement, steps: BoardStep[], n: number, run: Run, still = false) {
  try {
    for (const id of steps[n].erase) await erasePart(svg, id, run, still)
    for (const id of steps[n].draw) partElements(svg, id).forEach((el) => (el.style.visibility = 'hidden'))
    for (const id of steps[n].draw) await drawPart(svg, id, run, still)
  } finally {
    pen(svg).style.display = 'none'
  }
}
