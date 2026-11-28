import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import type { LegendOptions, ScaleOptions } from '@observablehq/plot'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme'
import { Limits } from './Figure'
import type { Teaches } from './Figure'
import { InlineMarkdown } from './Md'
import { PIN_PLOT } from './parts'
import { nearestX, place, pointable, spot, substituted, tidy } from './plotPoints'
import type { Place, Row } from './plotPoints'
import { Button } from '@/components/ui/button'
import { cn } from 'cn'

export type Mark = { type: 'line' | 'dot' | 'bar' | 'area' | 'rule' | 'text' | 'rect'; data?: Record<string, unknown>[]; [k: string]: unknown }
type Axis = { label?: string; domain?: [number, number]; grid?: boolean; type?: 'linear' | 'log' | 'sqrt' | 'point' | 'band' }
export type PlotSpec = { x?: Axis; y?: Axis; marks: Mark[]; height?: number }
type PlotData = { spec: PlotSpec; alt: string; teaches?: Teaches }
function palette(): string[] {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return [v('--teal'), v('--amber'), v('--line-strong'), v('--teal-dark'), v('--amber-ink'), v('--muted')]
}

/** A plot drawn by Observable Plot from a spec the server resolved; axes and text follow the theme through currentColor.
 * A clicked point, or one a link in the lesson names, is pinned with its numbers written out. */
export function PlotCard(props: { id: number; title: string; data: unknown }) {
  const { t } = useTranslation()
  const d = props.data as PlotData
  const [pin, setPin] = useState<Row | null>(null)
  useEffect(() => {
    const onLink = (e: Event) => {
      const { id, x } = (e as CustomEvent<{ id: number; x: number }>).detail
      if (id === props.id) setPin(nearestX(pointable(d.spec).rows, x))
    }
    document.addEventListener(PIN_PLOT, onLink)
    return () => document.removeEventListener(PIN_PLOT, onLink)
  }, [props.id, d.spec])
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.plot')}</div>
      {props.title && <h2 className="m-0 text-lg"><InlineMarkdown>{props.title}</InlineMarkdown></h2>}
      <PlotBox spec={d.spec} alt={d.alt} pin={pin} onPin={setPin} />
      {pin ? <Pinned pin={pin} spec={d.spec} onClear={() => setPin(null)} /> : <div className="text-xs text-muted-foreground print:hidden">{t('block.pinHint')}</div>}
      {d.teaches?.notice && (
        <div className="text-sm text-ink-2" dir="auto">
          <InlineMarkdown>{t('block.notice', { notice: d.teaches.notice })}</InlineMarkdown>
        </div>
      )}
      <Limits teaches={d.teaches} />
    </section>
  )
}

function Pinned({ pin, spec, onClear }: { pin: Row; spec: PlotSpec; onClear: () => void }) {
  const { t, i18n } = useTranslation()
  const format = (v: unknown) => (typeof v === 'number' ? tidy(v).toLocaleString(i18n.language, { maximumSignificantDigits: 4 }) : String(v))
  const rows: [string, unknown][] = [
    [spec.x?.label ?? 'x', pin.x],
    [spec.y?.label ?? 'y', pin.y],
    ...Object.entries(pin).filter(([k]) => !['x', 'y', 'series', 'expr'].includes(k)),
  ]
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-card px-4 py-3 text-sm" aria-live="polite">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{pin.series != null ? format(pin.series) : t('block.pinned')}</span>
        <Button variant="ghost" size="sm" onClick={onClear}>{t('block.pinClear')}</Button>
      </div>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="m-0 font-semibold tabular-nums">{format(value)}</dd>
          </div>
        ))}
      </dl>
      {typeof pin.expr === 'string' && typeof pin.x === 'number' && typeof pin.y === 'number' && (
        <code dir="ltr" className="self-start rounded-sm bg-code px-2 py-1 text-code-foreground">
          {`${substituted(pin.expr, pin.x)} = ${tidy(pin.y)}`}
        </code>
      )}
    </div>
  )
}

type PlotElement = Element & { scale?: (name: string) => { apply: (v: unknown) => number } | undefined }

const MAX_WIDTH = 900
const PIN_RADIUS = 40
const MIN_HEIGHT = 280
const FONT_SIZE = '12px'
const MARGIN_LEFT = 48
const MARGIN_RIGHT = 20
const MARGIN_TOP = 20
const MARGIN_BOTTOM = 36

