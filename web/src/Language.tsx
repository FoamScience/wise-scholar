import { useEffect, useRef, useState } from 'react'
import { splitBy, splitSentences } from './text'

type ReadingData = {
  title: string
  lang: string
  glossary: { word: string; meaning: string }[]
  added: string[]
  targets?: string[]
  known?: string[]
}
type Strands = { input: number; output: number; language: number; fluency: number }

const CEFR = ['C2', 'C1', 'B2', 'B1', 'A2', 'A1']
const STRAND_LABELS: [keyof Strands, string][] = [
  ['input', 'Reading, listening'],
  ['output', 'Writing'],
  ['language', 'Grammar, words'],
  ['fluency', 'Fluency'],
]
const SLOW_RATE = 0.8

/** Plays sentences one after another through the local voice, or the browser voice when speech is off. */
function usePlayer(lang: string, local: boolean) {
  const [current, setCurrent] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const [error, setError] = useState('')
  const audio = useRef<HTMLAudioElement | null>(null)
  const slowRef = useRef(false)
  const run = useRef(0)

  function stop() {
    run.current += 1
    audio.current?.pause()
    audio.current = null
    speechSynthesis.cancel()
    setCurrent(null)
  }

  useEffect(() => stop, [])

  function setSlowRate(on: boolean) {
    slowRef.current = on
    setSlow(on)
    if (audio.current) audio.current.playbackRate = on ? SLOW_RATE : 1
  }

  async function play(sentences: string[]) {
    stop()
    const mine = run.current
    setError('')
    const url = (s: string) => `/api/tts?lang=${encodeURIComponent(lang)}&text=${encodeURIComponent(s)}`
    for (let i = 0; i < sentences.length && run.current === mine; i++) {
      setCurrent(sentences[i])
      if (local) {
        if (i + 1 < sentences.length) fetch(url(sentences[i + 1])).catch(() => {})
        const res = await fetch(url(sentences[i])).catch(() => null)
        if (run.current !== mine) return
        if (!res?.ok) {
          setError((await res?.json().catch(() => null))?.detail ?? 'The voice service did not answer.')
          break
        }
        const src = URL.createObjectURL(await res.blob())
        const clip = new Audio(src)
        clip.playbackRate = slowRef.current ? SLOW_RATE : 1
        audio.current = clip
        await new Promise<void>((done) => {
          clip.onended = () => done()
          clip.onerror = () => done()
          clip.play().catch(() => done())
        })
        URL.revokeObjectURL(src)
      } else {
        await new Promise<void>((done) => {
          const u = new SpeechSynthesisUtterance(sentences[i])
          u.lang = lang
          u.rate = slowRef.current ? SLOW_RATE : 1
          u.onend = () => done()
          u.onerror = () => done()
          speechSynthesis.speak(u)
        })
      }
    }
    if (run.current === mine) setCurrent(null)
  }

  return { current, slow, setSlow: setSlowRate, error, play, stop }
}

