import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Limits } from './Figure'
import type { Teaches } from './Figure'
import { PlotBox } from './PlotCard'
import type { Mark, PlotSpec } from './PlotCard'

type Control = { name: string; label: string; unit: string; values: number[]; start: number }
type Readout = { label: string; unit: string; digits: number }
type WidgetMark = { type: 'line' | 'area' | 'rule'; label: string; xs?: number[]; axis?: 'x' | 'y' }
type State = { readouts: (number | null)[]; marks: ((number | null)[] | number | null)[] }
export type WidgetData = {
  widget: { controls: Control[]; readouts: Readout[]; states: State[]; plot?: { x: PlotSpec['x']; y: PlotSpec['y']; marks: WidgetMark[] } }
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
      if (typeof value === 'number') marks.push({ type: 'rule', [m.axis ?? 'y']: value })
      return
    }
    const ys = value as (number | null)[]
    const data = (m.xs ?? []).map((x, k) => ({ x, y: ys[k], series: m.label }))
    marks.push(m.type === 'line' ? { type: 'line', data, x: 'x', y: 'y', stroke: 'series' } : { type: 'area', data, x: 'x', y: 'y', fill: 'series', fillOpacity: 0.3 })
  })
  return { x: plot.x, y: plot.y, marks }
}

/** A model the learner operates: sliders pick a setting, readouts and the plot show what the server computed for it. */
export function WidgetCard(props: { id: number; title: string; data: unknown }) {
  const { t, i18n } = useTranslation()
  const d = (props.data as WidgetData).widget
  const starts = d.controls.map((c) => c.start)
  const [at, setAt] = useState(starts)
  const state = d.states[stateIndex(d.controls, at)]
  const plot = useMemo(() => (d.plot ? plotOf(d.plot, state) : null), [d.plot, state])
  const format = (value: number, digits: number) => value.toLocaleString(i18n.language, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const moved = at.some((p, i) => p !== starts[i])
  return (
    <section id={`block-${props.id}`} className="block widget">
      <div className="label">{t('block.widget')}</div>
      {props.title && <h2>{props.title}</h2>}
      {plot && <PlotBox spec={plot} alt={(props.data as WidgetData).alt} />}
      <dl className="readouts" aria-live="polite">
        {d.readouts.map((r, i) => (
          <div key={i}>
            <dt>{r.label}</dt>
            <dd>
              <output>{state.readouts[i] === null ? t('block.widgetUndefined') : `${format(state.readouts[i] as number, r.digits)}${r.unit ? ` ${r.unit}` : ''}`}</output>
            </dd>
          </div>
        ))}
      </dl>
      <div className="controls">
        {d.controls.map((c, i) => {
          const shown = `${c.values[at[i]].toLocaleString(i18n.language, { maximumFractionDigits: 6 })}${c.unit ? ` ${c.unit}` : ''}`
          return (
            <div key={c.name} className="control">
              <label htmlFor={`${props.id}-${c.name}`}>{c.label}</label>
              <input
                id={`${props.id}-${c.name}`}
                type="range"
                min={0}
                max={c.values.length - 1}
                step={1}
                value={at[i]}
                aria-valuetext={shown}
                onChange={(e) => setAt(at.map((p, k) => (k === i ? Number(e.target.value) : p)))}
              />
              <output htmlFor={`${props.id}-${c.name}`}>{shown}</output>
            </div>
          )
        })}
      </div>
      <button type="button" className="btn small" disabled={!moved} onClick={() => setAt(starts)}>
        {t('block.widgetReset')}
      </button>
      <Limits teaches={(props.data as WidgetData).teaches} />
    </section>
  )
}