function heightFor(width: number): number {
  return Math.round(Math.min(440, Math.max(MIN_HEIGHT, width / 2)))
}

type Halo = { fill: string; stroke: string; strokeWidth: number }
// a note's width, and the height of a line of text, as fractions of the plot's frame
type Measure = { width: (text: unknown) => number; line: number }

/** The colour the plot sits on: Plot's background, so its writing, and the tip and crosshair's, can be ringed in it and
 * stay legible over grid, rules and curves. */
function surface(el: Element | null): string {
  for (; el; el = el.parentElement) {
    const bg = getComputedStyle(el).backgroundColor
    if (bg && bg !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(bg)) return bg
  }
  return 'var(--ground)'
}

/** A rule at one value, with its label and value written at the plot's edge when the spec names it. */
function rule(Plot: typeof import('@observablehq/plot'), spec: PlotSpec, opts: Record<string, unknown>, halo: Halo, measure: Measure) {
  const axis = 'y' in opts ? 'y' : 'x'
  const value = opts[axis] as number
  const style = { strokeDasharray: opts.strokeDasharray as string | undefined }
  const line = axis === 'y' ? Plot.ruleY([value], style) : Plot.ruleX([value], style)
  if (!opts.label) return line
  const text = `${opts.label} = ${value.toLocaleString(undefined, { maximumSignificantDigits: 4 })}`
  if (axis === 'x') {
    return Plot.marks(line, Plot.text([value], { x: (v: number) => v, text: () => text, frameAnchor: 'top', lineAnchor: 'bottom', dy: -3, ...place(spec, value, undefined, measure.width(text)), ...halo }))
  }
  const { left, below } = spot(spec, value, measure.width(text), measure.line)
  const where = { frameAnchor: left ? 'left' : 'right', textAnchor: left ? 'start' : 'end', dx: left ? 3 : 0, lineAnchor: below ? 'top' : 'bottom', dy: below ? 3 : -3 } as const
  return Plot.marks(line, Plot.text([value], { y: (v: number) => v, text: () => text, ...where, ...halo }))
}

/** The tutor's notes, each written beside the rules rather than across them and inward from the frame's sides. */
function notes(Plot: typeof import('@observablehq/plot'), spec: PlotSpec, data: Record<string, unknown>[], opts: Record<string, unknown>, halo: Halo, measure: Measure) {
  const field = (channel: string) => (typeof opts[channel] === 'string' ? (opts[channel] as string) : '')
  const groups = new Map<string, { at: Place; rows: Record<string, unknown>[] }>()
  for (const r of data) {
    const at = place(spec, r[field('x')], r[field('y')], measure.width(r[field('text')]))
    const key = [at.textAnchor, at.dx, at.lineAnchor, at.dy].join()
    if (!groups.has(key)) groups.set(key, { at, rows: [] })
    groups.get(key)!.rows.push(r)
  }
  return Plot.marks(...[...groups.values()].map(({ at, rows }) => Plot.text(rows, { ...halo, ...opts, ...at })))
}

/** An axis title above or below the drawing, where it wraps instead of running past a narrow plot. */
function axisTitle(text: string, axis: 'x' | 'y'): HTMLElement {
  const title = document.createElement('div')
  title.className = cn('text-xs leading-snug', axis === 'x' ? 'mt-1 text-end' : 'mb-1')
  const words = document.createElement('bdi')
  words.textContent = text
  title.append(...(axis === 'x' ? [words, ' →'] : ['↑ ', words]))
  return title
}

function buildMarks(Plot: typeof import('@observablehq/plot'), spec: PlotSpec, halo: Halo, measure: Measure, pin?: Row | null) {
  const marks = spec.marks.map((m) => {
    const { type, data = [], expr: _, ...options } = m
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
        return rule(Plot, spec, opts, halo, measure)
      case 'text':
        return notes(Plot, spec, data, opts, halo, measure)
      default:
        return Plot.rect(data, opts)
    }
  })
  const { rows, columns } = pointable(spec)
  if (rows.length) {
    const channels = Object.fromEntries(columns.map((c) => [c, { value: c, label: c === 'series' ? '' : c }]))
    const named = (axis: 'x' | 'y') => ({ value: axis, label: spec[axis]?.label || axis })
    marks.push(Plot.crosshair(rows, { x: 'x', y: 'y' }), Plot.tip(rows, Plot.pointer({ x: named('x'), y: named('y'), channels })))
  }
  if (pin) marks.push(Plot.ruleX([pin], { x: 'x', strokeDasharray: '4,3' }), Plot.dot([pin], { x: 'x', y: 'y', r: 5, fill: 'currentColor' }))
  return marks
}

