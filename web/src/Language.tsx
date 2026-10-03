import { useState } from 'react'
import { usePlayer } from './player'
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

type VocabRound = { tier: number; words: string[]; known: string[]; passed: boolean }
type VocabData = { lang: string; rounds: VocabRound[]; current: { tier: number; words: string[] } | null; tier: number | null }
const TIER_WORDS = 200

export function VocabCheckCard(props: { id: number; data: unknown; disabled: boolean; onSubmit: (known: string[]) => void }) {
  const d = props.data as VocabData
  return (
    <section id={`block-${props.id}`} className="block vocab-check">
      <div className="label">Vocabulary check · tick the words whose meaning you could give</div>
      {d.rounds.map((r) => (
        <div key={r.tier} className="small">
          The {r.tier * TIER_WORDS} most common words: {r.known.length} of {r.words.length} known
        </div>
      ))}
      {d.current && (
        <VocabRoundForm key={d.current.tier} lang={d.lang} round={d.current} disabled={props.disabled} onSubmit={props.onSubmit} />
      )}
      {d.tier && (
        <div>
          Your vocabulary: <span className="chip">tier {d.tier}</span> working on the {d.tier * TIER_WORDS} most common words
        </div>
      )}
    </section>
  )
}

function VocabRoundForm(props: {
  lang: string
  round: { tier: number; words: string[] }
  disabled: boolean
  onSubmit: (known: string[]) => void
}) {
  const [ticked, setTicked] = useState<string[]>([])
  const toggle = (w: string) => setTicked((t) => (t.includes(w) ? t.filter((x) => x !== w) : [...t, w]))
  return (
    <>
      <h2>From the {props.round.tier * TIER_WORDS} most common words</h2>
      <div className="options">
        {props.round.words.map((w) => (
          <button
            key={w}
            type="button"
            lang={props.lang}
            className={`btn option${ticked.includes(w) ? ' on' : ''}`}
            aria-pressed={ticked.includes(w)}
            onClick={() => toggle(w)}
          >
            {w}
          </button>
        ))}
      </div>
      <div className="row">
        <button type="button" className="btn primary" disabled={props.disabled} onClick={() => props.onSubmit(ticked)}>
          I know {ticked.length} of {props.round.words.length}
        </button>
      </div>
    </>
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
