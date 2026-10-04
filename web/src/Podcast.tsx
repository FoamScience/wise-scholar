import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

export type PodcastData = {
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
  const { t } = useTranslation()
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
        {d.cues.length ? t('cast.quiz') : t('cast.recap')} · {t('cast.experimental')}
        {d.duration !== null && <span className="small"> · {clock(d.duration)}</span>}
      </div>
      <h2>{props.title}</h2>
      {d.status === 'rendering' && (
        <div className="small">{t('cast.rendering', { done: d.done, total: d.lines.length })}</div>
      )}
      {d.status === 'failed' && <div className="error">{t('cast.failed', { error: d.error })}</div>}
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
      {pending !== null && <div className="hint">{t('cast.paused')}</div>}
      {d.glossary.length > 0 && (
        <div className="targets">
          {d.glossary.map((g) => (
            <span key={g.word} className="chip" lang={d.lang} dir="auto" title={g.meaning}>
              {g.word}
            </span>
          ))}
        </div>
      )}
      <details>
        <summary>{t('cast.transcript')}</summary>
        <div className="transcript" lang={d.lang} dir="auto">
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