export function ReadingCard(props: {
  id: number
  text: string
  data: unknown
  speech: boolean
  onAdd: (word: string) => void
  onKnown: (word: string) => void
}) {
  const d = props.data as ReadingData
  const [word, setWord] = useState<string | null>(null)
  const [shown, setShown] = useState(false)
  const gloss = d.glossary.find((g) => g.word === word)
  const paragraphs = props.text.split(/\n\s*\n/).map(splitSentences)
  const player = usePlayer(d.lang, props.speech)

  return (
    <section id={`block-${props.id}`} className="block reading">
      <div className="reading-head">
        <div className="label">Read · tap a marked word for its meaning</div>
        <label className="small">
          <input type="checkbox" checked={player.slow} onChange={(e) => player.setSlow(e.target.checked)} /> slow
        </label>
        <button
          type="button"
          className="btn"
          title={props.speech ? 'Local voice' : 'Browser voice; run make speech for a natural one'}
          onClick={() => (player.current ? player.stop() : player.play(paragraphs.flat()))}
        >
          {player.current ? 'Stop' : 'Listen'}
        </button>
      </div>
      <h2 lang={d.lang}>{d.title}</h2>
      {d.targets && d.targets.length > 0 && (
        <div className="targets">
          <span className="small">Words to meet in this text:</span>
          {d.targets.map((t) => (
            <span key={t} className="chip" lang={d.lang}>
              {t}
            </span>
          ))}
        </div>
      )}
      {paragraphs.map((sentences, i) => (
        <p key={i} lang={d.lang}>
          {sentences.map((sentence, k) => (
            <span key={k} className={sentence === player.current ? 'sentence playing' : 'sentence'}>
              {splitBy(
                sentence,
                d.glossary.map((g) => g.word),
              ).map((piece, j) =>
                piece.hit ? (
                  <button
                    key={j}
                    type="button"
                    className={piece.text === word ? 'gloss open' : 'gloss'}
                    onClick={() => {
                      setWord(piece.text)
                      setShown(false)
                    }}
                  >
                    {piece.text}
                  </button>
                ) : (
                  piece.text
                ),
              )}{' '}
            </span>
          ))}
        </p>
      ))}
      {player.error && <div className="error">{player.error}</div>}
      {gloss && (
        <div className="hint gloss-panel">
          <span className="grow">
            <strong lang={d.lang}>{gloss.word}</strong>
            {shown ? ` · ${gloss.meaning}` : ' · guess from the sentence first'}
          </span>
          {!shown && (
            <button type="button" className="btn" onClick={() => setShown(true)}>
              Show meaning
            </button>
          )}
          <button
            type="button"
            className="btn"
            disabled={d.added.includes(gloss.word)}
            onClick={() => props.onAdd(gloss.word)}
          >
            {d.added.includes(gloss.word) ? 'In your vocabulary' : 'Add to vocabulary'}
          </button>
          <button
            type="button"
            className="btn"
            disabled={(d.known ?? []).includes(gloss.word)}
            onClick={() => props.onKnown(gloss.word)}
          >
            {(d.known ?? []).includes(gloss.word) ? 'Known' : 'I know this'}
          </button>
        </div>
      )}
    </section>
  )
}

export function LevelPanel(props: {
  level: string | null
  strands: Strands
  vocabulary: { total: number; due: number; tier?: number; tier_size?: number; tier_known?: number; tier_words?: number }
  units: { mastery: number | null }[]
}) {
  const current = CEFR.find((l) => props.level?.toUpperCase().startsWith(l))
  const done = props.units.filter((u) => (u.mastery ?? 0) >= 2 / 3).length
  const most = Math.max(1, ...Object.values(props.strands))
  const total = Object.values(props.strands).reduce((a, b) => a + b, 0)
  const behind = STRAND_LABELS.reduce((low, s) => (props.strands[s[0]] < props.strands[low[0]] ? s : low))

  return (
    <div className="level-panel">
      {current && (
        <div className="ladder">
          {CEFR.map((l) =>
            l === current ? (
              <div key={l} className="rung current">
                <div>
                  <strong>{l}</strong>
                  <span>
                    {done} of {props.units.length} units
                  </span>
                </div>
                <progress value={done} max={Math.max(1, props.units.length)} />
              </div>
            ) : (
              <div key={l} className="rung">
                {l}
              </div>
            ),
          )}
        </div>
      )}
      <div className="label">Last 7 days by strand</div>
      {STRAND_LABELS.map(([key, label]) => (
        <div key={key} className="strand">
          <span>{label}</span>
          <span className="strand-bar">
            <i style={{ width: `${(props.strands[key] / most) * 100}%` }} />
          </span>
          <span>{props.strands[key]}</span>
        </div>
      ))}
      {total > 0 && <div className="stats">{behind[1]} is behind. The next unit leans on it.</div>}
      {props.vocabulary.tier && (
        <div className="small">
          Tier {props.vocabulary.tier} · the {props.vocabulary.tier_words} most common words: {props.vocabulary.tier_known} of{' '}
          {props.vocabulary.tier_size} in this tier known
        </div>
      )}
      <a className="btn as-link" href="#/review">
        Vocabulary · {props.vocabulary.due} due of {props.vocabulary.total}
      </a>
    </div>
  )
}
