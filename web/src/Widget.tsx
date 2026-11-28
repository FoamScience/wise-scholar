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

/** The marks of one setting; a pinned one is dashed in its curves' own colours and names its setting in the tip. */
function marksOf(plot: NonNullable<WidgetData['widget']['plot']>, state: State, pinned?: string): Mark[] {
  const marks: Mark[] = []
  const dash = pinned ? { strokeDasharray: '5,4' } : {}
  plot.marks.forEach((m, i) => {
    const value = state.marks[i]
    if (m.type === 'rule') {
      if (typeof value === 'number') marks.push({ type: 'rule', [m.axis ?? 'y']: value, label: pinned ? '' : m.label, ...dash })
      return
    }
    const ys = value as (number | null)[]
    const data = (m.xs ?? []).map((x, k) => ({ x, y: ys[k], series: m.label, ...(pinned && { pinned }) }))
    marks.push(m.type === 'line' ? { type: 'line', data, x: 'x', y: 'y', stroke: 'series', ...dash } : { type: 'area', data, x: 'x', y: 'y', fill: 'series', fillOpacity: pinned ? 0.12 : 0.3 })
  })
  return marks
}

function plotOf(plot: NonNullable<WidgetData['widget']['plot']>, state: State, pinned?: { state: State; setting: string }): PlotSpec {
  const marks = [...(pinned ? marksOf(plot, pinned.state, pinned.setting) : []), ...marksOf(plot, state)]
  return { x: plot.x, y: plot.y, marks }
}

// A setting counts as tried once the sliders have stood still this long.
const SETTLE_MS = 1200

/** The server's scrubbed drawing with this setting's numbers in its places; only numbers go in. */
function filled(template: string, values: (number | null)[]): string {
  return template.replace(/__w(\d+)__/g, (_, i: string) => String(values[Number(i)] ?? 0))
}

/** A value with its unit, in the learner's locale. */
function withUnit(text: string, unit: string): string {
  return unit ? `${text} ${unit}` : text
}

/** One control's setting at a slider position, as shown beside the slider and in the pin's note. */
function settingText(c: Control, position: number, locale: string): string {
  return withUnit(c.values[position].toLocaleString(locale, { maximumFractionDigits: 6 }), c.unit)
}

/** The sliders' positions and the move that marks the learner as having touched them; onTry hears each setting they stop at. */
function useSetting(starts: number[], tried?: (at: number[]) => void) {
  const [at, setAt] = useState(starts)
  const touched = useRef(false)
  // The page hands a new callback on every render; only a new setting restarts the wait.
  const onTry = useRef(tried)
  useEffect(() => {
    onTry.current = tried
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
  return { at, move }
}

/** One readout's value, and under it the pinned setting's value and the difference when the sliders have left the pin. */
function ReadoutItem(props: { r: Readout; value: number | null; pinned?: number | null; format: (value: number, digits: number) => string }) {
  const { t } = useTranslation()
  const { r, value, pinned, format } = props
  const text = (v: number | null) => (v === null ? t('block.widgetUndefined') : withUnit(format(v, r.digits), r.unit))
  const diff = value !== null && pinned != null ? value - pinned : null
  return (
    <div>
      <dt className="text-sm text-muted-foreground"><InlineMarkdown>{r.label}</InlineMarkdown></dt>
      <dd className="m-0 text-lg font-semibold tabular-nums">
        <output>{text(value)}</output>
      </dd>
      {pinned !== undefined && (
        <dd className="m-0 text-sm text-muted-foreground tabular-nums">
          {t('block.widgetPinnedValue', { value: text(pinned) })}
          {diff !== null && <> · Δ {diff >= 0 ? '+' : ''}{format(diff, r.digits)}</>}
        </dd>
      )}
    </div>
  )
}

function Sliders(props: { id: number; controls: Control[]; at: number[]; onMove: (next: number[]) => void }) {
  const { i18n } = useTranslation()
  return (
    <div className="flex flex-col">
      {props.controls.map((c, i) => {
        const shown = settingText(c, props.at[i], i18n.language)
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
              value={props.at[i]}
              aria-valuetext={shown}
              onChange={(e) => props.onMove(props.at.map((p, k) => (k === i ? Number(e.target.value) : p)))}
            />
            <output className="tabular-nums" htmlFor={`${props.id}-${c.name}`}>{shown}</output>
          </div>
        )
      })}
    </div>
  )
}

/** A model the learner operates: sliders pick a setting, readouts and the plot show what the server computed for it.
 * onTry hears each setting the learner stops at. */
export function WidgetCard(props: { id: number; title: string; data: unknown; onTry?: (at: number[]) => void }) {
  const { t, i18n } = useTranslation()
  const d = (props.data as WidgetData).widget
  const starts = d.controls.map((c) => c.start)
  const { at, move } = useSetting(starts, props.onTry)
  const [pin, setPin] = useState<number[] | null>(null)
  const state = d.states[stateIndex(d.controls, at)]
  const format = (value: number, digits: number) => value.toLocaleString(i18n.language, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const settingOf = (positions: number[]) => d.controls.map((c, i) => `${c.label} = ${settingText(c, positions[i], i18n.language)}`).join(', ')
  const pinnedState = pin ? d.states[stateIndex(d.controls, pin)] : null
  const pinnedSetting = pin ? settingOf(pin) : ''
  const plot = useMemo(
    () => (d.plot ? plotOf(d.plot, state, pinnedState ? { state: pinnedState, setting: pinnedSetting } : undefined) : null),
    [d.plot, state, pinnedState, pinnedSetting],
  )
  const pinnedAway = pin !== null && pin.some((p, i) => p !== at[i])
  const moved = at.some((p, i) => p !== starts[i])
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.widget')}</div>
      {props.title && <h2 className="m-0 text-lg"><InlineMarkdown>{props.title}</InlineMarkdown></h2>}
      {d.figure && <Drawing className="figure-box mx-auto w-full max-w-[600px] break-inside-avoid" svg={filled(d.figure, state.figure ?? [])} alt={(props.data as WidgetData).alt} sketched={false} />}
      {plot && <PlotBox spec={plot} alt={(props.data as WidgetData).alt} />}
      <dl className="m-0 flex flex-wrap gap-x-6 gap-y-2" aria-live="polite">
        {d.readouts.map((r, i) => (
          <ReadoutItem key={i} r={r} value={state.readouts[i]} pinned={pinnedState && pinnedAway ? pinnedState.readouts[i] : undefined} format={format} />
        ))}
      </dl>
      <Sliders id={props.id} controls={d.controls} at={at} onMove={move} />
      {pin && <div className="text-sm text-muted-foreground"><InlineMarkdown>{t('block.widgetPinned', { setting: pinnedSetting })}</InlineMarkdown></div>}
      <div className="flex flex-wrap gap-2 print:hidden">
        <Button variant="outline" size="sm" onClick={() => setPin(pin ? null : at)}>
          {pin ? t('block.widgetUnpin') : t('block.widgetPin')}
        </Button>
        <Button variant="outline" size="sm" disabled={!moved} onClick={() => move(starts)}>
          {t('block.widgetReset')}
        </Button>
      </div>
      <Limits teaches={(props.data as WidgetData).teaches} />
    </section>
  )
}
