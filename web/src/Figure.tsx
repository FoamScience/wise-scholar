import { useState } from 'react'

type FigureData = { svg: string; alt: string }

/** A tutor-drawn SVG: inline so its text follows the theme; click to see it large. */
export function FigureCard(props: { id: number; caption: string; data: unknown }) {
  const d = props.data as FigureData
  const [large, setLarge] = useState(false)
  return (
    <section id={`block-${props.id}`} className="block figure">
      <div className="label">Figure</div>
      <button
        type="button"
        className={large ? 'figure-box large' : 'figure-box'}
        aria-label={large ? 'Shrink the figure' : `Enlarge: ${d.alt}`}
        onClick={() => setLarge(!large)}
      >
        <div role="img" aria-label={d.alt} dangerouslySetInnerHTML={{ __html: d.svg }} />
      </button>
      {props.caption && <div className="caption">{props.caption}</div>}
    </section>
  )
}
