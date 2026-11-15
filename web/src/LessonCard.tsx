import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import Markdown, { AnswerText, InlineMarkdown } from './Md'
import { api, failure, transcribe } from './api'
import { lookup, percent } from './i18n'
import { QuizCard } from './Quiz'
import type { Given } from './offline'
import type { QuizData } from './Quiz'
import { ReadingCard, VocabCheckCard } from './Language'
import { PodcastCard } from './Podcast'
import { challengeLabel, pendingPhotos } from './course'
import { PlacementAreas } from './Areas'
import { FileEditor } from './FileEditor'
import { PhotoTray } from './Handwork'
import { Comparison, Helper, HintList, Ladder } from './Ladder'
import type { Area, Block, ChallengeData, ExerciseData, ExerciseFile, Lesson, QuestionData, SpeakingData } from './course'
import { FigureCard } from './Figure'
import { WidgetCard } from './Widget'
import { NetworkCard } from './Network'
import { PlotCard } from './PlotCard'
import { usePlayer } from './player'
import { splitBy } from './text'
import { Mic } from './Mic'

function QuestionCard(props: { block: Block; disabled: boolean; onAnswer: (answer: string, nonGoals?: string[]) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const { options, answer, multiple, non_goals } = props.block.data as QuestionData
  const goals = non_goals !== undefined
  const { picked, ruled, toggle } = usePicks(Boolean(multiple), goals)

  if (answer !== null) return <AnsweredQuestion block={props.block} />

  const given = [...picked, text.trim()].filter(Boolean).join('; ')

  function submit(e: FormEvent) {
    e.preventDefault()
    if (given || ruled.length) props.onAnswer(given, goals ? ruled : undefined)
  }

  return (
    <section id={`block-${props.block.id}`} className="block question">
      <h2 dir="auto"><InlineMarkdown>{props.block.markdown}</InlineMarkdown></h2>
      {multiple && <div className="small">{t(goals ? 'question.goals' : 'question.several')}</div>}
      <form className="stack" onSubmit={submit}>
        <div className="options">
          {options.map((o) => (
            <OptionButton key={o} option={o} state={picked.includes(o) ? 'on' : ruled.includes(o) ? 'ruled' : 'off'} disabled={props.disabled} onToggle={() => toggle(o)} />
          ))}
        </div>
        <label htmlFor={`own-${props.block.id}`}>{t('question.own')}</label>
        <div className="row">
          <input
            id={`own-${props.block.id}`}
            className="field" dir="auto"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn primary" disabled={props.disabled || !(given || ruled.length)}>
            {submitLabel(t, picked.length, ruled.length, Boolean(multiple) && !text.trim())}
          </button>
        </div>
      </form>
    </section>
  )
}

function usePicks(multiple: boolean, goals: boolean) {
  const [picked, setPicked] = useState<string[]>([])
  const [ruled, setRuled] = useState<string[]>([])

  // on a goal card a tap picks an option, a second marks it not wanted, a third clears it
  function toggle(o: string) {
    if (!multiple) setPicked(picked.includes(o) ? [] : [o])
    else if (picked.includes(o)) {
      setPicked((all) => all.filter((x) => x !== o))
      if (goals) setRuled((all) => [...all, o])
    } else if (ruled.includes(o)) setRuled((all) => all.filter((x) => x !== o))
    else setPicked((all) => [...all, o])
  }

  return { picked, ruled, toggle }
}

/** picksOnly: several options may be picked and nothing is typed. */
function submitLabel(t: TFunction, picked: number, ruled: number, picksOnly: boolean) {
  if (ruled > 0) return t('question.doneRuled', { count: picked, ruled })
  if (picksOnly && picked > 0) return t('question.done', { count: picked })
  return t('question.answer')
}

function AnsweredQuestion({ block }: { block: Block }) {
  const { t } = useTranslation()
  const { options, answer, non_goals } = block.data as QuestionData
  return (
    <section id={`block-${block.id}`} className="block answered">
      <div className="muted" dir="auto"><InlineMarkdown>{block.markdown}</InlineMarkdown></div>
      {answer && <span className="chip"><AnswerText text={answer} picked={options.includes(answer)} /></span>}
      {non_goals?.map((o) => (
        <span key={o} className="chip ruled" dir="auto"><InlineMarkdown>{t('question.notWanted', { option: o })}</InlineMarkdown></span>
      ))}
    </section>
  )
}

function OptionButton(props: { option: string; state: 'on' | 'ruled' | 'off'; disabled: boolean; onToggle: () => void }) {
  const { t } = useTranslation()
  const ruled = props.state === 'ruled'
  return (
    <button
      type="button"
      className={props.state === 'off' ? 'btn option' : `btn option ${props.state}`}
      aria-pressed={props.state === 'on' ? true : ruled ? 'mixed' : false}
      aria-label={ruled ? t('question.notWanted', { option: props.option }) : undefined}
      dir="auto"
      disabled={props.disabled}
      onClick={props.onToggle}
    >
      <InlineMarkdown>{props.option}</InlineMarkdown>
    </button>
  )
}

function ChallengeCard(props: { block: Block; disabled: boolean; speech: boolean; authored: boolean; onAct: Act; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const d = props.block.data as ChallengeData
  const open = !d.solved && d.solution === null && !props.authored
  const player = usePlayer(d.lang ?? '', props.speech)
  const spoken = Boolean(d.spoken && d.lang)

  return (
    <section id={`block-${props.block.id}`} className="block challenge">
      <div className="label">
        {challengeLabel(d, props.speech, t)}
        {d.solved && <span className="chip">{d.writing ? t('common.done') : t('common.solved')}</span>}
        {spoken && <ListenButton player={player} text={props.block.markdown} />}
      </div>
      {!spoken && <Markdown>{props.block.markdown}</Markdown>}
      <Comparison data={d} />
      <Helper data={d} />
      {player.error && <div className="error">{player.error}</div>}

      <Ladder data={d} blockId={props.block.id} onError={props.onError} />

      {open && (
        <>
          <AttemptForm block={props.block} disabled={props.disabled} speech={props.speech} onAct={props.onAct} onError={props.onError} />
          <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />
        </>
      )}
    </section>
  )
}

function ListenButton({ player, text }: { player: ReturnType<typeof usePlayer>; text: string }) {
  const { t } = useTranslation()
  return (
    <button type="button" className="btn" onClick={() => (player.current ? player.stop() : player.play([text]))}>
      {player.current ? t('common.stop') : t('common.listen')}
    </button>
  )
}

function AttemptForm(props: { block: Block; disabled: boolean; speech: boolean; onAct: Act; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const d = props.block.data as ChallengeData
  const photos = pendingPhotos(d).length
  const ready = Boolean(text.trim()) || photos > 0

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready) return
    props.onAct('attempt', { answer: text.trim() })
    setText('')
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor={`attempt-${props.block.id}`}>
        {t('common.yourAnswer')}
        {d.words && (
          <span className="muted">
            {' '}
            {t(d.structure ? 'challenge.wordRangeStructure' : 'challenge.wordRange', {
              min: d.words[0],
              max: d.words[1],
              structure: d.structure,
              n: text.trim() ? text.trim().split(/\s+/).length : 0,
            })}
          </span>
        )}
      </label>
      <textarea
        id={`attempt-${props.block.id}`}
        className="field" dir="auto"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {!d.spoken && <PhotoTray blockId={props.block.id} task={props.block.markdown} data={d} disabled={props.disabled} onError={props.onError} />}
      <div className="row">
        <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />
        {d.spoken && props.speech && (
          <Mic
            onClip={(clip) => transcribe(clip, d.lang).then((t) => setText((v) => (v ? `${v} ${t}` : t)))}
            onError={props.onError}
            disabled={props.disabled}
            limit={d.teachback ? 60 : undefined}
          />
        )}
        <button className="btn primary" disabled={props.disabled || !ready}>
          {t('challenge.submit')}
        </button>
      </div>
    </form>
  )
}

type Act = (action: string, body?: unknown) => void

const WEAK_WORD = 0.5

function SpeakingCard(props: { block: Block; disabled: boolean; speech: boolean; onAct: Act; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const d = props.block.data as SpeakingData
  const open = !d.solved && d.solution === null
  const player = usePlayer(d.lang, props.speech)
  const marks = d.marks ?? []

  async function upload(clip: Blob) {
    const form = new FormData()
    form.append('audio', clip, 'clip.webm')
    const res = await fetch(`/api/blocks/${props.block.id}/speak`, { method: 'POST', body: form })
    if (!res.ok) throw await failure(res)
  }

  return (
    <section id={`block-${props.block.id}`} className="block challenge speaking">
      <div className="label">
        {d.speaking === 'shadow' ? t('speaking.shadow') : t('speaking.read')}
        {d.solved && <span className="chip">{t('common.done')}</span>}
        <ListenButton player={player} text={props.block.markdown} />
      </div>
      {(d.speaking === 'read' || d.scores.length > 0) && (
        <p className="spoken-text" lang={d.lang} dir="auto">
          {splitBy(props.block.markdown, marks).map((piece, j) => (piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text))}
        </p>
      )}
      {player.error && <div className="error">{player.error}</div>}
      {d.scores.map((a, i) => (
        <SpokenAttempt key={i} n={i + 1} attempt={a} lang={d.lang} />
      ))}
      <HintList data={d} />
      {open && (
        <>
          <div className="row">
            <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />
            <Mic onClip={upload} onError={props.onError} label={t('speaking.record')} disabled={props.disabled} />
          </div>
          <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />
        </>
      )}
    </section>
  )
}

function SpokenAttempt({ n, attempt, lang }: { n: number; attempt: SpeakingData['scores'][number]; lang: string }) {
  const { t } = useTranslation()
  return (
    <div className="attempt">
      <span className="label">{t('speaking.attemptScore', { n, score: percent(attempt.score) })}</span>
      <span lang={lang} dir="auto">
        {attempt.words.map((w, j) => (
          <span key={j} className={w.score < WEAK_WORD ? 'word weak' : 'word'} title={percent(w.score)}>
            {w.word}{' '}
          </span>
        ))}
        {attempt.heard !== null && <span className="small"> {t('speaking.heard', { text: attempt.heard })}</span>}
      </span>
    </div>
  )
}

function HintButton(props: { data: ChallengeData; disabled: boolean; onAct: Act }) {
  const { t } = useTranslation()
  const { hints, max_hints } = props.data
  const label = hints.length ? t('challenge.nextHint') : t('challenge.hint')
  return (
    <button
      type="button"
      className="btn icon"
      disabled={props.disabled || hints.length >= max_hints}
      aria-label={label}
      title={label}
      onClick={() => props.onAct('hint')}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5M9 18h6M10 22h4" />
      </svg>
    </button>
  )
}

function LockedRow(props: { data: ChallengeData; disabled: boolean; onAct: Act }) {
  const { t } = useTranslation()
  const attemptsLeft = props.data.reveal_after - props.data.attempts.length
  return (
    <div className="locked">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="1" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
      <span className="grow">
        {attemptsLeft > 0
          ? t(props.data.writing ? 'challenge.correctionLocked' : 'challenge.solutionLocked', { count: attemptsLeft })
          : t('challenge.unlocked')}
      </span>
      <button type="button" className="link" disabled={props.disabled} onClick={() => props.onAct('give-up')}>
        {attemptsLeft > 0 ? t('challenge.giveUp') : t('challenge.showSolution')}
      </button>
    </div>
  )
}

function ExerciseCard(props: { block: Block; disabled: boolean; commands: boolean; authored: boolean; onAct: Act; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const d = props.block.data as ExerciseData
  const [answer, setAnswer] = useState('')
  const open = !d.solved && d.solution === null && !props.authored
  const blockId = props.block.id
  const { files, reads, flushes } = useExerciseFiles(blockId, open)
  const { running, error, setError, allSaved, run } = useExerciseRun(blockId, flushes)
  const kept = files.length > 0 && files.every((f) => f.kept)
  const editing = open && files.some((f) => f.editable)

  return (
    <section id={`block-${props.block.id}`} className="block challenge">
      <div className="label">
        {d.milestone ? t('challenge.milestone') : t('exercise.label')}
        {d.solved && <span className="chip">{t('common.solved')}</span>}
      </div>
      <Markdown>{props.block.markdown}</Markdown>
      <Helper data={d} />

      {files.map((f) => (
        <ExerciseFileView
          key={f.path}
          blockId={blockId}
          file={f}
          editable={open && f.editable}
          completions={d.completions ?? []}
          onSaving={() => reads.current++}
          register={(flush) => {
            flushes.current.set(f.path, flush)
            return () => flushes.current.delete(f.path)
          }}
        />
      ))}
      <div className="small">{kept ? t('exercise.cleaned') : editing ? t('exercise.editHere') : t('exercise.follows')}</div>

      {open && (
        <form onSubmit={(e) => e.preventDefault()}>
          <label htmlFor={`answer-${blockId}`}>{t('exercise.answer')}</label>
          <textarea id={`answer-${blockId}`} className="field" dir="auto" rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} />
          <PhotoTray blockId={blockId} task={props.block.markdown} data={d} disabled={props.disabled} onError={props.onError} />
        </form>
      )}

      <div className="row">
        <code className="grow">$ {d.run}</code>
        {open && <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />}
        {props.commands && !kept && (
          <button type="button" className="btn" disabled={running} onClick={run}>
            {running ? t('exercise.running') : t('exercise.run')}
          </button>
        )}
        {open && (
          <button
            type="button"
            className="btn primary"
            disabled={props.disabled}
            onClick={async () => {
              setError('')
              if (!(await allSaved())) return
              props.onAct('check', { answer: answer.trim() })
              setAnswer('')
            }}
          >
            {t('exercise.check')}
          </button>
        )}
      </div>

      {d.last_run && <RunOutput run={d.last_run} />}
      {error && <div className="error">{error}</div>}

      <Ladder data={d} blockId={blockId} onError={props.onError} />
      {open && <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />}
    </section>
  )
}

/** Running the exercise's command, once every edited file is saved. */
function useExerciseRun(blockId: number, flushes: ReturnType<typeof useExerciseFiles>['flushes']) {
  const { t } = useTranslation()
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  async function allSaved() {
    const results = await Promise.all([...flushes.current.values()].map((flush) => flush()))
    if (results.every(Boolean)) return true
    setError(t('exercise.unsaved'))
    return false
  }

  async function run() {
    setRunning(true)
    setError('')
    if (await allSaved()) await api(`/api/blocks/${blockId}/run`, {}).catch((err: Error) => setError(err.message))
    setRunning(false)
  }

  return { running, error, setError, allSaved, run }
}

/** The exercise's files, read again every 2 s while it is open; the refs let a save outrun a read in flight. */
function useExerciseFiles(blockId: number, open: boolean) {
  const [files, setFiles] = useState<ExerciseFile[]>([])
  // A read that began before a save ended may carry the old text; only the latest read counts.
  const reads = useRef(0)
  const flushes = useRef(new Map<string, () => Promise<boolean>>())

  useEffect(() => {
    const load = () => {
      const read = ++reads.current
      api<ExerciseFile[]>(`/api/blocks/${blockId}/files`).then((f) => {
        if (read === reads.current) setFiles(f)
      }, () => {})
    }
    load()
    if (!open) return
    // ponytail: polls the files every 2 s; push changes over SSE from a file watcher if this lags or costs too much
    const timer = setInterval(load, 2000)
    return () => clearInterval(timer)
  }, [blockId, open])

  return { files, reads, flushes }
}

function ExerciseFileView(props: {
  blockId: number
  file: ExerciseFile
  editable: boolean
  completions: NonNullable<ExerciseData['completions']>
  onSaving: () => void
  register: (flush: () => Promise<boolean>) => () => void
}) {
  const { t } = useTranslation()
  const f = props.file
  return (
    // closed at first: a card with several files stays short, and the run button stays in reach
    <details className="file">
      <summary className="file-head">
        <code>{f.location}</code>
        <button
          type="button"
          className="link"
          onClick={(e) => {
            e.preventDefault()
            navigator.clipboard.writeText(f.location)
          }}
        >
          {t('exercise.copyPath')}
        </button>
      </summary>
      {f.content === null ? (
        <pre>{t('exercise.missing')}</pre>
      ) : props.editable ? (
        <FileEditor blockId={props.blockId} file={f} completions={props.completions} onSaving={props.onSaving} register={props.register} />
      ) : (
        <div className="file-body">
          <Markdown>{`\`\`\`\`${f.path.split('.').pop() ?? ''}\n${f.content}\n\`\`\`\``}</Markdown>
        </div>
      )}
    </details>
  )
}

function RunOutput({ run }: { run: NonNullable<ExerciseData['last_run']> }) {
  const { t } = useTranslation()
  return (
    <div className="file">
      <div className="file-head">
        <span className="label">{run.exit_code === null ? t('exercise.outputStopped') : t('exercise.outputExit', { code: run.exit_code })}</span>
      </div>
      <pre className={run.exit_code === 0 ? '' : 'failed'}>{run.output || t('exercise.noOutput')}</pre>
    </div>
  )
}

export function PlacementResult(props: { id?: number; level: string | null; text: string | null; areas: Area[] | undefined }) {
  const { t } = useTranslation()
  return (
    <section id={props.id ? `block-${props.id}` : undefined} className="block">
      <div className="label">
        {t('block.placementResult')} <span className="chip">{props.level}</span>
      </div>
      <Markdown>{props.text ?? ''}</Markdown>
      <PlacementAreas areas={props.areas} />
    </section>
  )
}

type Features = { speech: boolean; commands: boolean; crafted: boolean; sketched: boolean }

type CardProps = {
  block: Block
  lesson: Lesson
  authored: boolean
  given: Given | undefined
  onGive: (answer: Given) => void
  features: Features
  post: (path: string, body: unknown) => void
  onError: (message: string) => void
}

const TASK_KINDS = new Set(['exercise', 'challenge', 'speaking'])
const ANSWER_KINDS = new Set(['question', 'quiz', 'reading', 'vocab', 'network'])

/** One card of a lesson, by its kind, with the calls it makes back to the server. */
export function LessonCard(props: CardProps) {
  if (TASK_KINDS.has(props.block.kind)) return <TaskCard {...props} />
  if (ANSWER_KINDS.has(props.block.kind)) return <AnswerCard {...props} />
  return <ShownCard {...props} />
}

/** The cards worked on over several tries: challenges, exercises and speaking. */
function TaskCard(props: CardProps) {
  const { block: b, lesson, authored, features } = props
  const onAct: Act = (action, body = {}) => props.post(`/api/blocks/${b.id}/${action}`, body)
  return b.kind === 'exercise' ? (
      <ExerciseCard
        key={b.id}
        block={b}
        disabled={lesson.running}
        commands={features.commands}
        authored={authored}
        onAct={onAct}
        onError={props.onError}
      />
    ) : b.kind === 'challenge' ? (
      <ChallengeCard
        key={b.id}
        block={b}
        disabled={lesson.running}
        speech={features.speech}
        authored={authored}
        onAct={onAct}
        onError={props.onError}
      />
    ) : (
      <SpeakingCard
        key={b.id}
        block={b}
        disabled={lesson.running}
        speech={features.speech}
        onAct={onAct}
        onError={props.onError}
      />
    )
}

/** The cards answered in one go: questions, quizzes, readings, the vocabulary check and network requests. */
function AnswerCard(props: CardProps) {
  const { block: b, lesson, authored, features } = props
  return b.kind === 'question' ? (
      <QuestionCard
        key={b.id}
        block={b}
        disabled={lesson.running}
        onAnswer={(answer, nonGoals) => props.post(`/api/blocks/${b.id}/answer`, { answer, non_goals: nonGoals ?? [] })}
      />
    ) : b.kind === 'quiz' ? (
      <QuizCard
        key={b.id}
        id={b.id}
        question={b.markdown}
        data={b.data as QuizData}
        disabled={lesson.running}
        authored={authored}
        offline={lesson.batch ? { given: props.given, onGive: props.onGive } : undefined}
        onUnknown={lesson.phase === 'placement' ? () => props.post(`/api/blocks/${b.id}/quiz/unknown`, {}) : undefined}
        onSelfGrade={lesson.replay ? (correct) => props.post(`/api/blocks/${b.id}/self-grade`, { correct }) : undefined}
        onSubmit={(answer, confidence) => props.post(`/api/blocks/${b.id}/quiz`, { answer, confidence })}
      />
    ) : b.kind === 'reading' ? (
      <ReadingCard
        key={b.id}
        id={b.id}
        text={b.markdown}
        data={b.data}
        speech={features.speech}
        onAdd={(word) => props.post(`/api/blocks/${b.id}/vocabulary`, { word })}
        onKnown={(word) => props.post(`/api/blocks/${b.id}/known`, { word })}
      />
    ) : b.kind === 'vocab' ? (
      <VocabCheckCard
        key={b.id}
        id={b.id}
        data={b.data}
        disabled={lesson.running}
        onSubmit={(known) => props.post(`/api/blocks/${b.id}/vocab`, { known })}
      />
    ) : (
      <NetworkCard
        key={b.id}
        id={b.id}
        reason={b.markdown}
        data={b.data}
        disabled={lesson.running}
        onDecide={(allow) => props.post(`/api/blocks/${b.id}/network`, { allow })}
      />
    )
}

/** The cards that show something: plots, widgets, figures, a placement result, a podcast, and plain text. */
function ShownCard(props: CardProps) {
  const { block: b, lesson, authored, features } = props
  return b.kind === 'plot' ? (
      <PlotCard key={b.id} id={b.id} title={b.markdown} data={b.data} />
    ) : b.kind === 'widget' ? (
      <WidgetCard key={b.id} id={b.id} title={b.markdown} data={b.data} onTry={authored ? undefined : (at) => props.post(`/api/blocks/${b.id}/widget`, { at })} />
    ) : b.kind === 'figure' ? (
      <FigureCard key={b.id} id={b.id} caption={b.markdown} data={b.data} sketched={features.sketched} disabled={lesson.running} onRestore={() => props.post(`/api/blocks/${b.id}/restore`, {})} onRedraw={features.crafted ? (notes) => props.post(`/api/blocks/${b.id}/redraw`, { notes }) : undefined} />
    ) : b.kind === 'placement' ? (
      <PlacementResult key={b.id} id={b.id} level={(b.data as { level: string }).level} text={b.markdown} areas={(b.data as { areas?: Area[] }).areas} />
    ) : b.kind === 'podcast' ? (
      <PodcastCard
        key={b.id}
        id={b.id}
        title={b.markdown}
        data={b.data}
        answered={(id) => (lesson.blocks.find((q) => q.id === id)?.data as QuizData | undefined)?.answer != null}
      />
    ) : (
      <section key={b.id} id={`block-${b.id}`} className="block">
        <div className="label">{lookup(`block.${b.kind}`, b.kind)}</div>
        <Markdown>{b.markdown}</Markdown>
      </section>
    )
}
