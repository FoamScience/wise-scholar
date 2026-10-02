import { useState } from 'react'
import { splitBy } from './text'

type ReadingData = {
  title: string
  lang: string
  glossary: { word: string; meaning: string }[]
  added: string[]
}
type Strands = { input: number; output: number; language: number; fluency: number }

const CEFR = ['C2', 'C1', 'B2', 'B1', 'A2', 'A1']
const STRAND_LABELS: [keyof Strands, string][] = [
  ['input', 'Reading, listening'],
  ['output', 'Writing'],
  ['language', 'Grammar, words'],
  ['fluency', 'Fluency'],
]

export function ReadingCard(props: { id: number; text: string; data: unknown; onAdd: (word: string) => void }) {
  const d = props.data as ReadingData
  const [word, setWord] = useState<string | null>(null)
  const [shown, setShown] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const gloss = d.glossary.find((g) => g.word === word)

  function listen() {
    speechSynthesis.cancel()
    if (speaking) return setSpeaking(false)
    const utterance = new SpeechSynthesisUtterance(props.text)
    utterance.lang = d.lang
    utterance.onend = () => setSpeaking(false)
    speechSynthesis.speak(utterance)
    setSpeaking(true)
  }

  return (
    <section className="block reading">
      <div className="reading-head">
        <div className="label">Read · tap a marked word for its meaning</div>
        <button type="button" className="btn" onClick={listen}>
          {speaking ? 'Stop' : 'Listen'}
        </button>
      </div>
      <h2 lang={d.lang}>{d.title}</h2>
      {props.text.split(/\n\s*\n/).map((paragraph, i) => (
        <p key={i} lang={d.lang}>
          {splitBy(
            paragraph,
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
          )}
        </p>
      ))}
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
        </div>
      )}
    </section>
  )
}

export function LevelPanel(props: {
  level: string | null
  strands: Strands
  vocabulary: { total: number; due: number }
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
      <a className="btn as-link" href="#/review">
        Vocabulary · {props.vocabulary.due} due of {props.vocabulary.total}
      </a>
    </div>
  )
}
