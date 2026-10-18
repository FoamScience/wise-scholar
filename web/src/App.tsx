import { Fragment, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api, failure } from './api'
import { useArrivals } from './arrive'
import i18n, { day, lookup, percent } from './i18n'
import Logo from './Logo'
import { QuizCard, Review, ReviewPanels } from './Quiz'
import { loadGiven, saveGiven, useOnline } from './offline'
import type { Given } from './offline'
import type { QuizData } from './Quiz'
import { LevelPanel, ReadingCard, VocabCheckCard } from './Language'
import { PodcastCard } from './Podcast'
import { ErrorsPage } from './Errors'
import { CommandsPage } from './Commands'
import { challengeLabel, lessonStream, lessonTitle, outlineOf, practiceTitle } from './course'
import { OutlineCard } from './Outline'
import { SittingPage } from './Sitting'
import { Comparison, HintList, Ladder } from './Ladder'
import type { Block, Capstone, ChallengeData, Concept, Course, CourseDetail, ExerciseData, ExerciseFile, Lesson, Message, QuestionData, Ranked, SpeakingData } from './course'
import { FigureCard } from './Figure'
import { NetworkCard } from './Network'
import { PlotCard } from './PlotCard'
import { ScopeCard, ScopeForm } from './Scope'
import { Book } from './Book'
import { Handout } from './Handout'
import { SourcesPanel, SOURCE_TYPES } from './Sources'
import type { Source } from './Sources'
import { usePlayer } from './player'
import { splitBy, textDirection } from './text'
import { FirstProfile, ProfilePage } from './Profile'
import { useProfiles } from './profiles'
import { LOCALES, browserLocale, rememberLocale } from './locale'
import type { Locale } from './locale'

type TutorEvent =
  | { type: 'turn.started'; lesson_id: number }
  | { type: 'chat.delta'; lesson_id: number; text: string }
  | { type: 'activity'; lesson_id: number; tool: string }
  | { type: 'block.added' | 'block.updated'; lesson_id: number; block: Block }
  | { type: 'block.removed'; lesson_id: number; id: number }
  | { type: 'lesson.ordered'; lesson_id: number; blocks: Block[] }
  | { type: 'plan.ranked'; ranking: Ranked[]; mechanism: string }
  | { type: 'plan.chosen'; mechanism: string }
  | { type: 'course.pace'; pace: 'momentum' | 'speed' }
  | { type: 'placement.set'; level: string; placement: string }
  | { type: 'map.set'; concepts: Concept[]; capstones?: Capstone[] }
  | { type: 'capstone.set'; capstone: Capstone }
  | { type: 'source.updated'; source: Source }
  | { type: 'source.removed'; id: number }
  | { type: 'lesson.created'; lesson: Lesson }
  | { type: 'turn.done'; lesson_id: number; ok: boolean; error: string | null; message: Message | null }

const LESSON_AREA_TOOLS = [
  'add_block',
  'ask',
  'ask_network',
  'rank_mechanisms',
  'pose_challenge',
  'pose_comparison',
  'pose_exercise',
  'pose_quiz',
  'pose_sort',
  'add_reading',
  'add_figure',
  'add_crafted_figure',
  'add_diagram',
  'add_animation',
  'add_plot',
  'pose_writing',
  'pose_vocab_check',
  'pose_speaking',
  'pose_teachback',
  'make_podcast',
]

function useHash(): string {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const onChange = () => setHash(location.hash)
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

type TodayPlan = {
  due: number
  warmup: number
  review_minutes: number
  units: { course_id: number; topic: string; concept_id: number | null; title: string; started?: boolean }[]
  cast: { id: number; lesson_id: number; title: string; course_id: number } | null
  errors: number
  extras: { course_id: number; topic: string; kind: 'episode' | 'writing' }[]
}

function unitTitle(u: TodayPlan['units'][number], t: TFunction): string {
  if (u.concept_id !== null) return u.title
  return u.started ? t('today.finishInterview') : t('scope.start')
}

function unitHash(u: TodayPlan['units'][number]): string {
  return u.concept_id === null ? `#/course/${u.course_id}` : `#/course/${u.course_id}?concept=${u.concept_id}`
}

/** The sitting as one plan: reviews first, then the next unit. Start walks through both. */
function Today({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState<TodayPlan | null>(null)
  useEffect(() => {
    api<TodayPlan>(`/api/today?profile=${profile}`).then(setPlan, () => {})
  }, [profile])
  if (!plan || (plan.due === 0 && plan.units.length === 0)) return null
  const unit = plan.units[0]
  // a review with somewhere to go next is the sitting's warm-up, capped; the review page holds the rest
  const start = plan.warmup > 0 ? `#/review?then=${encodeURIComponent(unit ? unitHash(unit) : '#/')}` : unit ? unitHash(unit) : '#/review'
  return (
    <section className="block today">
      <div className="label">{t('today.heading')}</div>
      <ol className="plan-steps">
        {plan.due > 0 && (
          <li>
            {t('today.reviews', { count: plan.warmup })} <span className="muted">{t('today.reviewMinutes', { minutes: Math.max(1, plan.review_minutes) })}</span>
          </li>
        )}
        {unit && (
          <li>
            {t('today.unit', { topic: unit.topic, title: unitTitle(unit, t) })} <span className="muted">{t('today.restOfSitting')}</span>
          </li>
        )}
        {plan.units.slice(1, 4).map((u) => (
          <li key={u.course_id} className="muted">
            {t('today.later', { topic: u.topic, title: unitTitle(u, t) })}
          </li>
        ))}
        {plan.cast && (
          <li className="muted">
            {t('today.castReady')} <a href={`#/course/${plan.cast.course_id}`}>{plan.cast.title}</a>
          </li>
        )}
        {plan.extras.map((x) => (
          <li key={`${x.course_id}-${x.kind}`} className="muted">
            <a href={`#/course/${x.course_id}?start=${x.kind}`}>
              {x.kind === 'episode' ? t('today.nextEpisode', { topic: x.topic }) : t('today.writingSession', { topic: x.topic })}
            </a>{' '}
            {t('today.strandBehind')}
          </li>
        ))}
        {plan.errors > 0 && (
          <li className="muted">
            <a href="#/errors">{t('today.errors', { count: plan.errors })}</a>
          </li>
        )}
      </ol>
      <div className="row">
        <a className="btn primary as-link" href={start}>
          {t('common.start')}
        </a>
      </div>
    </section>
  )
}

function Home({ profile, teacher }: { profile: number; teacher: boolean }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState<Course[]>([])
  const [topic, setTopic] = useState('')
  const [materials, setMaterials] = useState<File[]>([])
  const [url, setUrl] = useState('')
  const [starting, setStarting] = useState('')
  const picker = useRef<HTMLInputElement | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Course[]>(`/api/courses?profile=${profile}`).then(setCourses, (e) => setError(e.message))
  }, [profile])

  async function start(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const course = await api<Course>('/api/courses', { topic, profile_id: profile })
      // Materials go in before the interview, so its first turn already knows them.
      for (const file of materials) {
        setStarting(t('home.adding', { name: file.name }))
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(`/api/courses/${course.id}/sources`, { method: 'POST', body: form })
        if (!res.ok) throw await failure(res)
      }
      if (url.trim()) {
        setStarting(t('home.adding', { name: url.trim() }))
        await api(`/api/courses/${course.id}/sources/url`, { url: url.trim() })
      }
      location.hash = `#/course/${course.id}`
    } catch (err) {
      setError((err as Error).message)
      // The course may exist by now: show it in the list rather than inviting a second Start.
      api<Course[]>(`/api/courses?profile=${profile}`).then(setCourses, () => {})
      setTopic('')
      setMaterials([])
      setUrl('')
    } finally {
      setStarting('')
    }
  }

  function archive(course: Course, archived: boolean) {
    api(`/api/courses/${course.id}/archive`, { archived }).then(
      () => setCourses((all) => all.map((c) => (c.id === course.id ? { ...c, archived: Number(archived) } : c))),
      (err: Error) => setError(err.message),
    )
  }

  function remove(course: Course) {
    api(`/api/courses/${course.id}/delete`, {}).then(
      () => setCourses((all) => all.filter((c) => c.id !== course.id)),
      (err: Error) => setError(err.message),
    )
  }

  function duplicate(course: Course) {
    api<Course>(`/api/courses/${course.id}/duplicate`, {}).then(
      (copy) => setCourses((all) => [copy, ...all]),
      (err: Error) => setError(err.message),
    )
  }

  const active = courses.filter((c) => !c.archived)
  const archived = courses.filter((c) => c.archived)

  return (
    <main className="home">
      <form className="topic-form" onSubmit={start}>
        <label htmlFor="topic">{t('home.topicLabel')}</label>
        <div className="row">
          <input
            id="topic"
            className="field" dir="auto"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={t('home.topicPlaceholder')}
          />
          <button className="btn primary" disabled={!topic.trim() || starting !== ''}>
            {starting ? t('home.starting') : t('common.start')}
          </button>
        </div>
        <div className="muted">{t('home.topicHelp')}</div>
        <details className="block materials">
          <summary className="label">{t('home.materials')}</summary>
          <div className="stack">
            <div className="muted">{t('home.materialsHelp')}</div>
            <div className="row">
              <button type="button" className="btn" onClick={() => picker.current?.click()}>
                {t('sources.add')}
              </button>
              <span className="small grow">{materials.map((f) => f.name).join(' · ')}</span>
            </div>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              accept={SOURCE_TYPES}
              onChange={(e) => setMaterials(Array.from(e.target.files ?? []))}
            />
            <input
              className="field"
              type="text"
              inputMode="url"
              dir="ltr"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('home.urlPlaceholder')}
            />
            {starting && <div className="small">{starting}</div>}
          </div>
        </details>
      </form>
      {error && <div className="error">{error}</div>}
      {!teacher && <Today profile={profile} />}
      {!teacher && <ReviewPanels profile={profile} />}
      {active.length > 0 && (
        <section>
          <div className="label gap-below">{t('home.courses')}</div>
          <div className="courses">
            {active.map((c) => (
              <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} />
            ))}
          </div>
        </section>
      )}
      {archived.length > 0 && (
        <details className="archived">
          <summary className="label">{t('home.archived', { n: archived.length })}</summary>
          <div className="courses">
            {archived.map((c) => (
              <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} />
            ))}
          </div>
        </details>
      )}
    </main>
  )
}

