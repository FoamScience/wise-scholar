import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme'

type Mark = { type: 'line' | 'dot' | 'bar' | 'area' | 'rule' | 'text' | 'rect'; data?: Record<string, unknown>[]; [k: string]: unknown }
type Axis = { label?: string; domain?: [number, number]; grid?: boolean; type?: 'linear' | 'log' | 'sqrt' | 'point' | 'band' }
type PlotSpec = { x?: Axis; y?: Axis; marks: Mark[]; height?: number }
type PlotData = { spec: PlotSpec; alt: string }

function palette(): string[] {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return [v('--teal'), v('--amber'), v('--line-strong'), v('--teal-dark'), v('--amber-ink'), v('--muted')]
}

/** A plot drawn by Observable Plot from a spec the server resolved; axes and text follow the theme through currentColor. */
export function PlotCard(props: { id: number; title: string; data: unknown }) {
  const { t } = useTranslation()
  const d = props.data as PlotData
  const box = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const theme = useTheme()

  useEffect(() => {
    let live = true
    import('@observablehq/plot').then((Plot) => {
      if (!live || !box.current) return
      try {
        const marks = d.spec.marks.map((m) => {
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
          height: d.spec.height ?? 320,
          marginLeft: 48,
          style: { background: 'transparent', color: 'currentColor', fontFamily: 'inherit' },
          color: { range: palette(), legend: d.spec.marks.some((m) => 'stroke' in m || 'fill' in m) },
          x: { grid: true, ...d.spec.x },
          y: { grid: true, ...d.spec.y },
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
  }, [d, theme])

  return (
    <section id={`block-${props.id}`} className="block plot">
      <div className="label">{t('block.plot')}</div>
      {props.title && <h2>{props.title}</h2>}
      <div ref={box} className="plot-box" role="img" aria-label={d.alt} />
      {error && (
        <div className="mermaid-error">
          <pre>{JSON.stringify(d.spec, null, 1).slice(0, 2000)}</pre>
          <div className="error">{t('block.plotFailed', { error })}</div>
        </div>
      )}
    </section>
  )
}
