import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme'
import { Limits } from './Figure'
import type { Teaches } from './Figure'
import { InlineMarkdown } from './Md'
import { PIN_PLOT } from './parts'
import { nearestX, pointable, substituted, tidy } from './plotPoints'
import type { Row } from './plotPoints'
import { Button } from '@/components/ui/button'

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

const MAX_WIDTH = 900
const PIN_RADIUS = 40
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
export function PlotBox({ spec, alt, pin, onPin }: { spec: PlotSpec; alt: string; pin?: Row | null; onPin?: (row: Row) => void }) {
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
        if (pin) marks.push(Plot.ruleX([pin], { x: 'x', strokeDasharray: '4,3' }), Plot.dot([pin], { x: 'x', y: 'y', r: 5, fill: 'currentColor' }))
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
  }, [spec, theme, pin])

  // Nearest point to the click in screen space, so a tap on a phone pins as well as a mouse click.
  const pick = (e: React.MouseEvent) => {
    const root = box.current?.firstElementChild as (Element & { scale?: (name: string) => { apply: (v: unknown) => number } | undefined }) | null
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
      <div ref={box} dir="ltr" className="plot-box overflow-x-auto break-inside-avoid [&_svg]:[--plot-background:var(--popover)]!" role="img" aria-label={alt} onClick={onPin ? pick : undefined} style={error ? undefined : { minHeight: spec.height ?? MIN_HEIGHT }} />
      {error && (
        <div>
          <pre dir="ltr" className="mb-2 overflow-x-auto rounded-md bg-code px-4 py-3 text-[0.93em] text-code-foreground">{JSON.stringify(spec, null, 1).slice(0, 2000)}</pre>
          <div className="error rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{t('block.plotFailed', { error })}</div>
        </div>
      )}
    </>
  )
}