function CourseCard(props: {
  course: Course
  onArchive: (course: Course, archived: boolean) => void
  onDelete: (course: Course) => void
  onDuplicate: (course: Course) => void
}) {
  const { course } = props
  const { t } = useTranslation()
  const [confirming, setConfirming] = useState(false)
  const menu = useRef<HTMLDetailsElement>(null)

  function close() {
    setConfirming(false)
    if (menu.current) menu.current.open = false
  }

  return (
    <div className="course-card">
      <a href={`#/course/${course.id}`}>
        <strong dir="auto">
          {course.topic}
          {course.mode === 'teacher' && <span className="chip">{t('home.prepared')}</span>}
        </strong>
        <span className="muted">{course.mechanism ? lookup(`playbooks.${course.mechanism}.title`, course.mechanism) : t('home.interviewOpen')}</span>
      </a>
      <details ref={menu} className="menu" name="course-menu" onToggle={() => setConfirming(false)}>
        <summary aria-label={t('home.options', { topic: course.topic })}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="12" cy="5" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="12" cy="19" r="2" />
          </svg>
        </summary>
        <div className="menu-panel">
          {confirming ? (
            <>
              <div>{t('home.deleteConfirm', { topic: course.topic })}</div>
              <button type="button" className="btn danger" onClick={() => props.onDelete(course)}>
                {t('home.deleteCourse')}
              </button>
              <button type="button" className="btn" onClick={close}>
                {t('common.cancel')}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  close()
                  props.onArchive(course, !course.archived)
                }}
              >
                {course.archived ? t('home.unarchive') : t('home.archive')}
              </button>
              {course.mode === 'teacher' && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    close()
                    props.onDuplicate(course)
                  }}
                >
                  {t('home.duplicate')}
                </button>
              )}
              <button type="button" className="btn" onClick={() => setConfirming(true)}>
                {t('home.delete')}
              </button>
            </>
          )}
        </div>
      </details>
    </div>
  )
}

function Skeleton() {
  const { t } = useTranslation()
  return (
    <section className="block skeleton" role="status" aria-label={t('block.tutorWorking')}>
      <span style={{ width: '22%' }} />
      <span style={{ width: '92%' }} />
      <span style={{ width: '78%' }} />
      <span style={{ width: '54%' }} />
    </section>
  )
}

function QuestionCard(props: { block: Block; disabled: boolean; onAnswer: (answer: string) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const { options, answer, multiple } = props.block.data as QuestionData

  if (answer !== null)
    return (
      <section id={`block-${props.block.id}`} className="block answered">
        <div className="muted" dir="auto">{props.block.markdown}</div>
        <span className="chip" dir="auto">{answer}</span>
      </section>
    )

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) props.onAnswer(text.trim())
  }

  return (
    <section id={`block-${props.block.id}`} className="block question">
      <h2 dir="auto">{props.block.markdown}</h2>
      {multiple && <div className="small">{t('question.several')}</div>}
      <div className="options">
        {options.map((o) =>
          multiple ? (
            <button
              key={o}
              type="button"
              className={picked.includes(o) ? 'btn option on' : 'btn option'}
              aria-pressed={picked.includes(o)}
              dir="auto"
              disabled={props.disabled}
              onClick={() => setPicked((all) => (all.includes(o) ? all.filter((x) => x !== o) : [...all, o]))}
            >
              {o}
            </button>
          ) : (
            <button key={o} className="btn option" dir="auto" disabled={props.disabled} onClick={() => props.onAnswer(o)}>
              {o}
            </button>
          ),
        )}
        {multiple && (
          <button type="button" className="btn primary" disabled={props.disabled || picked.length === 0} onClick={() => props.onAnswer(picked.join('; '))}>
            {t('question.done', { count: picked.length })}
          </button>
        )}
      </div>
      <form onSubmit={submit}>
        <label htmlFor={`own-${props.block.id}`}>{t('question.own')}</label>
        <div className="row">
          <input
            id={`own-${props.block.id}`}
            className="field" dir="auto"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn primary" disabled={props.disabled || !text.trim()}>
            {t('question.answer')}
          </button>
        </div>
      </form>
    </section>
  )
}

