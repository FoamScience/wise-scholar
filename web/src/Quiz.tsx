import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api } from './api'
import { percent } from './i18n'

export type QuizData = {
  card_id: number
  kind: 'choice' | 'open'
  options: string[]
  answer: string | null
  pretest?: boolean
  confidence?: number
  correct?: boolean
  confident_miss?: boolean
  answer_key?: string
  explanation?: string
  feedback?: string
}

type Graded = { correct: boolean; confident_miss: boolean; answer_key: string; explanation: string }
type DueCard = {
  id: number
  topic: string
  question: string
  kind: 'choice' | 'open'
  options: string[]
  confident_miss: boolean
}
type Calibration = {
  n: number
  brier: number | null
  buckets: { label: string; n: number; stated: number | null; actual: number | null }[]
}

function QuizForm(props: {
  id: string
  kind: 'choice' | 'open'
  options: string[]
  disabled: boolean
  onSubmit: (answer: string, confidence: number) => void
}) {
  const { t } = useTranslation()
  const [answer, setAnswer] = useState('')
  const [confidence, setConfidence] = useState(50)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (answer.trim()) props.onSubmit(answer.trim(), confidence / 100)
  }

  return (
    <form className="quiz-form" onSubmit={submit}>
      {props.kind === 'choice' ? (
        <div className="quiz-options">
          {props.options.map((o) => (
            <label key={o} className={o === answer ? 'quiz-option picked' : 'quiz-option'}>
              <input type="radio" name={props.id} checked={o === answer} onChange={() => setAnswer(o)} />
              <Markdown>{o}</Markdown>
            </label>
          ))}
        </div>
      ) : (
        <>
          <label htmlFor={`${props.id}-answer`} className="small">
            {t('common.yourAnswer')}
          </label>
          <textarea
            id={`${props.id}-answer`}
            className="field"
            rows={3}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
          />
        </>
      )}
      <div className="confidence">
        <label htmlFor={`${props.id}-confidence`}>{t('quiz.howSure')}</label>
        <span className="small">{t('quiz.guessing')}</span>
        <input
          id={`${props.id}-confidence`}
          type="range"
          min={0}
          max={100}
          step={5}
          value={confidence}
          onChange={(e) => setConfidence(Number(e.target.value))}
        />
        <span className="small">{t('quiz.certain')}</span>
        <output>{percent(confidence / 100)}</output>
        <button className="btn primary" disabled={props.disabled || !answer.trim()}>
          {t('common.submit')}
        </button>
      </div>
    </form>
  )
}

function QuizResult(props: { answer: string; confidence: number; result: Graded; feedback?: string }) {
  const { result } = props
  const { t } = useTranslation()
  return (
    <div className="quiz-result">
      <div className="attempt">
        <span className="label">{t('quiz.answerSure', { percent: percent(props.confidence) })}</span>
        {props.answer}
      </div>
      <div className={result.correct ? 'solution' : 'hint'}>
        <div className="label">{result.correct ? t('quiz.correct') : t('quiz.notQuite')}</div>
        {!result.correct && <Markdown>{t('quiz.answerKey', { answer: result.answer_key })}</Markdown>}
        <Markdown>{props.feedback || result.explanation}</Markdown>
        {result.confident_miss && (
          <p>{t('quiz.confidentMiss', { percent: percent(props.confidence) })}</p>
        )}
      </div>
    </div>
  )
}

export function QuizCard(props: {
  id: number
  question: string
  data: QuizData
  disabled: boolean
  onSubmit: (answer: string, confidence: number) => void
}) {
  const d = props.data
  const { t } = useTranslation()
  return (
    <section id={`block-${props.id}`} className="block quiz">
      <div className="label">{props.data.pretest ? t('quiz.pretest') : t('quiz.quickCheck')}</div>
      <Markdown>{props.question}</Markdown>
      {d.answer === null ? (
        <QuizForm id={`quiz-${props.id}`} kind={d.kind} options={d.options} disabled={props.disabled} onSubmit={props.onSubmit} />
      ) : d.correct === undefined ? (
        <div className="attempt">
          <span className="label">{t('quiz.grading', { percent: percent(d.confidence!) })}</span>
          {d.answer}
        </div>
      ) : (
        <QuizResult answer={d.answer} confidence={d.confidence!} result={d as Graded} feedback={d.feedback} />
      )}
    </section>
  )
}

