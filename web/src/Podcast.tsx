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

const AUDIO_CACHE = 'wise-scholar-audio'
const SKIP_SECONDS = 10
// pressing back this far into a line restarts it; earlier, it goes to the line before
const RESTART_SECONDS = 2
// the cast the lock screen controls: the one that last started playing
let controlled: number | null = null

/** Whether the cast's audio is kept for offline listening, and the actions to keep or drop it; null where the browser has no cache. */
function useKept(src: string | null) {
  const [kept, setKept] = useState<boolean | null>(null)
  useEffect(() => {
    if (!src || !('caches' in window)) return
    let current = true
    caches
      .open(AUDIO_CACHE)
      .then((c) => c.match(src))
      .then(
        (r) => current && setKept(!!r),
        () => current && setKept(null),
      )
    return () => {
      current = false
    }
  }, [src])
  async function keep() {
    await (await caches.open(AUDIO_CACHE)).add(src!)
    // a kept cast would otherwise go when the browser runs short of space
    await navigator.storage?.persist?.()
    setKept(true)
  }
  async function drop() {
    await (await caches.open(AUDIO_CACHE)).delete(src!)
    setKept(false)
  }
  return { kept, keep, drop }
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
  const { kept, keep, drop } = useKept(d.audio)
  const [keepError, setKeepError] = useState('')
  useEffect(
    () => () => {
      // a card that goes away hands the lock screen back, so its buttons do not drive a missing player
      if (controlled !== props.id || !('mediaSession' in navigator)) return
      controlled = null
      navigator.mediaSession.metadata = null
      for (const action of ['play', 'pause', 'seekbackward', 'seekforward', 'previoustrack', 'nexttrack'] as const) navigator.mediaSession.setActionHandler(action, null)
    },
    [props.id],
  )

  /** The lock screen and headset controls follow the cast that last started playing; previous and next go by line. */
  function claimControls() {
    if (!('mediaSession' in navigator)) return
    controlled = props.id
    const seek = (to: number) => {
      if (audio.current) audio.current.currentTime = Math.max(0, to)
    }
    const at = () => audio.current?.currentTime ?? 0
    const current = () => d.starts.filter((s) => s <= at()).length - 1
    navigator.mediaSession.metadata = new MediaMetadata({
      title: props.title,
      artist: 'wise-scholar',
      artwork: [{ src: '/icon-512.png', sizes: '512x512', type: 'image/png' }],
    })
    navigator.mediaSession.setActionHandler('play', () => audio.current?.play().catch(() => {}))
    navigator.mediaSession.setActionHandler('pause', () => audio.current?.pause())
    navigator.mediaSession.setActionHandler('seekbackward', () => seek(at() - SKIP_SECONDS))
    navigator.mediaSession.setActionHandler('seekforward', () => seek(at() + SKIP_SECONDS))
    navigator.mediaSession.setActionHandler('previoustrack', () => {
      const n = current()
      seek(d.starts[n >= 0 && at() - d.starts[n] < RESTART_SECONDS ? n - 1 : n] ?? 0)
    })
    navigator.mediaSession.setActionHandler('nexttrack', () => {
      const next = d.starts[current() + 1]
      if (next !== undefined) seek(next)
    })
  }

  function toggleKept() {
    setKeepError('')
    ;(kept ? drop() : keep()).catch(() => setKeepError(t('cast.keepFailed')))
  }

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
      <h2>{props.title}</h2>
      <div className="small">
        {d.cues.length ? t('cast.quiz') : t('cast.recap')} ({t('cast.experimental')}){d.duration !== null && <>, {clock(d.duration)}</>}
      </div>
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
          onPlay={claimControls}
          style={{ width: '100%' }}
        />
      )}
      {d.audio && kept !== null && (
        <div className="row">
          <button type="button" className="btn" onClick={toggleKept}>
            {kept ? t('cast.drop') : t('cast.keep')}
          </button>
          {kept && <span className="small">{t('cast.kept')}</span>}
        </div>
      )}
      {keepError && <div className="error">{keepError}</div>}
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
