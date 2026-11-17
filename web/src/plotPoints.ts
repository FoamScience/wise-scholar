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
