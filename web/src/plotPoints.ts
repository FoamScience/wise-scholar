import type { PlotSpec } from './PlotCard'

export type Row = Record<string, unknown>

const POINTED = new Set(['line', 'area', 'dot'])

/** Every point the learner can hover, from all curves and dots at once, so one tip shows the closest of them. */
export function pointable(spec: PlotSpec): { rows: Row[]; columns: string[] } {
  const rows: Row[] = []
  const columns = new Set<string>()
  for (const m of spec.marks) {
    if (!POINTED.has(m.type) || typeof m.x !== 'string' || typeof m.y !== 'string') continue
    const group = typeof m.stroke === 'string' ? m.stroke : typeof m.fill === 'string' ? m.fill : null
    const used = new Set([m.x, m.y, group])
    for (const r of m.data ?? []) {
      const extra = Object.fromEntries(Object.entries(r).filter(([k]) => !used.has(k) && k !== 'series'))
      Object.keys(extra).forEach((k) => columns.add(k))
      const series = group && group in r ? r[group] : (m.label ?? r.series)
      rows.push({ ...extra, series, x: r[m.x], y: r[m.y], ...(typeof m.expr === 'string' && { expr: m.expr }) })
    }
  }
  if (rows.some((r) => r.series != null)) columns.add('series')
  return { rows, columns: [...columns] }
}

/** The point whose x is nearest the asked one, for a link in the lesson text. */
export function nearestX(rows: Row[], x: number): Row | null {
  let best: Row | null = null
  for (const r of rows) {
    if (typeof r.x !== 'number' || typeof r.y !== 'number') continue
    if (!best || Math.abs(r.x - x) < Math.abs((best.x as number) - x)) best = r
  }
  return best
}

/** A sampled number to four significant digits, with floating-point dust around zero shown as zero. */
export function tidy(v: number): number {
  return Math.abs(v) < 1e-12 ? 0 : Number(v.toPrecision(4))
}

/** The curve's expression with the pinned x written in, so the learner sees the one case computed. */
export function substituted(expr: string, x: number): string {
  const value = tidy(x)
  return expr.replace(/\bx\b/g, value < 0 ? `(${value})` : String(value))
}

/** Whether a drawn curve runs through the box x0..x1, y0..y1, in the units of its rows. */
export function crosses(rows: Row[], [x0, x1]: [number, number], [y0, y1]: [number, number]): boolean {
  for (let i = 1; i < rows.length; i++) {
    const [a, b] = [rows[i - 1], rows[i]]
    if (a.series !== b.series || ![a.x, a.y, b.x, b.y].every((v) => typeof v === 'number')) continue
    const [ax, ay, bx, by] = [a.x, a.y, b.x, b.y] as number[]
    const lo = Math.max(Math.min(ax, bx), x0)
    const hi = Math.min(Math.max(ax, bx), x1)
    if (lo > hi) continue
    const at = (x: number) => ay + ((by - ay) * (x - ax)) / (bx - ax)
    const [ya, yb] = ax === bx ? [ay, by] : [at(lo), at(hi)]
    if (Math.max(ya, yb) >= y0 && Math.min(ya, yb) <= y1) return true
  }
  return false
}

export type Place = { textAnchor: 'start' | 'middle' | 'end'; dx: number; lineAnchor?: 'bottom'; dy?: number }

// how close a note is to a rule to count as on it, as a fraction of the axis span; the gap kept from the rule, in px
const ON_RULE = 0.02
const GAP = 6

/** The span an axis shows: its stated domain, else from the smallest to the largest number the marks put on it, with
 * the zero a bar or area is drawn up from. */
