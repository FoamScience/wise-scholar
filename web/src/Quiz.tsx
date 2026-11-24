import { useEffect, useRef, useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from 'cn'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Textarea } from '@/components/ui/textarea'
import Markdown, { AnswerText, InlineMarkdown } from './Md'
import { api } from './api'
import { useArrivals } from './arrive'
import { sortItems } from './course'
import type { SortItem } from './course'
import { number, percent } from './i18n'
import { gradeOffline, placements } from './offline'
import type { Given } from './offline'

export type QuizKind = 'choice' | 'open' | 'sort'

const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const ROW = 'flex flex-wrap items-center justify-end gap-2'
const CHIP = 'h-auto rounded-sm bg-accent px-2 py-0.5 text-base text-accent-foreground'
const WARN = 'h-auto rounded-sm bg-warm-tint px-2 py-0.5 text-base text-warm'
const ATTEMPT = 'attempt flex flex-col gap-0.5 rounded-md bg-secondary px-4 py-3 whitespace-pre-wrap print:break-inside-avoid'
const SOLUTION = 'solution rounded-md bg-accent px-4 py-3 print:break-inside-avoid [&>:last-child]:mb-0'
const HINT = 'hint rounded-md bg-warm-tint px-4 py-3 text-warm-ink print:break-inside-avoid [&>:last-child]:mb-0'
const ERROR = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const OPTION = 'flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 [&_p]:m-0'
const PICKED = 'border-primary bg-accent'
const BLOCK = 'block border-t pt-6 first:border-t-0 first:pt-0'
const RESULT = 'quiz-result flex flex-col gap-3 [&_p]:mt-1 [&_p]:mb-0'
const SORT_OUTCOME = 'm-0 flex list-none flex-col gap-2 p-0 [&_li]:flex [&_li]:flex-wrap [&_li]:items-center [&_li]:gap-2 [&_li_p]:m-0'
const QUIZ = 'flex flex-col gap-3 [&>.prose>p]:m-0 [&>.prose>p]:font-medium'
const QUIZ_HEAD = cn(LABEL, 'flex flex-wrap items-center gap-3')
const PANEL = 'block flex flex-col gap-3 border-t pt-6 first:border-t-0 first:pt-0'
const PAGE = 'mx-auto flex w-full max-w-(--measure) flex-col gap-10 px-6 pt-10 pb-16'

export type QuizData = {
  card_id: number
  kind: QuizKind
  options: string[] | SortItem[]
  categories?: string[]
  misplaced?: string[]
  answer: string | null
  translation?: string
  pretest?: boolean
  number?: number
  of?: number
  unknown?: boolean
  confidence?: number
  correct?: boolean
  confident_miss?: boolean
  answer_key?: string
  explanation?: string
  misconceptions?: Record<string, string>
  feedback?: string
}

export type Graded = { correct: boolean; confident_miss: boolean; answer_key: string; explanation: string; misplaced?: string[]; misconception?: string }
type DueCard = {
  id: number
  topic: string
  question: string
  kind: QuizKind
  options: string[] | SortItem[]
  categories?: string[]
  translation: string
  context: string
  confident_miss: boolean
}