function ChallengeCard(props: { block: Block; disabled: boolean; speech: boolean; authored: boolean; onAct: Act; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const d = props.block.data as ChallengeData
  const open = !d.solved && d.solution === null && !props.authored
  const player = usePlayer(d.lang ?? '', props.speech)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    props.onAct('attempt', { answer: text.trim() })
    setText('')
  }

  return (
    <section id={`block-${props.block.id}`} className="block challenge">
      <div className="label">
        {challengeLabel(d, props.speech, t)}
        {d.solved && <span className="chip">{d.writing ? t('common.done') : t('common.solved')}</span>}
        {d.spoken && d.lang && (
          <button type="button" className="btn" onClick={() => (player.current ? player.stop() : player.play([props.block.markdown]))}>
            {player.current ? t('common.stop') : t('common.listen')}
          </button>
        )}
      </div>
      {!(d.spoken && d.lang) && <Markdown>{props.block.markdown}</Markdown>}
      <Comparison data={d} />
      {player.error && <div className="error">{player.error}</div>}

      <Ladder data={d} />

      {open && (
        <>
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
              <button className="btn primary" disabled={props.disabled || !text.trim()}>
                {t('challenge.submit')}
              </button>
            </div>
          </form>
          <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />
        </>
      )}
    </section>
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
        <button type="button" className="btn" onClick={() => (player.current ? player.stop() : player.play([props.block.markdown]))}>
          {player.current ? t('common.stop') : t('common.listen')}
        </button>
      </div>
      {(d.speaking === 'read' || d.scores.length > 0) && (
        <p className="spoken-text" lang={d.lang} dir="auto">
          {splitBy(props.block.markdown, marks).map((piece, j) => (piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text))}
        </p>
      )}
      {player.error && <div className="error">{player.error}</div>}
      {d.scores.map((a, i) => (
        <div key={i} className="attempt">
          <span className="label">{t('speaking.attemptScore', { n: i + 1, score: percent(a.score) })}</span>
          <span lang={d.lang} dir="auto">
            {a.words.map((w, j) => (
              <span key={j} className={w.score < WEAK_WORD ? 'word weak' : 'word'} title={percent(w.score)}>
                {w.word}{' '}
              </span>
            ))}
            {a.heard !== null && <span className="small"> {t('speaking.heard', { text: a.heard })}</span>}
          </span>
        </div>
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

function HintButton(props: { data: ChallengeData; disabled: boolean; onAct: Act }) {
  const { t } = useTranslation()
  const { hints, max_hints } = props.data
  return (
    <button
      type="button"
      className="btn"
      disabled={props.disabled || hints.length >= max_hints}
      onClick={() => props.onAct('hint')}
    >
      {hints.length ? t('challenge.nextHint') : t('challenge.hint')}
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

function ExerciseCard(props: { block: Block; disabled: boolean; commands: boolean; authored: boolean; onAct: Act }) {
  const { t } = useTranslation()
  const d = props.block.data as ExerciseData
  const [files, setFiles] = useState<ExerciseFile[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const open = !d.solved && d.solution === null && !props.authored
  const blockId = props.block.id
  const kept = files.length > 0 && files.every((f) => f.kept)

  useEffect(() => {
    const load = () => api<ExerciseFile[]>(`/api/blocks/${blockId}/files`).then(setFiles, () => {})
    load()
    if (!open) return
    // ponytail: polls the files every 2 s; push changes over SSE from a file watcher if this lags or costs too much
    const timer = setInterval(load, 2000)
    return () => clearInterval(timer)
  }, [blockId, open])

  function run() {
    setRunning(true)
    setError('')
    api(`/api/blocks/${blockId}/run`, {})
      .catch((err: Error) => setError(err.message))
      .finally(() => setRunning(false))
  }

  return (
    <section id={`block-${props.block.id}`} className="block challenge">
      <div className="label">
        {d.milestone ? t('challenge.milestone') : t('exercise.label')}
        {d.solved && <span className="chip">{t('common.solved')}</span>}
      </div>
      <Markdown>{props.block.markdown}</Markdown>

      {files.map((f) => (
        <div key={f.path} className="file">
          <div className="file-head">
            <code>{f.location}</code>
            <button type="button" className="link" onClick={() => navigator.clipboard.writeText(f.location)}>
              {t('exercise.copyPath')}
            </button>
          </div>
          {f.content === null ? (
            <pre>{t('exercise.missing')}</pre>
          ) : (
            <div className="file-body">
              <Markdown>{`\`\`\`\`${f.path.split('.').pop() ?? ''}\n${f.content}\n\`\`\`\``}</Markdown>
            </div>
          )}
        </div>
      ))}
      <div className="small">{kept ? t('exercise.cleaned') : t('exercise.follows')}</div>

      <div className="row">
        <code className="grow">$ {d.run}</code>
        {open && <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />}
        {props.commands && !kept && (
          <button type="button" className="btn" disabled={running} onClick={run}>
            {running ? t('exercise.running') : t('exercise.run')}
          </button>
        )}
        {open && (
          <button type="button" className="btn primary" disabled={props.disabled} onClick={() => props.onAct('check')}>
            {t('exercise.check')}
          </button>
        )}
      </div>

      {d.last_run && (
        <div className="file">
          <div className="file-head">
            <span className="label">
              {d.last_run.exit_code === null ? t('exercise.outputStopped') : t('exercise.outputExit', { code: d.last_run.exit_code })}
            </span>
          </div>
          <pre className={d.last_run.exit_code === 0 ? '' : 'failed'}>{d.last_run.output || t('exercise.noOutput')}</pre>
        </div>
      )}
      {error && <div className="error">{error}</div>}

      <Ladder data={d} />
      {open && <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />}
    </section>
  )
}

/** A tutor or learner message, inline in the lesson between the cards. */
function Remark({ message }: { message: Message }) {
  if (message.role === 'learner')
    return (
      <div className="remark learner" dir={textDirection(message.text)}>
        {message.text}
      </div>
    )
  return (
    <div className="remark">
      <Markdown>{message.text}</Markdown>
    </div>
  )
}

function squares(concept: Concept): number {
  return Math.round((concept.mastery ?? 0) * 3)
}

type Draft = { markdown: string; solution: string; hints: string; run: string; options: string; answer_key: string; explanation: string }

function draftOf(block: Block): Draft {
  const d = (block.data ?? {}) as Partial<ChallengeData & ExerciseData & QuizData>
  return {
    markdown: block.markdown,
    solution: d.solution ?? '',
    hints: (d.hints ?? []).join('\n'),
    run: d.run ?? '',
    options: d.kind === 'choice' ? (d.options as string[]).join('\n') : '',
    answer_key: d.answer_key ?? '',
    explanation: d.explanation ?? '',
  }
}

/** A teacher's hand on a card of a prepared course: edit its text and answers, move it, remove it. */
function EditBar(props: { block: Block; first: boolean; last: boolean; disabled: boolean; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const { block } = props
  const [draft, setDraft] = useState<Draft | null>(null)
  const [confirming, setConfirming] = useState(false)
  const kind = block.kind
  const task = kind === 'challenge' || kind === 'exercise' || kind === 'speaking'
  const quiz = kind === 'quiz'

  function act(path: string, body: unknown = {}) {
    return api(`/api/blocks/${block.id}/${path}`, body).catch((err: Error) => props.onError(err.message))
  }

  function save() {
    if (!draft) return
    const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)
    const body: Record<string, unknown> = { markdown: draft.markdown }
    if (task) Object.assign(body, { solution: draft.solution, hints: lines(draft.hints), run: draft.run })
    if (quiz) Object.assign(body, { options: lines(draft.options), answer_key: draft.answer_key, explanation: draft.explanation })
    act('edit', body).then(() => setDraft(null))
  }

  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setDraft((d) => d && { ...d, [key]: e.target.value })

  if (draft) {
    return (
      <form
        className="edit-form"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <label className="small">{t('edit.text')}</label>
        <textarea className="field" dir="auto" rows={4} value={draft.markdown} onChange={set('markdown')} />
        {task && (
          <>
            <label className="small">{t('edit.hints')}</label>
            <textarea className="field" dir="auto" rows={3} value={draft.hints} onChange={set('hints')} />
            <label className="small">{t('edit.solution')}</label>
            <textarea className="field" dir="auto" rows={4} value={draft.solution} onChange={set('solution')} />
            {kind === 'exercise' && (
              <>
                <label className="small">{t('edit.run')}</label>
                <input className="field" dir="ltr" value={draft.run} onChange={set('run')} />
              </>
            )}
          </>
        )}
        {quiz && (
          <>
            {draft.options !== '' || (block.data as QuizData).kind === 'choice' ? (
              <>
                <label className="small">{t('edit.options')}</label>
                <textarea className="field" dir="auto" rows={4} value={draft.options} onChange={set('options')} />
              </>
            ) : null}
            <label className="small">{t('edit.key')}</label>
            <input className="field" dir="auto" value={draft.answer_key} onChange={set('answer_key')} />
            <label className="small">{t('edit.explanation')}</label>
            <textarea className="field" dir="auto" rows={3} value={draft.explanation} onChange={set('explanation')} />
          </>
        )}
        <div className="row">
          <button className="btn primary" disabled={!draft.markdown.trim()}>
            {t('edit.save')}
          </button>
          <button type="button" className="btn" onClick={() => setDraft(null)}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="edit-bar row">
      <button type="button" className="link" disabled={props.disabled} onClick={() => setDraft(draftOf(block))}>
        {t('edit.edit')}
      </button>
      <button type="button" className="link" disabled={props.disabled || props.first} onClick={() => act('move', { direction: 'up' })}>
        {t('edit.up')}
      </button>
      <button type="button" className="link" disabled={props.disabled || props.last} onClick={() => act('move', { direction: 'down' })}>
        {t('edit.down')}
      </button>
      {confirming ? (
        <>
          <button type="button" className="btn danger" disabled={props.disabled} onClick={() => act('remove')}>
            {t('edit.removeConfirm')}
          </button>
          <button type="button" className="link" onClick={() => setConfirming(false)}>
            {t('common.cancel')}
          </button>
        </>
      ) : (
        <button type="button" className="link" disabled={props.disabled} onClick={() => setConfirming(true)}>
          {t('edit.remove')}
        </button>
      )}
    </div>
  )
}

/** A unit is done once its lesson is finished, or placed out with no lesson begun. */
function unitDone(concept: Concept, lesson: Lesson | undefined): boolean {
  return lesson ? lesson.blocks.some((b) => b.kind === 'done') : Boolean(concept.known)
}

function conceptStats(concept: Concept, lesson: Lesson | undefined, t: TFunction, prepared = false): string {
  if (prepared) return !lesson ? t('map.notPlanned') : lesson.blocks.some((b) => b.kind === 'done') ? t('map.planned') : t('map.drafting')
  const due = concept.due ? t('map.reviewDue', { count: concept.due }) : ''
  if (!lesson) return [concept.known ? t('map.placedOut') : t('map.notStarted'), due].filter(Boolean).join(' · ')
  if (concept.kind === 'practice') return lesson.blocks.some((b) => b.kind === 'done') ? t('common.done') : t('map.started')
  const outline = outlineOf(lesson)
  const where = unitDone(concept, lesson)
    ? t('common.done')
    : outline && outline.at < outline.steps.length
      ? t('outline.step', { n: outline.at + 1, total: outline.steps.length })
      : ''
  const cs = lesson.blocks
    .filter((b) => b.kind === 'challenge' || b.kind === 'exercise' || b.kind === 'speaking')
    .map((b) => b.data as ChallengeData)
  if (cs.length === 0) return [where || t('map.started'), due].filter(Boolean).join(' · ')
  const hints = cs.reduce((n, c) => n + c.hints.length, 0)
  const gaveUp = cs.filter((c) => c.gave_up).length
  return [
    where,
    t('map.solved', { solved: cs.filter((c) => c.solved).length, total: cs.length }),
    hints > 0 && t('map.hints', { count: hints }),
    gaveUp > 0 && t('map.gaveUp', { n: gaveUp }),
    due,
  ]
    .filter(Boolean)
    .join(' · ')
}

function Plan(props: {
  ranking: Ranked[]
  mechanism: string | null
  accepted: boolean
  disabled: boolean
  onChoose: (mechanism: string) => void
  onAccept: () => void
  onPlacement: () => void
  prepared: boolean
}) {
  const { t } = useTranslation()
  return (
    <section className="plan">
      <div className="label">{t('plan.heading')}</div>
      {props.ranking.map((r, i) => (
        <label key={r.mechanism} className={r.mechanism === props.mechanism ? 'plan-card chosen' : 'plan-card'}>
          <input
            type="radio"
            name="mechanism"
            checked={r.mechanism === props.mechanism}
            disabled={props.accepted}
            onChange={() => props.onChoose(r.mechanism)}
          />
          <span>
            <strong>
              {i + 1} · {lookup(`playbooks.${r.mechanism}.title`, r.title)}
            </strong>
            <span dir="auto">{r.rationale}</span>
            <span className="muted">{lookup(`playbooks.${r.mechanism}.summary`, r.summary)}</span>
            <span className="evidence">
              {t('plan.evidence')}{' '}
              {r.evidence.map((e, n) => (
                <span key={e.url}>
                  {n > 0 && '; '}
                  <a href={e.url} target="_blank" rel="noreferrer" title={e.finding}>
                    {e.source}
                  </a>
                </span>
              ))}
            </span>
          </span>
        </label>
      ))}
      <div className="muted">{t('plan.always')}</div>
      {!props.accepted && (
        <div className="block next-step">
          <div className="label">{props.prepared ? t('plan.nextPrepared') : t('plan.next')}</div>
          <div>{props.prepared ? t('plan.preparedInfo') : t('plan.placementInfo')}</div>
          <div className="row">
            {!props.prepared && (
              <button className="btn primary" disabled={props.disabled} onClick={props.onPlacement}>
                {t('plan.startPlacement')}
              </button>
            )}
            <button className={props.prepared ? 'btn primary' : 'btn'} disabled={props.disabled} onClick={props.onAccept}>
              {props.prepared ? t('plan.accept') : t('plan.skip')}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function Workspace({ courseId, speech, commands, crafted, sketched, concept, start }: { courseId: number; speech: boolean; commands: boolean; crafted: boolean; sketched: boolean; concept: number | null; start: 'episode' | 'writing' | null }) {
  const { t } = useTranslation()
  const [course, setCourse] = useState<CourseDetail | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [lessonId, setLessonId] = useState<number | null>(null)
  const [streaming, setStreaming] = useState('')
  const [activity, setActivity] = useState('')
  const [writing, setWriting] = useState(false)
  const [draft, setDraft] = useState('')
  const [changing, setChanging] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const online = useOnline()
  // which column a phone shows; wider screens show all three
  const [pane, setPane] = useState<'map' | 'lesson'>('lesson')
  // the chat drawer; unset, it follows the lesson: open in the interview, which is a conversation
  const [asking, setAsking] = useState<boolean | null>(null)
  const [kept, setKept] = useState<{ lesson: number | null; answers: Record<number, Given> }>({ lesson: null, answers: {} })
  const lessonBottom = useRef<HTMLDivElement>(null)
  const sideMenu = useRef<HTMLDetailsElement>(null)
  const lessonBox = useRef<HTMLElement>(null)

  const lesson = course?.lessons.find((l) => l.id === lessonId) ?? null
  useArrivals(lessonBox, lesson?.id)

  const given = kept.lesson === lessonId ? kept.answers : lessonId ? loadGiven(lessonId) : {}

  function keep(id: number, answers: Record<number, Given>) {
    setKept({ lesson: id, answers })
    saveGiven(id, answers)
  }

  function give(blockId: number, answer: Given) {
    keep(lessonId!, { ...given, [blockId]: answer })
  }

  function prepareOffline() {
    const id = lessonId!
    api(`/api/lessons/${id}/prepare`, {}).then(() => patchLesson(id, (l) => ({ ...l, batch: 1 })), (err: Error) => setError(err.message))
  }

  function sendBatch(blocks: Block[]) {
    const id = lessonId!
    const answers = blocks.filter((b) => given[b.id]).map((b) => ({ block_id: b.id, ...given[b.id] }))
    setSending(true)
    api(`/api/lessons/${id}/batch`, { answers })
      .then(
        () => {
          patchLesson(id, (l) => ({ ...l, batch: 0 }))
          keep(id, {})
        },
        (err: Error) => setError(err.message),
      )
      .finally(() => setSending(false))
  }

  function showLesson(id: number) {
    setLessonId(id)
    setPane('lesson')
    setAsking(null)
  }

  function closeChat() {
    setAsking(false)
    // the drawer hides with the focus in it: hand it back to the button that opens it
    requestAnimationFrame(() => document.getElementById('ask')?.focus())
  }

  function patchLesson(id: number, patch: (l: Lesson) => Lesson) {
    setCourse((c) => c && { ...c, lessons: c.lessons.map((l) => (l.id === id ? patch(l) : l)) })
  }

  function addLesson(lesson: Lesson) {
    setCourse((c) => c && (c.lessons.some((l) => l.id === lesson.id) ? c : { ...c, lessons: [...c.lessons, lesson] }))
  }

  function openConcept(concept: Concept) {
    const existing = course?.lessons.find((l) => l.concept_id === concept.id)
    if (existing) return showLesson(existing.id)
    api<Lesson>(`/api/concepts/${concept.id}/lesson`, {}).then(
      (created) => {
        addLesson(created)
        showLesson(created.id)
      },
      (err: Error) => setError(err.message),
    )
  }

  useEffect(() => {
    const refreshTotals = () =>
      api<CourseDetail>(`/api/courses/${courseId}`).then(
        ({ concepts, strands, vocabulary }) => setCourse((c) => c && { ...c, concepts, strands, vocabulary }),
        () => {},
      )
    const source = new EventSource(`/api/courses/${courseId}/events`)
    source.onmessage = (raw) => {
      const ev: TutorEvent = JSON.parse(raw.data)
      if (ev.type === 'turn.started') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, running: true }))
        setActivity('thinking')
        setError('')
      } else if (ev.type === 'chat.delta') {
        setActivity('')
        setStreaming((s) => s + ev.text)
      } else if (ev.type === 'activity') {
        setActivity(ev.tool)
        setWriting(LESSON_AREA_TOOLS.includes(ev.tool))
      } else if (ev.type === 'block.added') {
        setWriting(false)
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: [...l.blocks, ev.block] }))
        refreshTotals()
      } else if (ev.type === 'block.updated') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: l.blocks.map((b) => (b.id === ev.block.id ? ev.block : b)) }))
        refreshTotals()
      } else if (ev.type === 'block.removed') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: l.blocks.filter((b) => b.id !== ev.id) }))
      } else if (ev.type === 'lesson.ordered') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: ev.blocks }))
      } else if (ev.type === 'plan.ranked') {
        setWriting(false)
        setCourse((c) => c && { ...c, ranking: ev.ranking, mechanism: ev.mechanism })
      } else if (ev.type === 'plan.chosen') {
        setCourse((c) => c && { ...c, mechanism: ev.mechanism })
      } else if (ev.type === 'course.pace') {
        setCourse((c) => c && { ...c, pace: ev.pace })
      } else if (ev.type === 'placement.set') {
        setCourse((c) => c && { ...c, level: ev.level, placement: ev.placement })
      } else if (ev.type === 'capstone.set') {
        setCourse(
          (c) =>
            c && {
              ...c,
              capstones: c.capstones.some((k) => k.id === ev.capstone.id)
                ? c.capstones.map((k) => (k.id === ev.capstone.id ? ev.capstone : k))
                : [...c.capstones, ev.capstone],
            },
        )
      } else if (ev.type === 'source.updated') {
        setSources((all) => (all.some((s) => s.id === ev.source.id) ? all.map((s) => (s.id === ev.source.id ? ev.source : s)) : [...all, ev.source]))
      } else if (ev.type === 'source.removed') {
        setSources((all) => all.filter((s) => s.id !== ev.id))
      } else if (ev.type === 'map.set') {
        setCourse((c) => c && { ...c, concepts: ev.concepts, capstones: ev.capstones ?? c.capstones })
      } else if (ev.type === 'lesson.created') {
        addLesson(ev.lesson)
      } else if (ev.type === 'turn.done') {
        const { message } = ev
        patchLesson(ev.lesson_id, (l) => ({
          ...l,
          running: false,
          messages: message ? [...l.messages, message] : l.messages,
        }))
        setStreaming('')
        setActivity('')
        setWriting(false)
        if (!ev.ok && ev.error !== 'stopped') setError(ev.error ?? i18n.t('chat.turnFailed'))
      }
    }
    // a sitting opens with a few due reviews before the lesson
    const here = location.hash
    if (!start && navigator.onLine)
      api<{ due: number }>(`/api/courses/${courseId}/warmup`).then(
        (w) => {
          // only from the page that asked: a second answer, or one arriving after the learner moved on, does nothing
          // replaced, not pushed: going back from the lesson must not land on the warm-up again
          if (w.due && location.hash === here) location.replace(`#/review?then=${encodeURIComponent(here)}`)
        },
        () => {},
      )
    api<Source[]>(`/api/courses/${courseId}/sources`).then(setSources, () => {})
    api<CourseDetail>(`/api/courses/${courseId}`).then(
      (c) => {
        setCourse(c)
        const wanted = concept === null ? undefined : c.lessons.find((l) => l.concept_id === concept)
        setLessonId(wanted ? wanted.id : c.lessons[c.lessons.length - 1].id)
        if (start)
          api<Lesson>(`/api/courses/${courseId}/${start}`, {}).then(
            (created) => {
              setCourse((cur) => cur && { ...cur, lessons: [...cur.lessons, created] })
              setLessonId(created.id)
              location.hash = `#/course/${courseId}`
            },
            (err: Error) => setError(err.message),
          )
        if (!wanted && concept !== null)
          api<Lesson>(`/api/concepts/${concept}/lesson`, {}).then(
            (created) => {
              setCourse((cur) => cur && { ...cur, lessons: [...cur.lessons, created] })
              setLessonId(created.id)
            },
            (err: Error) => setError(err.message),
          )
        if (c.lessons.some((l) => l.running)) setActivity('thinking')
      },
      (e) => setError(e.message),
    )
    return () => source.close()
  }, [courseId, concept, start])

  useEffect(() => {
    // back at an unfinished unit after days away: the server decides whether it opens with a recap. Asked once the
    // lesson stays open a moment, so one shown on the way to another (a new unit being created) gets none.
    if (lessonId === null || !navigator.onLine) return
    const asked = setTimeout(() => api(`/api/lessons/${lessonId}/resume`, {}).catch(() => {}), 1500)
    return () => clearTimeout(asked)
  }, [lessonId])

  // follow new cards and messages only for a learner already at the end; one reading back stays where they are
  function nearEnd(): boolean {
    const main = lessonBottom.current?.closest('main')
    return !main || main.scrollHeight - main.scrollTop - main.clientHeight < 240
  }

  useEffect(() => {
    if (nearEnd()) lessonBottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [lesson?.blocks.length, lesson?.messages.length, course?.ranking.length, writing])

  useEffect(() => {
    if (streaming && nearEnd()) lessonBottom.current?.scrollIntoView({ block: 'end' })
  }, [streaming])

  function post(path: string, body: unknown) {
    api(path, body).catch((err: Error) => setError(err.message))
  }

  function send() {
    const text = draft.trim()
    if (!lesson || lesson.running || !text) return
    api<Message>(`/api/lessons/${lesson.id}/turns`, { text }).then(
      (message) => {
        patchLesson(lesson.id, (l) => ({ ...l, messages: [...l.messages, message] }))
        setDraft('')
        setChanging(false)
      },
      (err: Error) => setError(err.message),
    )
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  if (!course || !lesson) return <main className="home">{error && <div className="error">{error}</div>}</main>

  const showPlan = lesson.phase === 'interview' && course.ranking.length > 0
  const finished = lesson.concept_id !== null && lesson.blocks.some((b) => b.kind === 'done')
  const nextUnit = finished
    ? course.concepts.slice(course.concepts.findIndex((c) => c.id === lesson.concept_id) + 1).find((c) => !c.known && (c.mastery ?? 0) < 2 / 3)
    : undefined
  const stream = lessonStream(lesson.blocks, lesson.messages)
  const order = new Map(lesson.blocks.map((b, i) => [b.id, i]))
  const open = asking ?? lesson.phase === 'interview'
  const outline = outlineOf(lesson)
  const units = course.concepts.filter((c) => c.kind === 'concept')
  const unitsDone = units.filter((c) => unitDone(c, course.lessons.find((l) => l.concept_id === c.id))).length
  const reviewDue = units.filter((c) => c.due).length
  const empty = lesson.blocks.length === 0 && !showPlan
  const canPrepare = lesson.phase === 'lesson' && lesson.concept_id !== null && course.mode !== 'teacher' && !lesson.batch && !finished
  const batchCards = lesson.batch ? lesson.blocks.filter((b) => b.kind === 'quiz' && (b.data as QuizData).answer === null) : []
  const ready = batchCards.filter((b) => given[b.id] && ((b.data as QuizData).kind !== 'open' || given[b.id].self_correct !== undefined))

  return (
    <div className="workspace" data-pane={pane}>
      <nav className="map" aria-label={t('map.label')}>
        <div className="label">{t('map.label')}</div>
        {course.mode !== 'teacher' && units.length > 0 && (
          <div className="small">
            {reviewDue ? t('map.summary', { done: unitsDone, total: units.length, count: reviewDue }) : t('map.summaryDone', { done: unitsDone, total: units.length })}
          </div>
        )}
        {course.level && (
          <div className="level-row">
            <span>
              {t('map.level')} <span className="chip">{course.level}</span>
            </span>
          </div>
        )}
        {course.strands && course.concepts.length > 0 && (
          <LevelPanel
            level={course.level}
            strands={course.strands}
            vocabulary={course.vocabulary}
            units={course.concepts}
            disabled={lesson.running}
            onStart={(kind) =>
              api<Lesson>(`/api/courses/${course.id}/${kind}`, {}).then(
                (created) => {
                  addLesson(created)
                  showLesson(created.id)
                },
                (err: Error) => setError(err.message),
              )
            }
            story={course.lang !== null}
          />
        )}
        <details ref={sideMenu} className="side-menu">
          <summary className="btn">{t('map.menu')}</summary>
          <div className="side-menu-panel">
            <a className="btn as-link" href={`#/course/${course.id}/book`}>
              {t('book.export')}
            </a>
            <a className="btn as-link" href={`/api/courses/${course.id}/obsidian.zip`} download>
              {t('book.obsidian')}
            </a>
            {course.concepts.length > 0 && (
              <button
                type="button"
                className="btn"
                disabled={lesson.running}
                onClick={() =>
                  api<Lesson>(`/api/courses/${course.id}/placement/retake`, {}).then(
                    (created) => {
                      addLesson(created)
                      showLesson(created.id)
                      sideMenu.current!.open = false
                    },
                    (err: Error) => setError(err.message),
                  )
                }
              >
                {course.level ? t('map.retake') : t('map.take')}
              </button>
            )}
            {course.concepts.length > 0 && (
              <button
                type="button"
                className="btn"
                disabled={lesson.running}
                onClick={() => {
                  // The planning conversation lives in the interview lesson; the tutor revises the map from any lesson.
                  showLesson(course.lessons.find((l) => l.phase === 'interview')?.id ?? lesson.id)
                  sideMenu.current!.open = false
                  setAsking(true)
                  setChanging(true)
                  // after the click's render, once the drawer is open
                  requestAnimationFrame(() => document.getElementById('chat')?.focus())
                }}
              >
                {t('map.change')}
              </button>
            )}
            {course.mode !== 'teacher' && (
              <>
                <div className="pace" role="group" aria-label={t('pace.label')}>
                  {(['momentum', 'speed'] as const).map((pace) => (
                    <button
                      key={pace}
                      type="button"
                      className={course.pace === pace ? 'cat picked' : 'cat'}
                      aria-pressed={course.pace === pace}
                      onClick={() =>
                        api(`/api/courses/${course.id}/pace`, { pace }).then(
                          () => setCourse((c) => c && { ...c, pace }),
                          (err: Error) => setError(err.message),
                        )
                      }
                    >
                      {t(`pace.${pace}`)}
                    </button>
                  ))}
                </div>
                <div className="small">{t(`pace.${course.pace}Hint`)}</div>
              </>
            )}
            {course.cleaned && <div className="small muted">{t('map.cleaned', { date: day(course.cleaned) })}</div>}
            {course.concepts.length > 0 && <SourcesPanel courseId={course.id} sources={sources} onChange={setSources} onError={setError} />}
          </div>
        </details>
        {course.lessons
          .filter((l) => l.concept_id === null)
          .map((l) => (
            <button key={l.id} aria-current={l.id === lesson.id} onClick={() => showLesson(l.id)}>
              {lessonTitle(l, t)}
            </button>
          ))}
        {course.concepts.map((c, i) => {
          const conceptLesson = course.lessons.find((l) => l.concept_id === c.id)
          return (
            <div key={c.id} className="concept">
              {c.module !== course.concepts[i - 1]?.module && (
                <>
                  <strong dir="auto">{c.module}</strong>
                  {course.capstones
                    .filter((k) => k.module === c.module)
                    .map((k) => (
                      <div key={k.id} className="capstone" title={k.brief}>
                        <span className="small">{t('map.project', { title: k.title })}</span>
                        <progress value={k.done} max={k.milestones.length} />
                        <span className="small">{t('map.milestones', { done: k.done, total: k.milestones.length })}</span>
                      </div>
                    ))}
                </>
              )}
              <button aria-current={conceptLesson?.id === lesson.id} onClick={() => openConcept(c)}>
                <span className="concept-title">
                  <span className="concept-name" dir="auto">{c.kind === 'practice' ? practiceTitle(c.title, t) : c.title}</span>
                  {course.mode !== 'teacher' && (
                    <span className="marks">
                      {/* the slot stays when empty, so every unit's squares sit on the same line */}
                      {unitDone(c, conceptLesson) ? (
                        <span className="done-mark" role="img" aria-label={t('common.done')}>
                          ✓
                        </span>
                      ) : (
                        <span className="done-mark empty" />
                      )}
                      {c.kind !== 'practice' && (
                        <span className="mastery" aria-label={t('map.mastery', { n: squares(c) })} title={t('map.masteryHint')}>
                          {[1, 2, 3].map((n) => (
                            <i key={n} className={n <= squares(c) ? 'on' : ''} />
                          ))}
                        </span>
                      )}
                    </span>
                  )}
                </span>
                <span className="stats">{conceptStats(c, conceptLesson, t, course.mode === 'teacher')}</span>
              </button>
            </div>
          )
        })}
      </nav>

      <main ref={lessonBox} className="lesson">
        <h1 dir="auto">{lessonTitle(lesson, t)}</h1>
        {/* first, wherever the tutor posted it: the plan and the counter belong under the title */}
        {outline && (
          <OutlineCard
            key={lesson.id}
            data={outline}
            onTestOut={course.pace === 'speed' && !finished && !lesson.running ? (scope) => post(`/api/lessons/${lesson.id}/testout`, { scope }) : undefined}
          />
        )}
        {course.mode === 'teacher' && lesson.concept_id !== null && (
          <div className="small handouts">
            {t('handout.label')}{' '}
            <a href={`#/lesson/${lesson.id}/handout/teacher`}>{t('handout.teacher')}</a> ·{' '}
            <a href={`#/lesson/${lesson.id}/handout/student`}>{t('handout.student')}</a>
          </div>
        )}
        {lesson.phase === 'interview' &&
          (course.started ? (
            <ScopeCard course={course} />
          ) : (
            <ScopeForm
              disabled={lesson.running}
              onStart={(scope) =>
                api<CourseDetail>(`/api/courses/${course.id}/start`, scope).then(
                  ({ details, hours, started }) => {
                    setCourse((c) => c && { ...c, details, hours, started })
                  },
                  (err: Error) => setError(err.message),
                )
              }
            />
          ))}
        {stream.map((item) => {
          if ('message' in item) return <Remark key={`m${item.message.id}`} message={item.message} />
          const b = item.block
          const i = order.get(b.id)!
          if (b.kind === 'outline') return null
          const card = b.kind === 'question' ? (
            <QuestionCard
              key={b.id}
              block={b}
              disabled={lesson.running}
              onAnswer={(answer) => post(`/api/blocks/${b.id}/answer`, { answer })}
            />
          ) : b.kind === 'quiz' ? (
            <QuizCard
              key={b.id}
              id={b.id}
              question={b.markdown}
              data={b.data as QuizData}
              disabled={lesson.running}
              authored={course.mode === 'teacher'}
              offline={lesson.batch ? { given: given[b.id], onGive: (answer) => give(b.id, answer) } : undefined}
              onUnknown={lesson.phase === 'placement' ? () => post(`/api/blocks/${b.id}/quiz/unknown`, {}) : undefined}
              onSubmit={(answer, confidence) => post(`/api/blocks/${b.id}/quiz`, { answer, confidence })}
            />
          ) : b.kind === 'reading' ? (
            <ReadingCard
              key={b.id}
              id={b.id}
              text={b.markdown}
              data={b.data}
              speech={speech}
              onAdd={(word) => post(`/api/blocks/${b.id}/vocabulary`, { word })}
              onKnown={(word) => post(`/api/blocks/${b.id}/known`, { word })}
            />
          ) : b.kind === 'vocab' ? (
            <VocabCheckCard
              key={b.id}
              id={b.id}
              data={b.data}
              disabled={lesson.running}
              onSubmit={(known) => post(`/api/blocks/${b.id}/vocab`, { known })}
            />
          ) : b.kind === 'exercise' ? (
            <ExerciseCard
              key={b.id}
              block={b}
              disabled={lesson.running}
              commands={commands}
              authored={course.mode === 'teacher'}
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
            />
          ) : b.kind === 'challenge' ? (
            <ChallengeCard
              key={b.id}
              block={b}
              disabled={lesson.running}
              speech={speech}
              authored={course.mode === 'teacher'}
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
              onError={setError}
            />
          ) : b.kind === 'network' ? (
            <NetworkCard
              key={b.id}
              id={b.id}
              reason={b.markdown}
              data={b.data}
              disabled={lesson.running}
              onDecide={(allow) => post(`/api/blocks/${b.id}/network`, { allow })}
            />
          ) : b.kind === 'plot' ? (
            <PlotCard key={b.id} id={b.id} title={b.markdown} data={b.data} />
          ) : b.kind === 'figure' ? (
            <FigureCard key={b.id} id={b.id} caption={b.markdown} data={b.data} sketched={sketched} disabled={lesson.running} onRestore={() => post(`/api/blocks/${b.id}/restore`, {})} onRedraw={crafted ? (notes) => post(`/api/blocks/${b.id}/redraw`, { notes }) : undefined} />
          ) : b.kind === 'placement' ? (
            <section key={b.id} className="block">
              <div className="label">
                {t('block.placementResult')} <span className="chip">{(b.data as { level: string }).level}</span>
              </div>
              <Markdown>{b.markdown}</Markdown>
            </section>
          ) : b.kind === 'podcast' ? (
            <PodcastCard
              key={b.id}
              id={b.id}
              title={b.markdown}
              data={b.data}
              answered={(id) => (lesson.blocks.find((q) => q.id === id)?.data as QuizData | undefined)?.answer != null}
            />
          ) : b.kind === 'speaking' ? (
            <SpeakingCard
              key={b.id}
              block={b}
              disabled={lesson.running}
              speech={speech}
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
              onError={setError}
            />
          ) : (
            <section key={b.id} className="block">
              <div className="label">{lookup(`block.${b.kind}`, b.kind)}</div>
              <Markdown>{b.markdown}</Markdown>
            </section>
          )
          if (course.mode !== 'teacher' || b.kind === 'question') return card
          return (
            <Fragment key={b.id}>
              {card}
              <EditBar
                block={b}
                first={i === 0}
                last={i === lesson.blocks.length - 1}
                disabled={lesson.running}
                onError={setError}
              />
            </Fragment>
          )
        })}
        {showPlan && (
          <Plan
            ranking={course.ranking}
            mechanism={course.mechanism}
            accepted={course.concepts.length > 0 || course.lessons.some((l) => l.phase === 'placement')}
            prepared={course.mode === 'teacher'}
            disabled={lesson.running}
            onChoose={(mechanism) => post(`/api/courses/${course.id}/mechanism`, { mechanism })}
            onAccept={() => post(`/api/courses/${course.id}/plan/accept`, {})}
            onPlacement={() =>
              api<Lesson>(`/api/courses/${course.id}/placement`, {}).then(
                (created) => {
                  addLesson(created)
                  showLesson(created.id)
                },
                (err: Error) => setError(err.message),
              )
            }
          />
        )}
        {lesson.phase === 'placement' && course.placement && course.lessons.find((l) => l.phase === 'placement')?.id === lesson.id && !lesson.blocks.some((b) => b.kind === 'placement') && (
          <section className="block">
            <div className="label">
              {t('block.placementResult')} <span className="chip">{course.level}</span>
            </div>
            <Markdown>{course.placement}</Markdown>
          </section>
        )}
        {lesson.running && (empty || writing) && <Skeleton />}
        {lesson.batch && !lesson.running ? (
          <div className="lesson-next batch">
            <span className="small">{t('offline.answered', { n: ready.length, total: batchCards.length })}</span>
            {/* with nothing answered it leaves offline mode, the way out of a prepare that wrote no checks */}
            <button className={ready.length ? 'btn primary' : 'btn'} disabled={!online || sending} onClick={() => sendBatch(ready)}>
              {ready.length ? t('offline.send') : t('offline.leave')}
            </button>
          </div>
        ) : (
          canPrepare &&
          !lesson.running && (
            <div className="lesson-next batch">
              <span className="small">{t('offline.help')}</span>
              <button className="btn" disabled={!online} onClick={prepareOffline}>
                {t('offline.prepare')}
              </button>
            </div>
          )
        )}
        {nextUnit && !lesson.running && (
          <div className="lesson-next">
            <button className="btn primary" onClick={() => openConcept(nextUnit)}>
              {t('lesson.nextUnit', { title: nextUnit.title })}
            </button>
            <a className="btn as-link" href="#/sitting">
              {t('sitting.end')}
            </a>
          </div>
        )}
        {streaming && (
          <div className="remark">
            <Markdown>{streaming}</Markdown>
            <span className="caret" />
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div ref={lessonBottom} />
        {!open && (
          <button
            type="button"
            id="ask"
            className="btn primary ask"
            onClick={() => {
              setAsking(true)
              requestAnimationFrame(() => document.getElementById('chat')?.focus())
            }}
          >
            {t('chat.ask')}
            <span className="live" role="status">
              {lesson.running && ` · ${activity ? lookup(`activity.${activity}`, t('activity.working')) : t('activity.working')}`}
            </span>
          </button>
        )}
        <aside
          className={open ? 'chat drawer open' : 'chat drawer'}
          aria-label={t('chat.label')}
          hidden={!open}
          onKeyDown={(e) => {
            if (e.key === 'Escape') closeChat()
          }}
        >
          <div className="chat-head">
            <strong>{t('chat.tutor')}</strong>
            <span className={lesson.running ? 'status live' : 'status'} role="status">
              {lesson.running && (activity ? lookup(`activity.${activity}`, t('activity.working')) : t('activity.working'))}
            </span>
            <button type="button" className="link" onClick={closeChat}>
              {t('chat.close')}
            </button>
          </div>
          <div className="composer">
            <label htmlFor="chat">{t('chat.message')}</label>
            <textarea
              id="chat"
              className="field" dir="auto"
              rows={3}
              value={draft}
              placeholder={changing ? t('chat.changeHint') : undefined}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
            />
            <div className="row">
              {speech && <Mic onClip={(clip) => transcribe(clip).then((t) => setDraft((d) => (d ? `${d} ${t}` : t)))} onError={setError} />}
              {lesson.running && (
                <button className="btn" onClick={() => post(`/api/lessons/${lesson.id}/stop`, {})}>
                  {t('common.stop')}
                </button>
              )}
              <button className="btn primary" onClick={send} disabled={!online || lesson.running || !course.started || !draft.trim()}>
                {t('common.send')}
              </button>
            </div>
          </div>
        </aside>
      </main>

      <nav className="panes" aria-label={t('panes.label')}>
        {(['map', 'lesson'] as const).map((p) => (
          <button key={p} aria-pressed={pane === p} onClick={() => setPane(p)}>
            {p === 'map' ? t('map.label') : t('panes.lesson')}
            {p === 'lesson' && p !== pane && lesson.running && <span className="live"> · {t('activity.working')}</span>}
          </button>
        ))}
      </nav>
    </div>
  )
}

/** Push-to-talk: records while pressed, sends the clip to the recogniser, hands back the transcript. */
async function transcribe(clip: Blob, lang?: string): Promise<string> {
  const form = new FormData()
  form.append('audio', clip, 'clip.webm')
  const res = await fetch(`/api/stt${lang ? `?lang=${encodeURIComponent(lang)}` : ''}`, { method: 'POST', body: form })
  if (!res.ok) throw await failure(res)
  return (await res.json()).text
}

function Mic(props: { onClip: (clip: Blob) => Promise<void>; onError: (message: string) => void; label?: string; disabled?: boolean; limit?: number }) {
  const { t } = useTranslation()
  const [recording, setRecording] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const timer = useRef<number | undefined>(undefined)

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = []
      const rec = new MediaRecorder(stream)
      rec.ondataavailable = (e) => chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        props.onClip(new Blob(chunks, { type: rec.mimeType })).catch((err: Error) => props.onError(err.message))
      }
      rec.start()
      recorder.current = rec
      setRecording(true)
      if (props.limit) timer.current = window.setTimeout(stop, props.limit * 1000)
    } catch (err) {
      props.onError((err as Error).message)
    }
  }

  function stop() {
    window.clearTimeout(timer.current)
    recorder.current?.stop()
    recorder.current = null
    setRecording(false)
  }

  return (
    <button
      type="button"
      className={recording ? 'btn recording' : 'btn'}
      disabled={props.disabled && !recording}
      aria-label={recording ? t('speaking.stopRecording') : (props.label ?? t('speaking.speakMessage'))}
      title={recording ? t('speaking.stopRecording') : (props.label ?? t('speaking.speakMessage'))}
      onClick={recording ? stop : start}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
      {recording ? ` ${t('common.stop')}` : props.label ? ` ${props.label}` : ''}
    </button>
  )
}

