import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { usePlayer } from './player'
import { splitBy, splitSentences } from './text'

type ReadingData = {
  title: string
  lang: string
  glossary: { word: string; meaning: string }[]
  added: string[]
  targets?: string[]
  known?: string[]
  story?: string
  episode?: number
}
type Strands = { input: number; output: number; language: number; fluency: number }

const CEFR = ['C2', 'C1', 'B2', 'B1', 'A2', 'A1']
const STRANDS = ['input', 'output', 'language', 'fluency'] as const

export function ReadingCard(props: {
  id: number
  text: string
  data: unknown
  speech: boolean
  onAdd: (word: string) => void
  onKnown: (word: string) => void
}) {
  const { t } = useTranslation()
  const d = props.data as ReadingData
  const [word, setWord] = useState<string | null>(null)
  const [shown, setShown] = useState(false)
  const gloss = d.glossary.find((g) => g.word === word)
  const paragraphs = props.text.split(/\n\s*\n/).map(splitSentences)
  const player = usePlayer(d.lang, props.speech)

  return (
    <section id={`block-${props.id}`} className="block reading">
      <div className="reading-head">
        <div className="label">{d.story ? t('reading.story', { story: d.story, n: d.episode }) : t('reading.label')}</div>
        <label className="small">
          <input type="checkbox" checked={player.slow} onChange={(e) => player.setSlow(e.target.checked)} /> {t('reading.slow')}
        </label>
        <button
          type="button"
          className="btn"
          title={props.speech ? t('reading.localVoice') : t('reading.browserVoice')}
          onClick={() => (player.current ? player.stop() : player.play(paragraphs.flat()))}
        >
          {player.current ? t('common.stop') : t('common.listen')}
        </button>
      </div>
      <h2 lang={d.lang}>{d.title}</h2>
      {d.targets && d.targets.length > 0 && (
        <div className="targets">
          <span className="small">{t('reading.targets')}</span>
          {d.targets.map((target) => (
            <span key={target} className="chip" lang={d.lang}>
              {target}
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
            {shown ? ` · ${gloss.meaning}` : ` ${t('reading.guess')}`}
          </span>
          {!shown && (
            <button type="button" className="btn" onClick={() => setShown(true)}>
              {t('reading.showMeaning')}
            </button>
          )}
          <button
            type="button"
            className="btn"
            disabled={d.added.includes(gloss.word)}
            onClick={() => props.onAdd(gloss.word)}
          >
            {d.added.includes(gloss.word) ? t('reading.inVocabulary') : t('reading.addVocabulary')}
          </button>
          <button
            type="button"
            className="btn"
            disabled={(d.known ?? []).includes(gloss.word)}
            onClick={() => props.onKnown(gloss.word)}
          >
            {(d.known ?? []).includes(gloss.word) ? t('reading.known') : t('reading.iKnow')}
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
  const { t } = useTranslation()
  const d = props.data as VocabData
  return (
    <section id={`block-${props.id}`} className="block vocab-check">
      <div className="label">{t('vocab.label')}</div>
      {d.rounds.map((r) => (
        <div key={r.tier} className="small">
          {t('vocab.round', { n: r.tier * TIER_WORDS, known: r.known.length, total: r.words.length })}
        </div>
      ))}
      {d.current && (
        <VocabRoundForm key={d.current.tier} lang={d.lang} round={d.current} disabled={props.disabled} onSubmit={props.onSubmit} />
      )}
      {d.tier && (
        <div>
          {t('vocab.yours')} <span className="chip">{t('vocab.tier', { tier: d.tier })}</span> {t('vocab.working', { n: d.tier * TIER_WORDS })}
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
  const { t } = useTranslation()
  const [ticked, setTicked] = useState<string[]>([])
  const toggle = (w: string) => setTicked((all) => (all.includes(w) ? all.filter((x) => x !== w) : [...all, w]))
  return (
    <>
      <h2>{t('vocab.from', { n: props.round.tier * TIER_WORDS })}</h2>
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
          {t('vocab.iKnow', { known: ticked.length, total: props.round.words.length })}
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
  disabled: boolean
  story: boolean
  onStart: (kind: 'episode' | 'writing') => void
}) {
  const { t } = useTranslation()
  const current = CEFR.find((l) => props.level?.toUpperCase().startsWith(l))
  const done = props.units.filter((u) => (u.mastery ?? 0) >= 2 / 3).length
  const most = Math.max(1, ...Object.values(props.strands))
  const total = Object.values(props.strands).reduce((a, b) => a + b, 0)
  const behind = STRANDS.reduce((low, s) => (props.strands[s] < props.strands[low] ? s : low))

  return (
    <div className="level-panel">
      {current && (
        <div className="ladder">
          {CEFR.map((l) =>
            l === current ? (
              <div key={l} className="rung current">
                <div>
                  <strong>{l}</strong>
                  <span>{t('level.units', { done, total: props.units.length })}</span>
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
      <div className="label">{t('level.byStrand')}</div>
      {STRANDS.map((key) => (
        <div key={key} className="strand">
          <span>{t(`level.${key}`)}</span>
          <span className="strand-bar">
            <i style={{ width: `${(props.strands[key] / most) * 100}%` }} />
          </span>
          <span>{props.strands[key]}</span>
        </div>
      ))}
      {total > 0 && <div className="stats">{t('level.behind', { strand: t(`level.${behind}`) })}</div>}
      {props.vocabulary.tier && (
        <div className="small">
          {t('level.tier', {
            tier: props.vocabulary.tier,
            words: props.vocabulary.tier_words,
            known: props.vocabulary.tier_known,
            size: props.vocabulary.tier_size,
          })}
        </div>
      )}
      <a className="btn as-link" href="#/review">
        {t('level.vocabulary', { due: props.vocabulary.due, total: props.vocabulary.total })}
      </a>
      <div className="row">
        {props.story && (
          <button type="button" className="btn" disabled={props.disabled} onClick={() => props.onStart('episode')}>
            {t('level.nextEpisode')}
          </button>
        )}
        <button type="button" className="btn" disabled={props.disabled} onClick={() => props.onStart('writing')}>
          {t('level.writing')}
        </button>
      </div>
    </div>
  )
}
