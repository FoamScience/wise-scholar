import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { useTranslation } from 'react-i18next'
import { sketch } from './sketch'

export type Credit = { name: string; author: string; licence: string; pack: string; url: string }
export type FigureData = {
  svg: string
  alt: string
  credits?: Credit[]
  diagram?: { domain: string; substance?: string; stages?: string[] }
  crafted?: { script: string }
  frames?: string[]
  previous?: FigureData & { caption: string }
  restored?: boolean
}

/** The attribution a figure owes the art pack: every icon with its author and licence, and the pack it came from. */
export function Credits({ credits }: { credits?: Credit[] }) {
  const { t } = useTranslation()
  if (!credits?.length) return null
  const packs = [...new Map(credits.map((c) => [c.pack, c.url]))]
  return (
    <div className="credits">
      {t('block.art')} {credits.map((c) => `${c.name} (${c.author}, ${c.licence})`).join(', ')}
      {' · '}
      {packs.map(([pack, url]) => (
        <a key={pack} href={url} target="_blank" rel="noreferrer">
          {pack}
        </a>
      ))}
    </div>
  )
}

/** The SVG inline, so its text follows the theme; sketched in place when the profile asks for it. */
export function Drawing({ svg, alt, sketched, className }: { svg: string; alt: string; sketched: boolean; className?: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = box.current!
    el.innerHTML = svg
    const drawing = el.querySelector('svg')
    if (!sketched || !drawing) return
    try {
      sketch(drawing)
    } catch {
      el.innerHTML = svg // a shape rough.js cannot redraw: the figure is shown as drawn
    }
  }, [svg, sketched])
  return <div ref={box} className={className} role="img" aria-label={alt} />
}

/** Buttons to hold an animation at one of its stages, or let it play; the stage times come from the SVG itself. */
function Stages({ box, count }: { box: React.RefObject<HTMLDivElement | null>; count: number }) {
  const { t } = useTranslation()
  const [held, setHeld] = useState<number | null>(null)
  useEffect(() => {
    // Those who asked for less motion get the first stage, still; the buttons step through the rest.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) hold(0)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  function hold(stage: number | null) {
    const svg = box.current?.querySelector('svg')
    if (!svg) return
    const seconds = Number(svg.getAttribute('data-seconds')) || 3 * count
    if (stage === null) svg.unpauseAnimations()
    else {
      svg.pauseAnimations()
      svg.setCurrentTime((stage / count) * seconds + 0.01)
    }
    setHeld(stage)
  }
  return (
    <div className="stages">
      {Array.from({ length: count }, (_, i) => (
        <button key={i} type="button" className={held === i ? 'btn small primary' : 'btn small'} onClick={() => hold(i)}>
          {t('block.stage', { n: i + 1 })}
        </button>
      ))}
      <button type="button" className={held === null ? 'btn small primary' : 'btn small'} onClick={() => hold(null)}>
        {t('block.play')}
      </button>
    </div>
  )
}

/** A tutor-drawn figure; click to see it large. */
export function FigureCard(props: { id: number; caption: string; data: unknown; sketched: boolean; disabled?: boolean; onRestore?: () => void }) {
  const { t } = useTranslation()
  const d = props.data as FigureData
  const [large, setLarge] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  return (
    <section id={`block-${props.id}`} className="block figure">
      <div className="label">{t('block.figure')}</div>
      <button
        type="button"
        className={large ? 'figure-box large' : 'figure-box'}
        aria-label={large ? t('block.shrinkFigure') : t('block.enlargeFigure', { alt: d.alt })}
        onClick={() => setLarge(!large)}
      >
        <div ref={box}>
          <Drawing svg={d.svg} alt={d.alt} sketched={props.sketched && !d.diagram && !d.crafted} />
        </div>
      </button>
      {d.frames && d.frames.length > 1 && <Stages key={d.svg} box={box} count={d.frames.length} />}
      {props.caption && <div className="caption">{props.caption}</div>}
      <Credits credits={d.credits} />
      {d.previous && props.onRestore && (
        <button type="button" className="link small" disabled={props.disabled} onClick={props.onRestore}>
          {d.restored ? t('block.backToRedrawn') : t('block.restoreDrawing')}
        </button>
      )}
    </section>
  )
}