export function span(spec: PlotSpec, axis: 'x' | 'y'): [number, number] | null {
  const domain = spec[axis]?.domain
  if (domain) return domain
  let lo = Infinity
  let hi = -Infinity
  for (const m of spec.marks) {
    const values: unknown[] = axis === 'y' && (m.type === 'bar' || m.type === 'area') ? [0] : []
    for (const at of [m[axis], m[`${axis}1`], m[`${axis}2`]]) {
      if (typeof at === 'number') values.push(at)
      else if (typeof at === 'string') values.push(...(m.data ?? []).map((r) => r[at]))
    }
    for (const v of values) if (typeof v === 'number') [lo, hi] = [Math.min(lo, v), Math.max(hi, v)]
  }
  return hi > lo ? [lo, hi] : null
}

const SCALED: Record<string, (n: number) => number> = { log: Math.log, sqrt: (n) => Math.sign(n) * Math.sqrt(Math.abs(n)) }

/** Where a value falls along an axis, through the axis's scale: 0 at the span's start, 1 at its end. */
function fraction(spec: PlotSpec, axis: 'x' | 'y'): ((v: number) => number) | null {
  const s = span(spec, axis)
  if (!s) return null
  const scaled = SCALED[spec[axis]?.type ?? ''] ?? ((n: number) => n)
  const [a, b] = s.map(scaled)
  return (v) => (scaled(v) - a) / (b - a)
}

export type Spot = { left: boolean; below: boolean }

/** Where a horizontal rule's label goes: above it at the frame's right end, unless a curve runs there; then below it,
 * then at the left end. width, height: the label's, as fractions of the frame's. */
export function spot(spec: PlotSpec, value: number, width: number, height: number): Spot {
  const spots: Spot[] = [{ left: false, below: false }, { left: false, below: true }, { left: true, below: false }, { left: true, below: true }]
  const fx = fraction(spec, 'x')
  const fy = fraction(spec, 'y')
  if (!fx || !fy) return spots[0]
  const rows = pointable(spec).rows.map((r) => (typeof r.x === 'number' && typeof r.y === 'number' ? { ...r, x: fx(r.x), y: fy(r.y) } : r))
  const at = fy(value)
  const clear = ({ left, below }: Spot) => !crosses(rows, left ? [0, width] : [1 - width, 1], below ? [at - height, at] : [at, at + height])
  return spots.find(clear) ?? spots[0]
}

type Along = { x: ((v: number) => number) | null; y: ((v: number) => number) | null }

const onRule = (spec: PlotSpec, along: Along, axis: 'x' | 'y', f: number) =>
  spec.marks.some((m) => m.type === 'rule' && typeof m[axis] === 'number' && Math.abs(along[axis]!(m[axis] as number) - f) < ON_RULE)

const where = (along: Along, axis: 'x' | 'y', v: unknown) => (typeof v === 'number' && along[axis] ? along[axis]!(v) : null)

/** How a note at fraction f across the frame is anchored: off a rule it sits on, else inward where it would be cut off. */
function across(f: number, width: number, onIt: boolean): Pick<Place, 'textAnchor' | 'dx'> | null {
  if (onIt) return f + width > 1 && f > 0.5 ? { textAnchor: 'end', dx: -GAP } : { textAnchor: 'start', dx: GAP }
  if (f - width / 2 < 0) return { textAnchor: 'start', dx: 0 }
  if (f + width / 2 > 1) return { textAnchor: 'end', dx: 0 }
  return null
}

/** Where a note at (x, y) is written: beside a vertical rule it would sit on rather than across it, above a horizontal
 * one, and drawn inward at the frame's sides so it is not cut off. width: the note's, as a fraction of the frame's. */
export function place(spec: PlotSpec, x: unknown, y: unknown, width = 0): Place {
  const along = { x: fraction(spec, 'x'), y: fraction(spec, 'y') }
  const placed: Place = { textAnchor: 'middle', dx: 0 }
  const fx = where(along, 'x', x)
  if (fx !== null) Object.assign(placed, across(fx, width, onRule(spec, along, 'x', fx)))
  const fy = where(along, 'y', y)
  if (fy !== null && onRule(spec, along, 'y', fy)) Object.assign(placed, { lineAnchor: 'bottom', dy: -GAP / 2 })
  return placed
}
