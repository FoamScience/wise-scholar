import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme'
import { Limits } from './Figure'
import type { Teaches } from './Figure'
import { InlineMarkdown } from './Md'

export type Mark = { type: 'line' | 'dot' | 'bar' | 'area' | 'rule' | 'text' | 'rect'; data?: Record<string, unknown>[]; [k: string]: unknown }
type Axis = { label?: string; domain?: [number, number]; grid?: boolean; type?: 'linear' | 'log' | 'sqrt' | 'point' | 'band' }
export type PlotSpec = { x?: Axis; y?: Axis; marks: Mark[]; height?: number }
type PlotData = { spec: PlotSpec; alt: string; teaches?: Teaches }
type Row = Record<string, unknown>

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
      rows.push({ ...extra, series, x: r[m.x], y: r[m.y] })
    }
  }
  if (rows.some((r) => r.series != null)) columns.add('series')
  return { rows, columns: [...columns] }
}

function palette(): string[] {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return [v('--teal'), v('--amber'), v('--line-strong'), v('--teal-dark'), v('--amber-ink'), v('--muted')]
}

/** A plot drawn by Observable Plot from a spec the server resolved; axes and text follow the theme through currentColor. */
export function PlotCard(props: { id: number; title: string; data: unknown }) {
  const { t } = useTranslation()
  const d = props.data as PlotData
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.plot')}</div>
      {props.title && <h2 className="m-0 text-lg"><InlineMarkdown>{props.title}</InlineMarkdown></h2>}
      <PlotBox spec={d.spec} alt={d.alt} />
      {d.teaches?.notice && (
        <div className="text-sm text-ink-2" dir="auto">
          <InlineMarkdown>{t('block.notice', { notice: d.teaches.notice })}</InlineMarkdown>
        </div>
      )}
      <Limits teaches={d.teaches} />
    </section>
  )
}

const MAX_WIDTH = 900
const MIN_HEIGHT = 280

function heightFor(width: number): number {
  return Math.round(Math.min(440, Math.max(MIN_HEIGHT, width / 2)))
}

/** A rule at one value, with its label and value written at the plot's edge when the spec names it. */
function rule(Plot: typeof import('@observablehq/plot'), opts: Record<string, unknown>) {
  const axis = 'y' in opts ? 'y' : 'x'
  const value = opts[axis] as number
  const line = axis === 'y' ? Plot.ruleY([value]) : Plot.ruleX([value])
  if (!opts.label) return line
  const text = `${opts.label} = ${value.toLocaleString(undefined, { maximumSignificantDigits: 4 })}`
  const label = axis === 'y'
    ? Plot.text([value], { y: (v: number) => v, text: () => text, frameAnchor: 'right', textAnchor: 'end', dy: -6 })
    : Plot.text([value], { x: (v: number) => v, text: () => text, frameAnchor: 'top', textAnchor: 'start', dx: 4 })
  return Plot.marks(line, label)
}

/** The drawing of a resolved spec, with the spec shown when Observable Plot cannot draw it. */
export function PlotBox({ spec, alt }: { spec: PlotSpec; alt: string }) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const theme = useTheme()

  useEffect(() => {
    let live = true
    import('@observablehq/plot').then((Plot) => {
      if (!live || !box.current) return
      try {
        const marks = spec.marks.map((m) => {
          const { type, data = [], ...options } = m
          const opts = options as Record<string, unknown>
          switch (type) {
            case 'line':
              return Plot.lineY(data, opts)
            case 'dot':
              return Plot.dot(data, opts)
            case 'bar':
              return Plot.barY(data, { ...opts, tip: true })
            case 'area':
              return Plot.areaY(data, opts)
            case 'rule':
              return rule(Plot, opts)
            case 'text':
              return Plot.text(data, opts)
            default:
              return Plot.rect(data, opts)
          }
        })
        const { rows, columns } = pointable(spec)
        if (rows.length) {
          const channels = Object.fromEntries(columns.map((c) => [c, { value: c, label: c === 'series' ? '' : c }]))
          marks.push(Plot.crosshair(rows, { x: 'x', y: 'y' }), Plot.tip(rows, Plot.pointer({ x: 'x', y: 'y', channels })))
        }
        const width = Math.min(MAX_WIDTH, box.current.clientWidth || 640)
        const svg = Plot.plot({
          width,
          height: spec.height ?? heightFor(width),
          marginLeft: 48,
          style: { background: 'transparent', color: 'currentColor', fontFamily: 'inherit' },
          color: { range: palette(), legend: spec.marks.some((m) => 'stroke' in m || 'fill' in m) },
          x: { grid: true, ...spec.x },
          y: { grid: true, ...spec.y },
          marks,
        })
        box.current.replaceChildren(svg)
        setError(null)
      } catch (err) {
        setError((err as Error).message)
      }
    })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [spec, theme])

  return (
    <>
      <div ref={box} dir="ltr" className="plot-box overflow-x-auto break-inside-avoid [&_svg]:[--plot-background:var(--popover)]!" role="img" aria-label={alt} style={error ? undefined : { minHeight: spec.height ?? MIN_HEIGHT }} />
      {error && (
        <div>
          <pre dir="ltr" className="mb-2 overflow-x-auto rounded-md bg-code px-4 py-3 text-[0.93em] text-code-foreground">{JSON.stringify(spec, null, 1).slice(0, 2000)}</pre>
          <div className="error rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{t('block.plotFailed', { error })}</div>
        </div>
      )}
    </>
  )
}