type Theme = 'light' | 'dark'

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem('theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* storage may be unavailable */
  }
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Light or dark; the system choice until the learner picks one, which the browser remembers. */
function ThemeToggle() {
  const { t } = useTranslation()
  const [theme, setTheme] = useState<Theme>(readTheme)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  function flip() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* storage may be unavailable */
    }
  }
  return (
    <button type="button" className="btn theme" onClick={flip} title={theme === 'dark' ? t('header.toLight') : t('header.toDark')} aria-label={t('header.toggleTheme')}>
      {theme === 'dark' ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  )
}

export default function App() {
  const hash = useHash()
  const { t } = useTranslation()
  const online = useOnline()
  const [agent, setAgent] = useState('')
  const [speech, setSpeech] = useState(false)
  const [pdf, setPdf] = useState(false)
  const [commands, setCommands] = useState(true)
  const [crafted, setCrafted] = useState(false)
  const { profiles, current, select, reload } = useProfiles()
  const [chosen, setChosen] = useState<Locale>(browserLocale)
  const [localeError, setLocaleError] = useState('')
  const locale = current?.locale ?? chosen
  useEffect(() => {
    i18n.changeLanguage(locale)
  }, [locale])

  function switchLocale(next: Locale) {
    setLocaleError('')
    const saved = current ? api(`/api/profiles/${current.id}/locale`, { locale: next }).then(reload) : Promise.resolve()
    saved.then(
      () => {
        rememberLocale(next)
        setChosen(next)
      },
      (err: Error) => setLocaleError(err.message),
    )
  }
  useEffect(() => {
    api<{ agent: string; speech: boolean; pdf: boolean; commands: boolean; crafted: boolean }>('/api/meta').then(
      (m) => {
        setAgent(m.agent)
        setSpeech(m.speech)
        setPdf(m.pdf)
        setCommands(m.commands)
        setCrafted(m.crafted)
      },
      () => {},
    )
  }, [])
  const match = hash.match(/^#\/course\/(\d+)(?:\?concept=(\d+)|\?start=(episode|writing))?$/)
  const review = hash.match(/^#\/review(?:\?then=(.*))?$/)
  const book = hash.match(/^#\/course\/(\d+)\/book$/)
  const handout = hash.match(/^#\/lesson\/(\d+)\/handout\/(student|teacher)$/)

  function page() {
    if (!profiles) return null
    if (!current)
      return (
        <FirstProfile
          locale={locale}
          onCreated={(created) => {
            reload()
            select(created.id)
          }}
        />
      )
    if (match)
      return (
        <Workspace
          key={match[1]}
          courseId={Number(match[1])}
          speech={speech}
          commands={commands}
          crafted={crafted}
          sketched={current.sketch}
          concept={match[2] ? Number(match[2]) : null}
          start={(match[3] as 'episode' | 'writing' | undefined) ?? null}
        />
      )
    if (book) return <Book key={book[1]} courseId={Number(book[1])} learner={current.name} pdf={pdf} sketched={current.sketch} />
    if (handout) return <Handout key={handout[0]} lessonId={Number(handout[1])} version={handout[2] as 'student' | 'teacher'} pdf={pdf} />
    if (review) return <Review profile={current.id} then={review[1] ? decodeURIComponent(review[1]) : null} />
    if (hash === '#/errors') return <ErrorsPage profile={current.id} />
    if (hash === '#/sitting') return <SittingPage profile={current.id} />
    if (hash === '#/commands') return <CommandsPage profile={current.id} />
    if (hash === '#/profile')
      return <ProfilePage profiles={profiles} current={current} locale={locale} onSelect={select} onChanged={reload} />
    return <Home key={current.id} profile={current.id} teacher={current.mode === 'teacher'} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="wordmark" href="#/" title="wise-scholar">
          <Logo />
        </a>
        <span className="grow" />
        <span className="status">{t('header.agent', { agent })}</span>
        <ThemeToggle />
        {localeError && <span className="error">{localeError}</span>}
        <select className="btn locale" aria-label={t('header.language')} value={locale} onChange={(e) => switchLocale(e.target.value as Locale)}>
          {Object.entries(LOCALES).map(([code, name]) => (
            <option key={code} value={code} lang={code}>
              {name}
            </option>
          ))}
        </select>
        {current && (
          <a className="small" href="#/sitting">
            {t('sitting.end')}
          </a>
        )}
        {current && (
          <a className="btn as-link" href="#/profile">
            {current.name}
          </a>
        )}
      </header>
      {!online && (
        <div className="offline-banner" role="status">
          {t('offline.banner')}
        </div>
      )}
      {page()}
    </div>
  )
}
