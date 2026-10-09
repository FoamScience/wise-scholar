import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { sketch } from './sketch'

export type Credit = { name: string; author: string; licence: string; pack: string; url: string }
export type FigureData = { svg: string; alt: string; credits?: Credit[] }

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

/** A tutor-drawn figure; click to see it large. */
export function FigureCard(props: { id: number; caption: string; data: unknown; sketched: boolean }) {
  const { t } = useTranslation()
  const d = props.data as FigureData
  const [large, setLarge] = useState(false)
  return (
    <section id={`block-${props.id}`} className="block figure">
      <div className="label">{t('block.figure')}</div>
      <button
        type="button"
        className={large ? 'figure-box large' : 'figure-box'}
        aria-label={large ? t('block.shrinkFigure') : t('block.enlargeFigure', { alt: d.alt })}
        onClick={() => setLarge(!large)}
      >
        <Drawing svg={d.svg} alt={d.alt} sketched={props.sketched} />
      </button>
      {props.caption && <div className="caption">{props.caption}</div>}
      <Credits credits={d.credits} />
    </section>
  )
}
