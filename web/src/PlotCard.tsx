import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme'
import { Limits } from './Figure'
import type { Teaches } from './Figure'

export type Mark = { type: 'line' | 'dot' | 'bar' | 'area' | 'rule' | 'text' | 'rect'; data?: Record<string, unknown>[]; [k: string]: unknown }
type Axis = { label?: string; domain?: [number, number]; grid?: boolean; type?: 'linear' | 'log' | 'sqrt' | 'point' | 'band' }
export type PlotSpec = { x?: Axis; y?: Axis; marks: Mark[]; height?: number }
type PlotData = { spec: PlotSpec; alt: string; teaches?: Teaches }

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
    <section id={`block-${props.id}`} className="block plot">
      <div className="label">{t('block.plot')}</div>
      {props.title && <h2>{props.title}</h2>}
      <PlotBox spec={d.spec} alt={d.alt} />
      <Limits teaches={d.teaches} />
    </section>
  )
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
              return Plot.barY(data, opts)
            case 'area':
              return Plot.areaY(data, opts)
            case 'rule':
              return 'y' in opts ? Plot.ruleY([opts.y as number]) : Plot.ruleX([opts.x as number])
            case 'text':
              return Plot.text(data, opts)
            default:
              return Plot.rect(data, opts)
          }
        })
        const svg = Plot.plot({
          width: Math.min(640, box.current.clientWidth || 640),
          height: spec.height ?? 320,
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
      <div ref={box} className="plot-box" role="img" aria-label={alt} style={error ? undefined : { minHeight: spec.height ?? 320 }} />
      {error && (
        <div className="mermaid-error">
          <pre>{JSON.stringify(spec, null, 1).slice(0, 2000)}</pre>
          <div className="error">{t('block.plotFailed', { error })}</div>
        </div>
      )}
    </>
  )
}