/** Each item with a row of category buttons; the answer is the placement map as JSON. */
function SortForm(props: { items: SortItem[]; categories: string[]; placed: Record<string, string>; onPlace: (item: string, category: string) => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2">
      <div className={SMALL}>{t('quiz.placeEach')}</div>
      {props.items.map((item) => (
        <div key={item.text} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-md border px-3 py-2 [&_p]:m-0">
          <Markdown>{item.text}</Markdown>
          <div className="flex flex-wrap gap-2" role="group" aria-label={item.text}>
            {props.categories.map((c) => (
              <Button
                type="button"
                variant="outline"
                key={c}
                aria-pressed={props.placed[item.text] === c}
                className={cn('h-auto min-h-9 rounded-md bg-transparent px-3 py-1 text-base font-normal', props.placed[item.text] === c && PICKED)}
                onClick={() => props.onPlace(item.text, c)}
              >
                {c}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** A graded sort: every item with where it went, the misplaced ones marked. */
export function SortOutcome({ items, answer, misplaced }: { items: SortItem[]; answer: string; misplaced?: string[] }) {
  const { t } = useTranslation()
  const placed = placements(answer)
  const wrong = new Set(misplaced ?? [])
  return (
    <ul className={SORT_OUTCOME}>
      {items.map((item) => (
        <li key={item.text}>
          <Markdown>{item.text}</Markdown>
          <Badge variant="secondary" className={wrong.has(item.text) ? WARN : CHIP}>{placed[item.text] ?? '?'}</Badge>
          {wrong.has(item.text) && <span className={SMALL}>{t('quiz.misplaced')}</span>}
        </li>
      ))}
    </ul>
  )
}
type Calibration = {
  n: number
  brier: number | null
  buckets: { label: string; n: number; stated: number | null; actual: number | null }[]
}

export function Translation({ text, open }: { text?: string; open?: boolean }) {
  const { t } = useTranslation()
  if (!text) return null
  return (
    <details className="[&>:last-child]:mt-2 [&>:last-child]:mb-0 [&>:last-child]:text-muted-foreground" open={open}>
      <summary className="cursor-pointer text-sm text-muted-foreground">{t('quiz.translation')}</summary>
      <Markdown>{text}</Markdown>
    </details>
  )
}

function ChoiceOptions(props: { name: string; options: string[]; answer: string; unknown: boolean | null; onPick: (option: string) => void; onUnknown: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2">
      {props.options.map((o) => (
        <label key={o} className={cn(OPTION, o === props.answer && PICKED)}>
          <input type="radio" className="accent-primary" name={props.name} checked={o === props.answer} onChange={() => props.onPick(o)} />
          <Markdown>{o}</Markdown>
        </label>
      ))}
      {props.unknown !== null && (
        <label className={cn(OPTION, 'border-dashed text-muted-foreground', props.unknown && PICKED)}>
          <input type="radio" className="accent-primary" name={props.name} checked={props.unknown} onChange={props.onUnknown} />
          {t('quiz.dontKnow')}
        </label>
      )}
    </div>
  )
}

/** How sure the learner is, from guessing to certain; null when they said they don't know. */
function Confidence(props: { id: string; value: number | null; onChange: (value: number) => void; ready: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <label id={`${props.id}-confidence-label`} className="basis-full font-medium">{t('quiz.howSure')}</label>
      <span className={cn(SMALL, 'shrink-0')}>{t('quiz.guessing')}</span>
      <Slider
        id={`${props.id}-confidence`}
        aria-labelledby={`${props.id}-confidence-label`}
        className="flex min-h-11 w-auto min-w-32 flex-1 items-center"
        min={0}
        max={100}
        step={5}
        value={[props.value ?? 0]}
        disabled={props.value === null}
        onValueChange={(v) => props.onChange(Array.isArray(v) ? v[0] : v)}
      />
      <span className={cn(SMALL, 'shrink-0')}>{t('quiz.certain')}</span>
      <div className="ms-auto flex items-center gap-3">
        <output className="w-11 tabular-nums">{percent((props.value ?? 0) / 100)}</output>
        <Button type="submit" disabled={!props.ready}>
          {t('common.submit')}
        </Button>
      </div>
    </div>
  )
}

function QuizForm(props: {
  id: string
  kind: QuizKind
  options: string[] | SortItem[]
  categories?: string[]
  disabled: boolean
  onUnknown?: () => void
  onSubmit: (answer: string, confidence: number) => void
}) {
  const { answer, setAnswer, unknown, setUnknown, placed, setPlaced, items, sorted, ready } = useQuizAnswer(props.kind, props.options)
  const [confidence, setConfidence] = useState(50)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (unknown) props.onUnknown!()
    else if (sorted) props.onSubmit(JSON.stringify(placed), confidence / 100)
    else if (answer.trim()) props.onSubmit(answer.trim(), confidence / 100)
  }

  function pick(option: string) {
    setAnswer(option)
    setUnknown(false)
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      {props.kind === 'sort' ? (
        <SortForm items={items} categories={props.categories ?? []} placed={placed} onPlace={(item, c) => setPlaced({ ...placed, [item]: c })} />
      ) : props.kind === 'choice' ? (
        <ChoiceOptions
          name={props.id}
          options={props.options as string[]}
          answer={answer}
          unknown={props.onUnknown ? unknown : null}
          onPick={pick}
          onUnknown={() => {
            setAnswer('')
            setUnknown(true)
          }}
        />
      ) : (
        <OpenAnswer id={props.id} answer={answer} onAnswer={setAnswer} />
      )}
      <Confidence id={props.id} value={unknown ? null : confidence} onChange={setConfidence} ready={!props.disabled && ready} />
    </form>
  )
}

/** The answer taking shape: typed or picked, "I don't know", or every item sorted into a category. */
function useQuizAnswer(kind: QuizKind, options: string[] | SortItem[]) {
  const [answer, setAnswer] = useState('')
  const [unknown, setUnknown] = useState(false)
  const [placed, setPlaced] = useState<Record<string, string>>({})
  const items = kind === 'sort' ? sortItems(options) : []
  const sorted = kind === 'sort' && items.length > 0 && items.every((i) => placed[i.text])
  const ready = unknown || sorted || (kind !== 'sort' && answer.trim() !== '')
  return { answer, setAnswer, unknown, setUnknown, placed, setPlaced, items, sorted, ready }
}

function OpenAnswer(props: { id: string; answer: string; onAnswer: (answer: string) => void }) {
  const { t } = useTranslation()
  return (
    <>
      <label htmlFor={`${props.id}-answer`} className={SMALL}>
        {t('common.yourAnswer')}
      </label>
      <Textarea
        id={`${props.id}-answer`}
        className="min-h-11 py-3 leading-snug hover:enabled:border-foreground" dir="auto"
        rows={3}
        value={props.answer}
        onChange={(e) => props.onAnswer(e.target.value)}
      />
    </>
  )
}

export function QuizResult(props: { answer: string; confidence: number; result: Graded; feedback?: string; unknown?: boolean; items?: SortItem[]; picked?: boolean }) {
  const { result } = props
  const { t } = useTranslation()
  return (
    <div className={RESULT}>
      <div className={ATTEMPT}>
        <span className={LABEL}>
          {props.unknown ? t('common.yourAnswer') : t('quiz.answerSure', { percent: percent(props.confidence) })}
        </span>
        <GivenAnswer answer={props.answer} unknown={props.unknown} items={props.items} misplaced={result.misplaced} picked={props.picked} />
      </div>
      <div className={result.correct ? SOLUTION : HINT}>
        <div className={cn(LABEL, !result.correct && 'text-warm')}>{result.correct ? t('quiz.correct') : t('quiz.notQuite')}</div>
        {!result.correct && !props.items && <Markdown>{t('quiz.answerKey', { answer: result.answer_key })}</Markdown>}
        <Markdown>{props.feedback || result.explanation}</Markdown>
        {result.misconception && <p><InlineMarkdown>{t('quiz.belief', { belief: result.misconception })}</InlineMarkdown></p>}
        {result.confident_miss && (
          <p>{t('quiz.confidentMiss', { percent: percent(props.confidence) })}</p>
        )}
      </div>
    </div>
  )
}

function GivenAnswer(props: { answer: string; unknown?: boolean; items?: SortItem[]; misplaced?: string[]; picked?: boolean }) {
  const { t } = useTranslation()
  if (props.unknown) return t('quiz.dontKnow')
  if (props.items) return <SortOutcome items={props.items} answer={props.answer} misplaced={props.misplaced} />
  return <AnswerText text={props.answer} picked={props.picked} />
}

/** An answered card: still being graded, or its result. */
export function GradedAnswer({ data: d }: { data: QuizData }) {
  const { t } = useTranslation()
  if (d.correct === undefined)
    return (
      <div className={ATTEMPT}>
        <span className={LABEL}>{t('quiz.grading', { percent: percent(d.confidence!) })}</span>
        <AnswerText text={d.answer!} picked={d.kind === 'choice'} />
      </div>
    )
  return <QuizResult picked={d.kind === 'choice'} answer={d.answer!} confidence={d.confidence!} result={d as Graded} feedback={d.feedback} unknown={d.unknown} items={d.kind === 'sort' ? sortItems(d.options) : undefined} />
}

/** The model answer beside the learner's, for them to say whether they had it. */
function SelfGrade(props: { answer: string; confidence: number; answerKey: string; explanation?: string; disabled?: boolean; onGrade: (correct: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <div className={RESULT}>
      <div className={ATTEMPT}>
        <span className={LABEL}>{t('quiz.answerSure', { percent: percent(props.confidence) })}</span>
        <AnswerText text={props.answer} />
      </div>
      <div className={SOLUTION}>
        <div className={LABEL}>{t('review.model')}</div>
        <Markdown>{props.answerKey}</Markdown>
        <Markdown>{props.explanation ?? ''}</Markdown>
      </div>
      <div className={ROW}>
        <Button variant="outline" disabled={props.disabled} onClick={() => props.onGrade(false)}>
          {t('review.missed')}
        </Button>
        <Button disabled={props.disabled} onClick={() => props.onGrade(true)}>
          {t('review.right')}
        </Button>
      </div>
    </div>
  )
}

/** A prepared course's card as its teacher sees it: the options with their beliefs, the key and the explanation. */
function AuthoredKey({ data: d }: { data: QuizData }) {
  const { t } = useTranslation()
  return (
    <div className={SOLUTION}>
      {d.kind === 'sort' ? (
        <ul className={SORT_OUTCOME}>
          {sortItems(d.options).map((o) => (
            <li key={o.text}>
              <Markdown>{o.text}</Markdown>
              <Badge variant="secondary" className={CHIP}>{o.category ?? '?'}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        d.options.length > 0 && (
          <ul className="m-0 flex flex-col gap-2 ps-6 [&_p]:m-0">
            {(d.options as string[]).map((o) => (
              <li key={o} className={o === d.answer_key ? 'font-semibold' : undefined}>
                <Markdown>{o}</Markdown>
                {d.misconceptions?.[o] && <p><InlineMarkdown>{t('quiz.belief', { belief: d.misconceptions[o] })}</InlineMarkdown></p>}
              </li>
            ))}
          </ul>
        )
      )}
      {d.kind !== 'sort' && (
        <>
          <div className={LABEL}>{t('quiz.key')}</div>
          <Markdown>{d.answer_key ?? ''}</Markdown>
        </>
      )}
      {d.explanation && <Markdown>{d.explanation}</Markdown>}
    </div>
  )
}

/** A card of a lesson prepared for offline: answered and graded on the device, sent with the others later. */
function OfflineAnswer(props: { id: number; data: QuizData; given?: Given; onGive: (given: Given) => void }) {
  const { t } = useTranslation()
  const { data: d, given } = props
  if (!given)
    return <QuizForm id={`quiz-${props.id}`} kind={d.kind} options={d.options} categories={d.categories} disabled={false} onSubmit={(answer, confidence) => props.onGive({ answer, confidence })} />
  const result = gradeOffline(d, given)
  if (!result)
    return (
      <SelfGrade
        answer={given.answer}
        confidence={given.confidence}
        answerKey={d.answer_key ?? ''}
        explanation={d.explanation}
        onGrade={(correct) => props.onGive({ ...given, self_correct: correct })}
      />
    )
  return (
    <>
      <QuizResult picked={d.kind === 'choice'} answer={given.answer} confidence={given.confidence} result={result} items={d.kind === 'sort' ? sortItems(d.options) : undefined} />
      <div className={SMALL}>{t('offline.kept')}</div>
    </>
  )
}

type QuizCardProps = {
  id: number
  question: string
  data: QuizData
  disabled: boolean
  authored?: boolean
  offline?: { given?: Given; onGive: (given: Given) => void }
  onUnknown?: () => void
  onSelfGrade?: (correct: boolean) => void
  onSubmit: (answer: string, confidence: number) => void
}

export function QuizCard(props: QuizCardProps) {
  const d = props.data
  const { t } = useTranslation()
  return (
    <section id={`block-${props.id}`} className={`${BLOCK} ${QUIZ}`}>
      <div className={QUIZ_HEAD}>
        {props.data.pretest ? t('quiz.pretest') : d.kind === 'sort' ? t('quiz.sort') : t('quiz.quickCheck')}
        {d.number !== undefined && <span className="ms-auto text-muted-foreground tabular-nums">{t('quiz.numbered', { number: d.number, of: d.of })}</span>}
      </div>
      <Markdown>{props.question}</Markdown>
      <Translation text={d.translation} />
      <QuizBody {...props} />
    </section>
  )
}

/** The key for its author, the form while unanswered, the self-grade for an answer without a verdict, else the grade. */
function QuizBody(props: QuizCardProps) {
  const d = props.data
  if (props.authored) return <AuthoredKey data={d} />
  if (d.answer === null && props.offline) return <OfflineAnswer id={props.id} data={d} given={props.offline.given} onGive={props.offline.onGive} />
  if (d.answer === null)
    return (
      <QuizForm
        id={`quiz-${props.id}`}
        kind={d.kind}
        options={d.options}
        categories={d.categories}
        disabled={props.disabled}
        onUnknown={props.onUnknown}
        onSubmit={props.onSubmit}
      />
    )
  if (d.correct === undefined && props.onSelfGrade && d.answer_key !== undefined)
    return <SelfGrade answer={d.answer} confidence={d.confidence!} answerKey={d.answer_key} explanation={d.explanation} disabled={props.disabled} onGrade={props.onSelfGrade} />
  return <GradedAnswer data={d} />
}

// the warm-up leaves no history entry: going back from the lesson returns to where the learner came from
const goOn = (then: string) => (e: MouseEvent) => {
  e.preventDefault()
  location.replace(then)
}

function ReviewEnd(props: { total: number; left: number; then: string | null; onMore: () => void }) {
  const { t } = useTranslation()
  const { left, then } = props
  return (
    <main className={PAGE}>
      <h1 className="m-0 max-w-none">{left > 0 ? t('review.timeUp') : props.total ? t('review.done') : t('review.nothingDue')}</h1>
      {left > 0 && <p className="text-muted-foreground">{t('review.left', { count: left })}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {then ? (
          <a className={buttonVariants()} href={then} onClick={goOn(then)}>
            {t('review.onToNext')}
          </a>
        ) : (
          <a className={buttonVariants({ variant: 'outline' })} href="#/">{t('review.back')}</a>
        )}
        {left > 0 && (
          <Button type="button" variant="outline" onClick={props.onMore}>
            {t('review.more')}
          </Button>
        )}
      </div>
    </main>
  )
}

/** A choice card in review: graded the moment an option is picked. */
function ReviewChoice(props: { options: string[]; picked: string | null; result: Graded | null; onPick: (option: string) => void; onNext: () => void }) {
  const { t } = useTranslation()
  const { result, picked } = props
  return (
    <>
      <div className="flex flex-col gap-2">
        {props.options.map((o) => (
          <Button
            key={o}
            type="button"
            variant="outline"
            className={cn(
              OPTION,
              'h-auto w-full justify-start bg-card text-start text-base font-normal whitespace-normal text-foreground hover:bg-card hover:enabled:border-primary disabled:cursor-default disabled:opacity-100',
              result && (o === result.answer_key ? PICKED : o === picked && 'border-destructive text-muted-foreground'),
            )}
            disabled={picked !== null}
            onClick={() => props.onPick(o)}
          >
            <Markdown>{o}</Markdown>
          </Button>
        ))}
      </div>
      {result && (
        <>
          {!result.correct && <Markdown>{result.explanation}</Markdown>}
          {result.misconception && <p><InlineMarkdown>{t('quiz.belief', { belief: result.misconception })}</InlineMarkdown></p>}
          <div className={ROW}>
            <Button onClick={props.onNext}>
              {t('common.next')}
            </Button>
          </div>
        </>
      )}
    </>
  )
}

/** An open card in review: the answer is shown on request and the learner says whether they knew it. */
function ReviewOpen(props: { shown: { answer_key: string; explanation: string } | null; onShow: () => void; onKnew: (correct: boolean) => void }) {
  const { t } = useTranslation()
  if (!props.shown) {
    return (
      <div className={ROW}>
        <Button onClick={props.onShow}>
          {t('review.showAnswer')}
        </Button>
      </div>
    )
  }
  return (
    <>
      <div className={SOLUTION}>
        <Markdown>{props.shown.answer_key}</Markdown>
        <Markdown>{props.shown.explanation}</Markdown>
      </div>
      <div className={ROW}>
        <Button variant="outline" onClick={() => props.onKnew(false)}>
          {t('review.didnt')}
        </Button>
        <Button onClick={() => props.onKnew(true)}>
          {t('review.knewIt')}
        </Button>
      </div>
    </>
  )
}

function ReviewHead(props: { card: DueCard; n: number; total: number; then: string | null }) {
  const { t } = useTranslation()
  const { card, then } = props
  return (
    <div className={QUIZ_HEAD}>
      <span dir="auto">{card.topic}</span>
      <span className="text-muted-foreground">{t('review.position', { n: props.n, total: props.total })}</span>
      {card.confident_miss && <Badge variant="secondary" className={WARN}>{t('review.sureAndMissed')}</Badge>}
      {then && (
        <a className={cn(buttonVariants({ variant: 'outline' }), 'ms-auto whitespace-normal')} href={then} onClick={goOn(then)}>
          {t('review.skipWarmup')}
        </a>
      )}
    </div>
  )
}

// a review sitting is a short box of time; whatever is still due waits for the next one
const REVIEW_BOX_MS = 3 * 60 * 1000

export function Review({ profile, then }: { profile: number; then: string | null }) {
  const [cards, setCards] = useState<DueCard[] | null>(null)
  const [index, setIndex] = useState(0)
  const [started, setStarted] = useState(() => Date.now())
  const [over, setOver] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  const [shown, setShown] = useState<{ answer_id: number; answer_key: string; explanation: string } | null>(null)
  const [result, setResult] = useState<Graded | null>(null)
  const [error, setError] = useState('')
  const box = useRef<HTMLElement>(null)
  useArrivals(box, cards !== null)

  useEffect(() => {
    api<DueCard[]>(`/api/reviews?profile=${profile}${then ? '&warmup=true' : ''}`).then(setCards, (e) => setError(e.message))
  }, [profile, then])

  if (!cards) return <main className={PAGE}>{error && <div className={ERROR}>{error}</div>}</main>

  const card = over ? undefined : cards[index]
  if (!card) {
    return (
      <ReviewEnd
        total={cards.length}
        left={cards.length - index}
        then={then}
        onMore={() => {
          setStarted(Date.now())
          setOver(false)
        }}
      />
    )
  }

  function pick(option: string) {
    setPicked(option)
    api<{ answer_id: number } & Graded>(`/api/cards/${card!.id}/review`, { answer: option }).then(setResult, (e: Error) => setError(e.message))
  }

  function show() {
    api<NonNullable<typeof shown>>(`/api/cards/${card!.id}/review`, {}).then(setShown, (e: Error) => setError(e.message))
  }

  function knew(correct: boolean) {
    api<Graded>(`/api/answers/${shown!.answer_id}/grade`, { correct }).then(next, (e: Error) => setError(e.message))
  }

  function next() {
    setPicked(null)
    setShown(null)
    setResult(null)
    setIndex(index + 1)
    if (Date.now() - started >= REVIEW_BOX_MS) setOver(true)
  }

  return (
    <main ref={box} className={PAGE}>
      <section key={card.id} className={`${BLOCK} ${QUIZ}`}>
        <ReviewHead card={card} n={index + 1} total={cards.length} then={then} />
        <div className="h-[3px] overflow-hidden rounded-[2px] bg-border" aria-hidden="true">
          <span className="block h-full origin-left animate-[review-time_linear_forwards] bg-primary rtl:origin-right" style={{ animationDuration: `${REVIEW_BOX_MS}ms`, animationDelay: `-${Date.now() - started}ms` }} />
        </div>
        <Markdown>{card.question}</Markdown>
        {card.context && <blockquote dir="auto" className="m-0 border-s-2 ps-3 text-muted-foreground">{card.context}</blockquote>}
        <Translation text={card.translation} />
        {card.kind === 'choice' ? (
          <ReviewChoice options={card.options as string[]} picked={picked} result={result} onPick={pick} onNext={next} />
        ) : (
          <ReviewOpen shown={shown} onShow={show} onKnew={knew} />
        )}
        {error && <div className={ERROR}>{error}</div>}
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
    <div className="flex flex-col gap-6">
      <section className={PANEL}>
        <div className={LABEL}>{t('review.due')}</div>
        {byTopic.length === 0 && <div className="text-muted-foreground">{t('review.nothingDueNow')}</div>}
        {byTopic.map(([topic, count]) => (
          <div key={topic} className="flex justify-between gap-4 border-b pb-2 text-sm">
            <span>{topic}</span>
            <strong className="tabular-nums">{count}</strong>
          </div>
        ))}
        {due.length > 0 && (
          <a className={buttonVariants({ variant: 'outline' })} href="#/review">
            {t('review.start')}
          </a>
        )}
        <a href="#/errors">{t('review.errorNotebook')}</a>
      </section>

      {calibration && calibration.n > 0 && (
        <section className={PANEL}>
          <div className={LABEL}>{t('review.calibration')}</div>
          <div className="flex gap-6">
            {calibration.buckets
              .filter((b) => b.n > 0)
              .map((b) => (
                <div key={b.label} className="flex flex-col items-center gap-0.5">
                  <div className="flex h-[110px] items-end gap-1">
                    <span className="inline-block min-h-0.5 w-[22px] bg-warm" style={{ height: `${b.stated! * 100}%` }} title={t('review.said', { percent: percent(b.stated!) })} />
                    <span className="inline-block min-h-0.5 w-[22px] bg-primary" style={{ height: `${b.actual! * 100}%` }} title={t('review.wasRight', { percent: percent(b.actual!) })} />
                  </div>
                  <span className={SMALL} dir="ltr">
                    {b.label}
                  </span>
                  <span className={SMALL}>{t('review.ofN', { percent: percent(b.actual!), n: b.n })}</span>
                </div>
              ))}
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <span>
              <i className="me-2 inline-block size-3 bg-warm align-[-1px]" /> {t('review.howSure')}
            </span>
            <span>
              <i className="me-2 inline-block size-3 bg-primary align-[-1px]" /> {t('review.howOften')}
            </span>
          </div>
          <div className={SMALL}>{t('review.brier', { brier: number(calibration.brier!, 2), n: calibration.n })}</div>
        </section>
      )}
    </div>
  )
}
