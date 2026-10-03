import { useEffect, useRef, useState } from 'react'

type PodcastData = {
  lang: string
  speakers: string[]
  lines: { speaker: string; text: string }[]
  glossary: { word: string; meaning: string }[]
  status: 'rendering' | 'ready' | 'failed'
  done: number
  audio: string | null
  starts: number[]
  duration: number | null
  cues: { line: number; block_id: number }[]
  error?: string
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

/** A two-voice cast with a collapsed transcript; a quiz-cast pauses at each cue until its question is answered. */
export function PodcastCard(props: { id: number; title: string; data: unknown; answered: (blockId: number) => boolean }) {
  const d = props.data as PodcastData
  const audio = useRef<HTMLAudioElement | null>(null)
  const paused = useRef(false)
  const [time, setTime] = useState(0)
  const line = d.starts.filter((s) => s <= time).length - 1
  // The first question whose line has played and which is still unanswered holds the cast.
  const pending = d.cues.find((c) => (d.starts[c.line + 1] ?? Infinity) <= time && !props.answered(c.block_id))?.block_id ?? null

  useEffect(() => {
    if (pending !== null) {
      audio.current?.pause()
      document.getElementById(`block-${pending}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } else if (paused.current) {
      audio.current?.play().catch(() => {})
    }
    paused.current = pending !== null
  }, [pending])

  return (
    <section id={`block-${props.id}`} className="block podcast">
      <div className="label">
        {d.cues.length ? 'Quiz-cast' : 'Recap cast'} · experimental
        {d.duration !== null && <span className="small"> · {clock(d.duration)}</span>}
      </div>
      <h2>{props.title}</h2>
      {d.status === 'rendering' && (
        <div className="small">
          Rendering the voices: {d.done} of {d.lines.length} lines…
        </div>
      )}
      {d.status === 'failed' && <div className="error">The cast could not be rendered: {d.error}</div>}
      {d.audio && (
        <audio
          ref={audio}
          controls
          preload="metadata"
          src={d.audio}
          onTimeUpdate={() => setTime(audio.current?.currentTime ?? 0)}
          style={{ width: '100%' }}
        />
      )}
      {pending !== null && <div className="hint">Paused for a question. Answer it below and the cast goes on.</div>}
      {d.glossary.length > 0 && (
        <div className="targets">
          {d.glossary.map((g) => (
            <span key={g.word} className="chip" lang={d.lang} title={g.meaning}>
              {g.word}
            </span>
          ))}
        </div>
      )}
      <details>
        <summary>Transcript</summary>
        <div className="transcript" lang={d.lang}>
          {d.lines.map((l, i) => (
            <p key={i} className={i === line ? 'current' : undefined}>
              <strong>{l.speaker}:</strong> {l.text}
            </p>
          ))}
        </div>
      </details>
    </section>
  )
}