export function Review({ profile, then }: { profile: number; then: string | null }) {
  const { t } = useTranslation()
  const [cards, setCards] = useState<DueCard[] | null>(null)
  const [index, setIndex] = useState(0)
  const [given, setGiven] = useState<{ answer: string; confidence: number } | null>(null)
  const [pending, setPending] = useState<{ answer_id: number; answer_key: string; explanation: string } | null>(null)
  const [result, setResult] = useState<Graded | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<DueCard[]>(`/api/reviews?profile=${profile}`).then(setCards, (e) => setError(e.message))
  }, [profile])

  if (!cards) return <main className="home">{error && <div className="error">{error}</div>}</main>

  const card = cards[index]
  if (!card)
    return (
      <main className="home">
        <h1>{cards.length ? t('review.done') : t('review.nothingDue')}</h1>
        {then ? (
          <a className="btn primary as-link" href={then}>
            {t('review.onToNext')}
          </a>
        ) : (
          <a href="#/">{t('review.back')}</a>
        )}
      </main>
    )

  function submit(answer: string, confidence: number) {
    setGiven({ answer, confidence })
    api<Graded | NonNullable<typeof pending>>(`/api/cards/${card.id}/review`, { answer, confidence }).then(
      (res) => ('correct' in res ? setResult(res) : setPending(res)),
      (e: Error) => setError(e.message),
    )
  }

  function selfGrade(correct: boolean) {
    api<Graded>(`/api/answers/${pending!.answer_id}/grade`, { correct }).then(setResult, (e: Error) => setError(e.message))
    setPending(null)
  }

  function next() {
    setGiven(null)
    setResult(null)
    setIndex(index + 1)
  }

  return (
    <main className="home">
      <section className="block quiz">
        <div className="label">
          {t('review.position', { n: index + 1, total: cards.length, topic: card.topic })}
          {card.confident_miss && <span className="chip warn">{t('review.sureAndMissed')}</span>}
        </div>
        <Markdown>{card.question}</Markdown>
        {!given && <QuizForm key={card.id} id={`card-${card.id}`} kind={card.kind} options={card.options} disabled={false} onSubmit={submit} />}
        {given && pending && (
          <div className="quiz-result">
            <div className="attempt">
              <span className="label">{t('quiz.answerSure', { percent: percent(given.confidence) })}</span>
              {given.answer}
            </div>
            <div className="solution">
              <div className="label">{t('review.model')}</div>
              <Markdown>{pending.answer_key}</Markdown>
              <Markdown>{pending.explanation}</Markdown>
            </div>
            <div className="row">
              <button className="btn" onClick={() => selfGrade(false)}>
                {t('review.missed')}
              </button>
              <button className="btn primary" onClick={() => selfGrade(true)}>
                {t('review.right')}
              </button>
            </div>
          </div>
        )}
        {given && result && (
          <>
            <QuizResult answer={given.answer} confidence={given.confidence} result={result} />
            <div className="row">
              <button className="btn primary" onClick={next}>
                {index + 1 < cards.length ? t('common.next') : t('common.finish')}
              </button>
            </div>
          </>
        )}
        {error && <div className="error">{error}</div>}
      </section>
    </main>
  )
}

export function ReviewPanels({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [due, setDue] = useState<DueCard[]>([])
  const [calibration, setCalibration] = useState<Calibration | null>(null)

  useEffect(() => {
    api<DueCard[]>(`/api/reviews?profile=${profile}`).then(setDue, () => {})
    api<Calibration>(`/api/calibration?profile=${profile}`).then(setCalibration, () => {})
  }, [profile])

  const counts = new Map<string, number>()
  for (const c of due) counts.set(c.topic, (counts.get(c.topic) ?? 0) + 1)
  const byTopic = [...counts]

  return (
    <div className="panels">
      <section className="block">
        <div className="label">{t('review.due')}</div>
        {byTopic.length === 0 && <div className="muted">{t('review.nothingDueNow')}</div>}
        {byTopic.map(([topic, count]) => (
          <div key={topic} className="due-row">
            <span>{topic}</span>
            <strong>{count}</strong>
          </div>
        ))}
        {due.length > 0 && (
          <a className="btn primary as-link" href="#/review">
            {t('review.start')}
          </a>
        )}
        <a className="btn as-link" href="#/errors">
          {t('review.errorNotebook')}
        </a>
      </section>

      {calibration && calibration.n > 0 && (
        <section className="block">
          <div className="label">{t('review.calibration')}</div>
          <div className="bars">
            {calibration.buckets
              .filter((b) => b.n > 0)
              .map((b) => (
                <div key={b.label} className="bar-group">
                  <div className="bar-pair">
                    <span className="bar stated" style={{ height: `${b.stated! * 100}%` }} title={t('review.said', { percent: percent(b.stated!) })} />
                    <span className="bar actual" style={{ height: `${b.actual! * 100}%` }} title={t('review.wasRight', { percent: percent(b.actual!) })} />
                  </div>
                  <span className="small">{b.label}</span>
                  <span className="small">{t('review.ofN', { percent: percent(b.actual!), n: b.n })}</span>
                </div>
              ))}
          </div>
          <div className="legend">
            <span>
              <i className="bar stated" /> {t('review.howSure')}
            </span>
            <span>
              <i className="bar actual" /> {t('review.howOften')}
            </span>
          </div>
          <div className="muted">{t('review.brier', { brier: calibration.brier!.toFixed(2), n: calibration.n })}</div>
        </section>
      )}
    </div>
  )
}
