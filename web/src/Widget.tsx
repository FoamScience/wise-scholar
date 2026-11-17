import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Drawing, Limits } from './Figure'
import type { Teaches } from './Figure'
import { PlotBox } from './PlotCard'
import type { Mark, PlotSpec } from './PlotCard'
import { InlineMarkdown } from './Md'

type Control = { name: string; label: string; unit: string; values: number[]; start: number }
type Readout = { label: string; unit: string; digits: number }
type WidgetMark = { type: 'line' | 'area' | 'rule'; label: string; xs?: number[]; axis?: 'x' | 'y' }
type State = { readouts: (number | null)[]; marks: ((number | null)[] | number | null)[]; figure?: (number | null)[] }
export type WidgetData = {
  widget: { controls: Control[]; readouts: Readout[]; states: State[]; plot?: { x: PlotSpec['x']; y: PlotSpec['y']; marks: WidgetMark[] }; figure?: string }
  alt: string
  teaches?: Teaches
}

/** The index of a setting among the server's evaluated states: the sliders' positions, the first slider slowest. */
function stateIndex(controls: Control[], at: number[]): number {
  return controls.reduce((index, c, i) => index * c.values.length + at[i], 0)
}

function plotOf(plot: NonNullable<WidgetData['widget']['plot']>, state: State): PlotSpec {
  const marks: Mark[] = []
  plot.marks.forEach((m, i) => {
    const value = state.marks[i]
    if (m.type === 'rule') {
      if (typeof value === 'number') marks.push({ type: 'rule', [m.axis ?? 'y']: value, label: m.label })
      return
    }
    const ys = value as (number | null)[]
    const data = (m.xs ?? []).map((x, k) => ({ x, y: ys[k], series: m.label }))
    marks.push(m.type === 'line' ? { type: 'line', data, x: 'x', y: 'y', stroke: 'series' } : { type: 'area', data, x: 'x', y: 'y', fill: 'series', fillOpacity: 0.3 })
  })
  return { x: plot.x, y: plot.y, marks }
}

// A setting counts as tried once the sliders have stood still this long.
const SETTLE_MS = 1200

/** The server's scrubbed drawing with this setting's numbers in its places; only numbers go in. */
function filled(template: string, values: (number | null)[]): string {
  return template.replace(/__w(\d+)__/g, (_, i: string) => String(values[Number(i)] ?? 0))
}

/** A model the learner operates: sliders pick a setting, readouts and the plot show what the server computed for it.
 * onTry hears each setting the learner stops at. */
export function WidgetCard(props: { id: number; title: string; data: unknown; onTry?: (at: number[]) => void }) {
  const { t, i18n } = useTranslation()
  const d = (props.data as WidgetData).widget
  const starts = d.controls.map((c) => c.start)
  const [at, setAt] = useState(starts)
  const state = d.states[stateIndex(d.controls, at)]
  const plot = useMemo(() => (d.plot ? plotOf(d.plot, state) : null), [d.plot, state])
  const format = (value: number, digits: number) => value.toLocaleString(i18n.language, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const moved = at.some((p, i) => p !== starts[i])
  const touched = useRef(false)
  // The page hands a new callback on every render; only a new setting restarts the wait.
  const onTry = useRef(props.onTry)
  useEffect(() => {
    onTry.current = props.onTry
  })
  useEffect(() => {
    if (!touched.current) return
    const timer = setTimeout(() => onTry.current?.(at), SETTLE_MS)
    return () => clearTimeout(timer)
  }, [at])
  const move = (next: number[]) => {
    touched.current = true
    setAt(next)
  }
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.widget')}</div>
      {props.title && <h2 className="m-0 text-lg"><InlineMarkdown>{props.title}</InlineMarkdown></h2>}
      {d.figure && <Drawing className="figure-box mx-auto w-full max-w-[600px] break-inside-avoid" svg={filled(d.figure, state.figure ?? [])} alt={(props.data as WidgetData).alt} sketched={false} />}
      {plot && <PlotBox spec={plot} alt={(props.data as WidgetData).alt} />}
      <dl className="m-0 flex flex-wrap gap-x-6 gap-y-2" aria-live="polite">
        {d.readouts.map((r, i) => (
          <div key={i}>
            <dt className="text-sm text-muted-foreground"><InlineMarkdown>{r.label}</InlineMarkdown></dt>
            <dd className="m-0 text-lg font-semibold tabular-nums">
              <output>{state.readouts[i] === null ? t('block.widgetUndefined') : `${format(state.readouts[i] as number, r.digits)}${r.unit ? ` ${r.unit}` : ''}`}</output>
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col">
        {d.controls.map((c, i) => {
          const shown = `${c.values[at[i]].toLocaleString(i18n.language, { maximumFractionDigits: 6 })}${c.unit ? ` ${c.unit}` : ''}`
          return (
            <div key={c.name} className="grid grid-cols-[1fr_auto] items-center gap-3 min-[481px]:grid-cols-[minmax(8rem,auto)_1fr_minmax(4rem,auto)]">
              <label htmlFor={`${props.id}-${c.name}`}><InlineMarkdown>{c.label}</InlineMarkdown></label>
              <input
                id={`${props.id}-${c.name}`}
                className="col-span-full row-start-2 h-11 min-w-0 accent-primary min-[481px]:col-auto min-[481px]:row-auto"
                type="range"
                min={0}
                max={c.values.length - 1}
                step={1}
                value={at[i]}
                aria-valuetext={shown}
                onChange={(e) => move(at.map((p, k) => (k === i ? Number(e.target.value) : p)))}
              />
              <output className="tabular-nums" htmlFor={`${props.id}-${c.name}`}>{shown}</output>
            </div>
          )
        })}
      </div>
      <Button variant="outline" size="sm" className="self-start print:hidden" disabled={!moved} onClick={() => move(starts)}>
        {t('block.widgetReset')}
      </Button>
      <Limits teaches={(props.data as WidgetData).teaches} />
    </section>
  )
}