function plotOptions(spec: PlotSpec, width: number, height: number, marks: ReturnType<typeof buildMarks>) {
  // the axis titles are written outside the SVG, by axisTitle
  return {
    width,
    height,
    marginLeft: MARGIN_LEFT,
    marginRight: MARGIN_RIGHT,
    marginTop: MARGIN_TOP,
    marginBottom: MARGIN_BOTTOM,
    style: { background: 'transparent', color: 'currentColor', fontFamily: 'inherit', fontSize: FONT_SIZE },
    color: { range: palette(), legend: spec.marks.some((m) => 'stroke' in m || 'fill' in m), style: { fontFamily: 'inherit', fontSize: FONT_SIZE } } as ScaleOptions & Omit<LegendOptions, 'legend'>,
    x: { grid: true, ...spec.x, label: null },
    y: { grid: true, ...spec.y, label: null },
    marks,
  }
}

/** The drawing of a resolved spec, with the spec shown when Observable Plot cannot draw it. */
export function PlotBox({ spec, alt, pin, onPin }: { spec: PlotSpec; alt: string; pin?: Row | null; onPin?: (row: Row) => void }) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement | null>(null)
  const drawn = useRef<PlotElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const theme = useTheme()

  useEffect(() => {
    let live = true
    import('@observablehq/plot').then((Plot) => {
      if (!live || !box.current) return
      try {
        const halo = { fill: 'currentColor', stroke: 'var(--plot-background)', strokeWidth: 4 }
        const width = Math.min(MAX_WIDTH, box.current.clientWidth || 640)
        const ctx = document.createElement('canvas').getContext('2d')!
        ctx.font = `${FONT_SIZE} ${getComputedStyle(box.current).fontFamily}`
        const height = spec.height ?? heightFor(width)
        const measure = {
          width: (text: unknown) => ctx.measureText(String(text ?? '')).width / (width - MARGIN_LEFT - MARGIN_RIGHT),
          line: (1.3 * parseFloat(FONT_SIZE)) / (height - MARGIN_TOP - MARGIN_BOTTOM),
        }
        const marks = buildMarks(Plot, spec, halo, measure, pin)
        const plot = Plot.plot(plotOptions(spec, width, height, marks)) as PlotElement
        box.current.replaceChildren(plot)
        drawn.current = plot
        const svg = (plot.tagName === 'svg' ? plot : plot.querySelector(':scope > svg')!) as SVGSVGElement
        svg.style.setProperty('--plot-background', surface(box.current))
        if (spec.y?.label) svg.before(axisTitle(spec.y.label, 'y'))
        if (spec.x?.label) svg.after(axisTitle(spec.x.label, 'x'))
        setError(null)
      } catch (err) {
        setError((err as Error).message)
      }
    })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [spec, theme, pin])

  // Nearest point to the click in screen space, so a tap on a phone pins as well as a mouse click.
  const pick = (e: React.MouseEvent) => {
    const root = drawn.current
    const svg = root?.tagName === 'svg' ? root : root?.querySelector(':scope > svg')
    const xs = root?.scale?.('x')
    const ys = root?.scale?.('y')
    if (!onPin || !svg || !xs || !ys) return
    const frame = svg.getBoundingClientRect()
    const [cx, cy] = [e.clientX - frame.left, e.clientY - frame.top]
    let best: Row | null = null
    let distance = PIN_RADIUS
    for (const r of pointable(spec).rows) {
      const d = Math.hypot(xs.apply(r.x) - cx, ys.apply(r.y) - cy)
      if (d < distance) [best, distance] = [r, d]
    }
    if (best) onPin(best)
  }

  return (
    <>
      <div ref={box} dir="ltr" className="plot-box overflow-x-auto break-inside-avoid" role="img" aria-label={alt} onClick={onPin ? pick : undefined} style={error ? undefined : { minHeight: spec.height ?? MIN_HEIGHT }} />
      {error && (
        <div>
          <pre dir="ltr" className="mb-2 overflow-x-auto rounded-md bg-code px-4 py-3 text-[0.93em] text-code-foreground">{JSON.stringify(spec, null, 1).slice(0, 2000)}</pre>
          <div className="error rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{t('block.plotFailed', { error })}</div>
        </div>
      )}
    </>
  )
}
