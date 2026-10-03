import { Fragment, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import Markdown from './Md'
import { api } from './api'
import Logo from './Logo'
import { QuizCard, Review, ReviewPanels } from './Quiz'
import type { QuizData } from './Quiz'
import { LevelPanel, ReadingCard, VocabCheckCard } from './Language'
import { PodcastCard } from './Podcast'
import { ErrorsPage } from './Errors'
import { Correction } from './Diff'
import { FigureCard } from './Figure'
import { SourcesPanel } from './Sources'
import type { Source } from './Sources'
import { usePlayer } from './player'
import { splitBy } from './text'
import { FirstProfile, ProfilePage } from './Profile'
import { useProfiles } from './profiles'

type Course = {
  id: number
  topic: string
  slug: string
  mechanism: string | null
  level: string | null
  archived: number
}
type Message = { id: number; lesson_id: number; role: 'learner' | 'tutor'; text: string; created: string }
type QuestionData = { options: string[]; answer: string | null }
type ChallengeData = {
  attempts: string[]
  hints: string[]
  gave_up: boolean
  solved: boolean
  solution: string | null
  reveal_after: number
  max_hints: number
  writing?: boolean
  fluency?: boolean
  marks?: string[]
  spoken?: boolean
  teachback?: boolean
  pretest?: boolean
  milestone?: boolean
  transfer?: boolean
  lang?: string
  words?: [number, number] | null
  structure?: string
}
type Scored = { word: string; score: number }
type SpeakingData = ChallengeData & { speaking: 'read' | 'shadow'; lang: string; scores: { words: Scored[]; heard: string | null; score: number }[] }
type Block = { id: number; lesson_id: number; kind: string; markdown: string; data: unknown; created: string }
type Concept = { id: number; module: string; title: string; known: number; mastery: number | null }
type Lesson = {
  id: number
  title: string
  phase: string
  concept_id: number | null
  messages: Message[]
  blocks: Block[]
  running: boolean
}
type Ranked = {
  mechanism: string
  rationale: string
  title: string
  summary: string
  evidence: { source: string; finding: string; url: string }[]
}
type Capstone = {
  id: number
  module: string
  title: string
  brief: string
  folder: string
  done: number
  milestones: { id: number; concept_id: number; concept: string; deliverable: string; done: number }[]
}
type CourseDetail = Course & {
  placement: string | null
  lang: string | null
  capstones: Capstone[]
  ranking: Ranked[]
  concepts: Concept[]
  lessons: Lesson[]
  strands: { input: number; output: number; language: number; fluency: number } | null
  vocabulary: { total: number; due: number; tier?: number; tier_size?: number; tier_known?: number; tier_words?: number }
}

type TutorEvent =
  | { type: 'turn.started'; lesson_id: number }
  | { type: 'chat.delta'; lesson_id: number; text: string }
  | { type: 'activity'; lesson_id: number; tool: string }
  | { type: 'block.added' | 'block.updated'; lesson_id: number; block: Block }
  | { type: 'plan.ranked'; ranking: Ranked[]; mechanism: string }
  | { type: 'plan.chosen'; mechanism: string }
  | { type: 'placement.set'; level: string; placement: string }
  | { type: 'map.set'; concepts: Concept[] }
  | { type: 'capstone.set'; capstone: Capstone }
  | { type: 'source.updated'; source: Source }
  | { type: 'source.removed'; id: number }
  | { type: 'lesson.created'; lesson: Lesson }
  | { type: 'turn.done'; lesson_id: number; ok: boolean; error: string | null; message: Message | null }

const BLOCK_LABELS: Record<string, string> = { prose: 'Read', example: 'Example' }
const ACTIVITY_LABELS: Record<string, string> = {
  add_block: 'writing in the lesson area…',
  ask: 'preparing a question…',
  note_learner: 'noting what you said…',
  list_playbooks: 'weighing teaching approaches…',
  get_playbook: 'reading a playbook…',
  rank_mechanisms: 'ranking teaching approaches…',
  set_course_map: 'laying out the course…',
  pose_challenge: 'preparing a challenge…',
  pose_exercise: 'preparing an exercise…',
  add_reading: 'writing a text for you…',
  add_figure: 'drawing a figure…',
  pose_writing: 'preparing a writing task…',
  bash: 'testing in the workspace…',
  read: 'reading your files…',
  write: 'writing exercise files…',
  edit: 'writing exercise files…',
  give_hint: 'writing a hint…',
  reveal: 'opening the solution…',
  mark_solved: 'checking your answer…',
  set_placement: 'working out your level…',
  pose_vocab_check: 'picking words to check…',
  pose_speaking: 'preparing a speaking task…',
  pose_teachback: 'preparing a teach-back…',
  make_podcast: 'writing a cast…',
  pose_quiz: 'preparing a quick check…',
  grade_quiz: 'grading your answer…',
}
const LESSON_AREA_TOOLS = [
  'add_block',
  'ask',
  'rank_mechanisms',
  'pose_challenge',
  'pose_exercise',
  'pose_quiz',
  'add_reading',
  'add_figure',
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
  review_minutes: number
  units: { course_id: number; topic: string; concept_id: number | null; title: string }[]
  cast: { id: number; lesson_id: number; title: string; course_id: number } | null
  errors: number
  extras: { course_id: number; topic: string; kind: 'episode' | 'writing' }[]
}

function unitHash(u: TodayPlan['units'][number]): string {
  return u.concept_id === null ? `#/course/${u.course_id}` : `#/course/${u.course_id}?concept=${u.concept_id}`
}

/** The sitting as one plan: reviews first, then the next unit. Start walks through both. */
function Today({ profile }: { profile: number }) {
  const [plan, setPlan] = useState<TodayPlan | null>(null)
  useEffect(() => {
    api<TodayPlan>(`/api/today?profile=${profile}`).then(setPlan, () => {})
  }, [profile])
  if (!plan || (plan.due === 0 && plan.units.length === 0)) return null
  const unit = plan.units[0]
  const start = plan.due > 0 ? `#/review${unit ? `?then=${encodeURIComponent(unitHash(unit))}` : ''}` : unit ? unitHash(unit) : '#/review'
  return (
    <section className="block today">
      <div className="label">Today · a sitting of 30 minutes</div>
      <ol className="plan-steps">
        {plan.due > 0 && (
          <li>
            {plan.due} {plan.due === 1 ? 'review' : 'reviews'} across your courses <span className="muted">· about {Math.max(1, plan.review_minutes)} min</span>
          </li>
        )}
        {unit && (
          <li>
            {unit.topic}: {unit.title} <span className="muted">· the rest of the sitting</span>
          </li>
        )}
        {plan.units.slice(1, 4).map((u) => (
          <li key={u.course_id} className="muted">
            Later: {u.topic}, {u.title}
          </li>
        ))}
        {plan.cast && (
          <li className="muted">
            A cast is ready to listen to: <a href={`#/course/${plan.cast.course_id}`}>{plan.cast.title}</a>
          </li>
        )}
        {plan.extras.map((x) => (
          <li key={`${x.course_id}-${x.kind}`} className="muted">
            <a href={`#/course/${x.course_id}?start=${x.kind}`}>
              {x.kind === 'episode' ? `Next episode of your ${x.topic} story` : `A writing session in ${x.topic}`}
            </a>{' '}
            · that strand is behind
          </li>
        ))}
        {plan.errors > 0 && (
          <li className="muted">
            <a href="#/errors">{plan.errors} open {plan.errors === 1 ? 'entry' : 'entries'} in your error notebook</a>
          </li>
        )}
      </ol>
      <div className="row">
        <a className="btn primary as-link" href={start}>
          Start
        </a>
      </div>
    </section>
  )
}

function Home({ profile }: { profile: number }) {
  const [courses, setCourses] = useState<Course[]>([])
  const [topic, setTopic] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api<Course[]>(`/api/courses?profile=${profile}`).then(setCourses, (e) => setError(e.message))
  }, [profile])

  async function start(e: FormEvent) {
    e.preventDefault()
    try {
      const course = await api<Course>('/api/courses', { topic, profile_id: profile })
      location.hash = `#/course/${course.id}`
    } catch (err) {
      setError((err as Error).message)
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

  const active = courses.filter((c) => !c.archived)
  const archived = courses.filter((c) => c.archived)

  return (
    <main className="home">
      <form className="topic-form" onSubmit={start}>
        <label htmlFor="topic">What do you want to learn?</label>
        <div className="row">
          <input
            id="topic"
            className="field"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="A language, a tool, a field…"
          />
          <button className="btn primary" disabled={!topic.trim()}>
            Start
          </button>
        </div>
        <div className="muted">The tutor interviews you first, then picks how to teach it.</div>
      </form>
      {error && <div className="error">{error}</div>}
      <Today profile={profile} />
      <ReviewPanels profile={profile} />
      {active.length > 0 && (
        <section>
          <div className="label gap-below">Your courses</div>
          <div className="courses">
            {active.map((c) => (
              <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} />
            ))}
          </div>
        </section>
      )}
      {archived.length > 0 && (
        <details className="archived">
          <summary className="label">Archived courses · {archived.length}</summary>
          <div className="courses">
            {archived.map((c) => (
              <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} />
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
}) {
  const { course } = props
  const [confirming, setConfirming] = useState(false)
  const menu = useRef<HTMLDetailsElement>(null)

  function close() {
    setConfirming(false)
    if (menu.current) menu.current.open = false
  }

  return (
    <div className="course-card">
      <a href={`#/course/${course.id}`}>
        <strong>{course.topic}</strong>
        <span className="muted">{course.mechanism ?? 'interview not finished'}</span>
      </a>
      <details ref={menu} className="menu" name="course-menu" onToggle={() => setConfirming(false)}>
        <summary aria-label={`Options for ${course.topic}`}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="12" cy="5" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="12" cy="19" r="2" />
          </svg>
        </summary>
        <div className="menu-panel">
          {confirming ? (
            <>
              <div>
                Delete “{course.topic}” with its lessons, reviews and exercise files? This cannot be undone.
              </div>
              <button type="button" className="btn danger" onClick={() => props.onDelete(course)}>
                Delete course
              </button>
              <button type="button" className="btn" onClick={close}>
                Cancel
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
                {course.archived ? 'Unarchive' : 'Archive'}
              </button>
              <button type="button" className="btn" onClick={() => setConfirming(true)}>
                Delete…
              </button>
            </>
          )}
        </div>
      </details>
    </div>
  )
}

function Skeleton() {
  return (
    <section className="block skeleton" role="status" aria-label="The tutor is working">
      <span style={{ width: '22%' }} />
      <span style={{ width: '92%' }} />
      <span style={{ width: '78%' }} />
      <span style={{ width: '54%' }} />
    </section>
  )
}

function QuestionCard(props: { block: Block; disabled: boolean; onAnswer: (answer: string) => void }) {
  const [text, setText] = useState('')
  const { options, answer } = props.block.data as QuestionData

  if (answer !== null)
    return (
      <section id={`block-${props.block.id}`} className="block answered">
        <div className="muted">{props.block.markdown}</div>
        <span className="chip">{answer}</span>
      </section>
    )

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) props.onAnswer(text.trim())
  }

  return (
    <section id={`block-${props.block.id}`} className="block question">
      <h2>{props.block.markdown}</h2>
      <div className="options">
        {options.map((o) => (
          <button key={o} className="btn option" disabled={props.disabled} onClick={() => props.onAnswer(o)}>
            {o}
          </button>
        ))}
      </div>
      <form onSubmit={submit}>
        <label htmlFor={`own-${props.block.id}`}>Or say it in your own words</label>
        <div className="row">
          <input
            id={`own-${props.block.id}`}
            className="field"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn primary" disabled={props.disabled || !text.trim()}>
            Answer
          </button>
        </div>
      </form>
    </section>
  )
}

function ChallengeCard(props: { block: Block; disabled: boolean; speech: boolean; onAct: Act; onError: (m: string) => void }) {
  const [text, setText] = useState('')
  const d = props.block.data as ChallengeData
  const open = !d.solved && d.solution === null
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
        {d.transfer
          ? 'Transfer: same idea, new ground, no hints'
          : d.milestone
          ? 'Capstone milestone'
          : d.pretest
          ? 'Before we start: try it'
          : d.teachback
          ? `Explain it in 60 seconds${props.speech ? ', out loud' : ''}`
          : d.spoken
            ? 'Listen and answer by speaking'
            : d.writing
              ? d.fluency
                ? 'Write fast'
                : 'Write'
              : 'Work it out'}
        {d.solved && <span className="chip">{d.writing ? 'Done' : 'Solved'}</span>}
        {d.spoken && d.lang && (
          <button type="button" className="btn" onClick={() => (player.current ? player.stop() : player.play([props.block.markdown]))}>
            {player.current ? 'Stop' : 'Listen'}
          </button>
        )}
      </div>
      {!(d.spoken && d.lang) && <Markdown>{props.block.markdown}</Markdown>}
      {player.error && <div className="error">{player.error}</div>}

      <Ladder data={d} />

      {open && (
        <>
          <form onSubmit={submit}>
            <label htmlFor={`attempt-${props.block.id}`}>
              Your answer
              {d.words && (
                <span className="muted">
                  {' '}
                  · {d.words[0]} to {d.words[1]} words{d.structure ? `, using ${d.structure}` : ''} · {text.trim() ? text.trim().split(/\s+/).length : 0} so far
                </span>
              )}
            </label>
            <textarea
              id={`attempt-${props.block.id}`}
              className="field"
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
                Submit attempt
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
  const d = props.block.data as SpeakingData
  const open = !d.solved && d.solution === null
  const player = usePlayer(d.lang, props.speech)
  const marks = d.marks ?? []

  async function upload(clip: Blob) {
    const form = new FormData()
    form.append('audio', clip, 'clip.webm')
    const res = await fetch(`/api/blocks/${props.block.id}/speak`, { method: 'POST', body: form })
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  }

  return (
    <section id={`block-${props.block.id}`} className="block challenge speaking">
      <div className="label">
        {d.speaking === 'shadow' ? 'Listen, then say it the same way' : 'Read aloud'}
        {d.solved && <span className="chip">Done</span>}
        <button type="button" className="btn" onClick={() => (player.current ? player.stop() : player.play([props.block.markdown]))}>
          {player.current ? 'Stop' : 'Listen'}
        </button>
      </div>
      {(d.speaking === 'read' || d.scores.length > 0) && (
        <p className="spoken-text" lang={d.lang}>
          {splitBy(props.block.markdown, marks).map((piece, j) => (piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text))}
        </p>
      )}
      {player.error && <div className="error">{player.error}</div>}
      {d.scores.map((a, i) => (
        <div key={i} className="attempt">
          <span className="label">
            Attempt {i + 1} · {Math.round(a.score * 100)}%
          </span>
          <span lang={d.lang}>
            {a.words.map((w, j) => (
              <span key={j} className={w.score < WEAK_WORD ? 'word weak' : 'word'} title={`${Math.round(w.score * 100)}%`}>
                {w.word}{' '}
              </span>
            ))}
            {a.heard !== null && <span className="small"> · heard: “{a.heard}”</span>}
          </span>
        </div>
      ))}
      <HintList data={d} />
      {open && (
        <>
          <div className="row">
            <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />
            <Mic onClip={upload} onError={props.onError} label="Record" disabled={props.disabled} />
          </div>
          <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />
        </>
      )}
    </section>
  )
}

function Ladder({ data: d }: { data: ChallengeData }) {
  return (
    <>
      {d.attempts.map((a, i) => (
        <div key={i} className="attempt">
          <span className="label">Attempt {i + 1}</span>
          <span>
            {splitBy(a, i === d.attempts.length - 1 ? (d.marks ?? []) : []).map((piece, j) =>
              piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text,
            )}
          </span>
        </div>
      ))}
      <HintList data={d} />
    </>
  )
}

function HintList({ data: d }: { data: ChallengeData }) {
  return (
    <>
      {d.hints.map((h, i) => (
        <div key={i} className="hint">
          <div className="label">
            {d.writing ? 'Prompt' : 'Hint'} {i + 1} of {d.max_hints}
            {d.writing && ' · not the correction'}
          </div>
          <Markdown>{h}</Markdown>
        </div>
      ))}
      {d.solution !== null && (
        <div className="solution">
          <div className="label">{d.writing ? 'Corrected text' : 'Solution'}</div>
          {d.writing && d.attempts.length > 0 ? (
            <Correction attempt={d.attempts[d.attempts.length - 1]} corrected={d.solution} />
          ) : (
            <Markdown>{d.solution}</Markdown>
          )}
        </div>
      )}
    </>
  )
}

function HintButton(props: { data: ChallengeData; disabled: boolean; onAct: Act }) {
  const { hints, max_hints } = props.data
  return (
    <button
      type="button"
      className="btn"
      disabled={props.disabled || hints.length >= max_hints}
      onClick={() => props.onAct('hint')}
    >
      {hints.length ? 'Next hint' : 'Hint'}
    </button>
  )
}

function LockedRow(props: { data: ChallengeData; disabled: boolean; onAct: Act }) {
  const attemptsLeft = props.data.reveal_after - props.data.attempts.length
  return (
    <div className="locked">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="1" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
      <span className="grow">
        {attemptsLeft > 0
          ? `${props.data.writing ? 'Corrected text' : 'Solution'} locked. Opens after ${attemptsLeft} more ${attemptsLeft === 1 ? 'attempt' : 'attempts'}, or when you give up.`
          : 'You can ask the tutor for the solution now, or keep trying.'}
      </span>
      <button type="button" className="link" disabled={props.disabled} onClick={() => props.onAct('give-up')}>
        {attemptsLeft > 0 ? 'Give up' : 'Show solution'}
      </button>
    </div>
  )
}

type ExerciseData = ChallengeData & {
  files: string[]
  run: string
  last_run: { exit_code: number | null; output: string } | null
}
type ExerciseFile = { path: string; absolute: string; content: string | null }

function ExerciseCard(props: { block: Block; disabled: boolean; onAct: Act }) {
  const d = props.block.data as ExerciseData
  const [files, setFiles] = useState<ExerciseFile[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const open = !d.solved && d.solution === null
  const blockId = props.block.id

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
        {d.milestone ? 'Capstone milestone' : 'Exercise'}
        {d.solved && <span className="chip">Solved</span>}
      </div>
      <Markdown>{props.block.markdown}</Markdown>

      {files.map((f) => (
        <div key={f.path} className="file">
          <div className="file-head">
            <code>{f.absolute}</code>
            <button type="button" className="link" onClick={() => navigator.clipboard.writeText(f.absolute)}>
              Copy path
            </button>
          </div>
          {f.content === null ? (
            <pre>This file is missing from the workspace.</pre>
          ) : (
            <div className="file-body">
              <Markdown>{`\`\`\`\`${f.path.split('.').pop() ?? ''}\n${f.content}\n\`\`\`\``}</Markdown>
            </div>
          )}
        </div>
      ))}
      <div className="small">Edit the file in your own editor. This view follows what is saved on disk.</div>

      <div className="row">
        <code className="grow">$ {d.run}</code>
        {open && <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />}
        <button type="button" className="btn" disabled={running} onClick={run}>
          {running ? 'Running…' : 'Run'}
        </button>
        {open && (
          <button type="button" className="btn primary" disabled={props.disabled} onClick={() => props.onAct('check')}>
            Check with tutor
          </button>
        )}
      </div>

      {d.last_run && (
        <div className="file">
          <div className="file-head">
            <span className="label">
              Output · {d.last_run.exit_code === null ? 'stopped' : `exit code ${d.last_run.exit_code}`}
            </span>
          </div>
          <pre className={d.last_run.exit_code === 0 ? '' : 'failed'}>{d.last_run.output || '(no output)'}</pre>
        </div>
      )}
      {error && <div className="error">{error}</div>}

      <Ladder data={d} />
      {open && <LockedRow data={d} disabled={props.disabled} onAct={props.onAct} />}
    </section>
  )
}

const CARD_KINDS = new Set(['question', 'challenge', 'exercise', 'quiz', 'reading', 'vocab', 'speaking', 'podcast'])

function cardLabel(b: Block): string {
  const d = (b.data ?? {}) as { writing?: boolean; teachback?: boolean; pretest?: boolean; milestone?: boolean; transfer?: boolean; files?: string[]; title?: string }
  const head = b.markdown.replace(/[*_`#>]/g, '').split('\n')[0].trim()
  const short = head.length > 48 ? `${head.slice(0, 47)}…` : head
  if (b.kind === 'question') return `Question · ${short}`
  if (b.kind === 'quiz') return `${d.pretest ? 'Pretest' : 'Quick check'} · ${short}`
  if (b.kind === 'reading') return `Reading · ${d.title ?? short}`
  if (b.kind === 'vocab') return 'Vocabulary check'
  if (b.kind === 'speaking') return `Speaking · ${short}`
  if (b.kind === 'podcast') return `Cast · ${short}`
  if (b.kind === 'exercise') return `${d.milestone ? 'Milestone' : 'Exercise'} · ${d.files?.[0] ?? short}`
  return `${d.transfer ? 'Transfer' : d.milestone ? 'Milestone' : d.pretest ? 'Pretest' : d.teachback ? 'Teach-back' : d.writing ? 'Writing' : 'Challenge'} · ${short}`
}

/** Which cards were posed before each message: the chat gets a labelled divider there. Key -1 = after the last message. */
function cardDividers(lesson: Lesson): Map<number, Block[]> {
  const cards = lesson.blocks.filter((b) => CARD_KINDS.has(b.kind))
  const out = new Map<number, Block[]>()
  let next = 0
  for (const m of lesson.messages) {
    // A learner message from the same second came first: the card it triggered belongs after it.
    while (next < cards.length && (cards[next].created < m.created || (cards[next].created === m.created && m.role === 'tutor'))) {
      out.set(m.id, [...(out.get(m.id) ?? []), cards[next]])
      next++
    }
  }
  if (next < cards.length) out.set(-1, cards.slice(next))
  return out
}

function CardDivider({ block }: { block: Block }) {
  return (
    <button
      type="button"
      className="divider"
      onClick={() => document.getElementById(`block-${block.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
    >
      <span>{cardLabel(block)}</span>
    </button>
  )
}

function conceptStats(concept: Concept, lesson: Lesson | undefined): string {
  if (!lesson) return concept.known ? 'placed out' : 'not started'
  const cs = lesson.blocks
    .filter((b) => b.kind === 'challenge' || b.kind === 'exercise' || b.kind === 'speaking')
    .map((b) => b.data as ChallengeData)
  if (cs.length === 0) return 'started'
  const hints = cs.reduce((n, c) => n + c.hints.length, 0)
  const gaveUp = cs.filter((c) => c.gave_up).length
  return [
    `${cs.filter((c) => c.solved).length}/${cs.length} solved`,
    hints > 0 && `${hints} ${hints === 1 ? 'hint' : 'hints'}`,
    gaveUp > 0 && `gave up ${gaveUp}×`,
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
}) {
  return (
    <section className="plan">
      <div className="label">How I plan to teach this · ranked for you</div>
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
              {i + 1} · {r.title}
            </strong>
            <span>{r.rationale}</span>
            <span className="muted">{r.summary}</span>
            <span className="evidence">
              Evidence:{' '}
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
      <div className="muted">Always on, whatever you pick: hints before answers, confidence-rated checks, spaced reviews.</div>
      {!props.accepted && (
        <div className="block next-step">
          <div className="label">Next · placement check</div>
          <div>
            About 8 questions, harder or easier depending on your answers. It decides where the course starts and what
            you can skip.
          </div>
          <div className="row">
            <button className="btn primary" disabled={props.disabled} onClick={props.onPlacement}>
              Start placement check
            </button>
            <button className="btn" disabled={props.disabled} onClick={props.onAccept}>
              Skip, start from the beginning
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function Workspace({ courseId, speech, concept, start }: { courseId: number; speech: boolean; concept: number | null; start: 'episode' | 'writing' | null }) {
  const [course, setCourse] = useState<CourseDetail | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [lessonId, setLessonId] = useState<number | null>(null)
  const [streaming, setStreaming] = useState('')
  const [activity, setActivity] = useState('')
  const [writing, setWriting] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const chatBottom = useRef<HTMLDivElement>(null)
  const lessonBottom = useRef<HTMLDivElement>(null)

  const lesson = course?.lessons.find((l) => l.id === lessonId) ?? null

  function patchLesson(id: number, patch: (l: Lesson) => Lesson) {
    setCourse((c) => c && { ...c, lessons: c.lessons.map((l) => (l.id === id ? patch(l) : l)) })
  }

  function addLesson(lesson: Lesson) {
    setCourse((c) => c && (c.lessons.some((l) => l.id === lesson.id) ? c : { ...c, lessons: [...c.lessons, lesson] }))
  }

  function openConcept(concept: Concept) {
    const existing = course?.lessons.find((l) => l.concept_id === concept.id)
    if (existing) return setLessonId(existing.id)
    api<Lesson>(`/api/concepts/${concept.id}/lesson`, {}).then(
      (created) => {
        addLesson(created)
        setLessonId(created.id)
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
        setActivity('thinking…')
        setError('')
      } else if (ev.type === 'chat.delta') {
        setActivity('')
        setStreaming((s) => s + ev.text)
      } else if (ev.type === 'activity') {
        setActivity(ACTIVITY_LABELS[ev.tool] ?? 'working…')
        setWriting(LESSON_AREA_TOOLS.includes(ev.tool))
      } else if (ev.type === 'block.added') {
        setWriting(false)
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: [...l.blocks, ev.block] }))
        refreshTotals()
      } else if (ev.type === 'block.updated') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, blocks: l.blocks.map((b) => (b.id === ev.block.id ? ev.block : b)) }))
        refreshTotals()
      } else if (ev.type === 'plan.ranked') {
        setWriting(false)
        setCourse((c) => c && { ...c, ranking: ev.ranking, mechanism: ev.mechanism })
      } else if (ev.type === 'plan.chosen') {
        setCourse((c) => c && { ...c, mechanism: ev.mechanism })
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
        setCourse((c) => c && { ...c, concepts: ev.concepts })
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
        if (!ev.ok && ev.error !== 'stopped') setError(ev.error ?? 'the turn failed')
      }
    }
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
        if (c.lessons.some((l) => l.running)) setActivity('thinking…')
      },
      (e) => setError(e.message),
    )
    return () => source.close()
  }, [courseId, concept, start])

  useEffect(() => {
    chatBottom.current?.scrollIntoView({ block: 'end' })
  }, [lesson?.messages.length, streaming])

  useEffect(() => {
    lessonBottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [lesson?.blocks.length, course?.ranking.length, writing])

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
  const dividers = cardDividers(lesson)
  const empty = lesson.blocks.length === 0 && !showPlan

  return (
    <div className="workspace">
      <nav className="map" aria-label="Course map">
        <div className="label">Course map</div>
        {(course.level || course.concepts.length > 0) && (
          <div className="level-row">
            {course.level && (
              <span>
                Level <span className="chip">{course.level}</span>
              </span>
            )}
            {course.concepts.length > 0 && (
              <button
                type="button"
                className="link"
                disabled={lesson.running}
                onClick={() =>
                  api<Lesson>(`/api/courses/${course.id}/placement/retake`, {}).then(
                    (created) => {
                      addLesson(created)
                      setLessonId(created.id)
                    },
                    (err: Error) => setError(err.message),
                  )
                }
              >
                {course.level ? 'Retake placement' : 'Take the placement check'}
              </button>
            )}
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
                  setLessonId(created.id)
                },
                (err: Error) => setError(err.message),
              )
            }
            story={course.lang !== null}
          />
        )}
        {course.concepts.length > 0 && <SourcesPanel courseId={course.id} sources={sources} onChange={setSources} onError={setError} />}
        {course.lessons
          .filter((l) => l.concept_id === null)
          .map((l) => (
            <button key={l.id} aria-current={l.id === lesson.id} onClick={() => setLessonId(l.id)}>
              {l.title}
            </button>
          ))}
        {course.concepts.map((c, i) => {
          const conceptLesson = course.lessons.find((l) => l.concept_id === c.id)
          return (
            <div key={c.id} className="concept">
              {c.module !== course.concepts[i - 1]?.module && (
                <>
                  <strong>{c.module}</strong>
                  {course.capstones
                    .filter((k) => k.module === c.module)
                    .map((k) => (
                      <div key={k.id} className="capstone" title={k.brief}>
                        <span className="small">Project · {k.title}</span>
                        <progress value={k.done} max={k.milestones.length} />
                        <span className="small">
                          {k.done} of {k.milestones.length} milestones
                        </span>
                      </div>
                    ))}
                </>
              )}
              <button aria-current={conceptLesson?.id === lesson.id} onClick={() => openConcept(c)}>
                <span className="concept-title">
                  {c.title}
                  <span className="mastery" aria-label={`mastery ${Math.round((c.mastery ?? 0) * 3)} of 3`}>
                    {[1, 2, 3].map((n) => (
                      <i key={n} className={n <= Math.round((c.mastery ?? 0) * 3) ? 'on' : ''} />
                    ))}
                  </span>
                </span>
                <span className="stats">{conceptStats(c, conceptLesson)}</span>
              </button>
            </div>
          )
        })}
      </nav>

      <main className="lesson">
        <h1>{lesson.title}</h1>
        {lesson.blocks.map((b) =>
          b.kind === 'question' ? (
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
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
            />
          ) : b.kind === 'challenge' ? (
            <ChallengeCard
              key={b.id}
              block={b}
              disabled={lesson.running}
              speech={speech}
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
              onError={setError}
            />
          ) : b.kind === 'figure' ? (
            <FigureCard key={b.id} id={b.id} caption={b.markdown} data={b.data} />
          ) : b.kind === 'placement' ? (
            <section key={b.id} className="block">
              <div className="label">
                Placement result <span className="chip">{(b.data as { level: string }).level}</span>
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
              <div className="label">{BLOCK_LABELS[b.kind] ?? b.kind}</div>
              <Markdown>{b.markdown}</Markdown>
            </section>
          ),
        )}
        {showPlan && (
          <Plan
            ranking={course.ranking}
            mechanism={course.mechanism}
            accepted={course.concepts.length > 0 || course.lessons.some((l) => l.phase === 'placement')}
            disabled={lesson.running}
            onChoose={(mechanism) => post(`/api/courses/${course.id}/mechanism`, { mechanism })}
            onAccept={() => post(`/api/courses/${course.id}/plan/accept`, {})}
            onPlacement={() =>
              api<Lesson>(`/api/courses/${course.id}/placement`, {}).then(
                (created) => {
                  addLesson(created)
                  setLessonId(created.id)
                },
                (err: Error) => setError(err.message),
              )
            }
          />
        )}
        {lesson.phase === 'placement' && course.placement && course.lessons.find((l) => l.phase === 'placement')?.id === lesson.id && !lesson.blocks.some((b) => b.kind === 'placement') && (
          <section className="block">
            <div className="label">
              Placement result <span className="chip">{course.level}</span>
            </div>
            <Markdown>{course.placement}</Markdown>
          </section>
        )}
        {lesson.running && (empty || writing) && <Skeleton />}
        <div ref={lessonBottom} />
      </main>

      <aside className="chat" aria-label="Tutor chat">
        <div className="chat-head">
          <strong>Tutor</strong>
          <span className="status" role="status">
            {activity}
          </span>
        </div>
        <div className="messages">
          {lesson.messages.map((m) => (
            <Fragment key={m.id}>
              {(dividers.get(m.id) ?? []).map((b) => (
                <CardDivider key={b.id} block={b} />
              ))}
              {m.role === 'learner' ? (
                <div className="bubble learner">{m.text}</div>
              ) : (
                <div className="bubble">
                  <Markdown>{m.text}</Markdown>
                </div>
              )}
            </Fragment>
          ))}
          {(dividers.get(-1) ?? []).map((b) => (
            <CardDivider key={b.id} block={b} />
          ))}
          {streaming && (
            <div className="bubble">
              <Markdown>{streaming}</Markdown>
              <span className="caret" />
            </div>
          )}
          {error && <div className="error">{error}</div>}
          <div ref={chatBottom} />
        </div>
        <div className="composer">
          <label htmlFor="chat">Message the tutor</label>
          <textarea
            id="chat"
            className="field"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
          />
          <div className="row">
            {speech && <Mic onClip={(clip) => transcribe(clip).then((t) => setDraft((d) => (d ? `${d} ${t}` : t)))} onError={setError} />}
            {lesson.running && (
              <button className="btn" onClick={() => post(`/api/lessons/${lesson.id}/stop`, {})}>
                Stop
              </button>
            )}
            <button className="btn primary" onClick={send} disabled={lesson.running || !draft.trim()}>
              Send
            </button>
          </div>
        </div>
      </aside>
    </div>
  )
}

/** Push-to-talk: records while pressed, sends the clip to the recogniser, hands back the transcript. */
async function transcribe(clip: Blob, lang?: string): Promise<string> {
  const form = new FormData()
  form.append('audio', clip, 'clip.webm')
  const res = await fetch(`/api/stt${lang ? `?lang=${encodeURIComponent(lang)}` : ''}`, { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  return (await res.json()).text
}

function Mic(props: { onClip: (clip: Blob) => Promise<void>; onError: (message: string) => void; label?: string; disabled?: boolean; limit?: number }) {
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
      aria-label={recording ? 'Stop recording' : (props.label ?? 'Speak your message')}
      title={recording ? 'Stop recording' : (props.label ?? 'Speak your message')}
      onClick={recording ? stop : start}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
      {recording ? ' Stop' : props.label ? ` ${props.label}` : ''}
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
    <button type="button" className="btn theme" onClick={flip} title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'} aria-label="Toggle theme">
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
  const [agent, setAgent] = useState('')
  const [speech, setSpeech] = useState(false)
  const { profiles, current, select, reload } = useProfiles()
  useEffect(() => {
    api<{ agent: string; speech: boolean }>('/api/meta').then(
      (m) => {
        setAgent(m.agent)
        setSpeech(m.speech)
      },
      () => {},
    )
  }, [])
  const match = hash.match(/^#\/course\/(\d+)(?:\?concept=(\d+)|\?start=(episode|writing))?$/)
  const review = hash.match(/^#\/review(?:\?then=(.*))?$/)

  function page() {
    if (!profiles) return null
    if (!current)
      return (
        <FirstProfile
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
          concept={match[2] ? Number(match[2]) : null}
          start={(match[3] as 'episode' | 'writing' | undefined) ?? null}
        />
      )
    if (review) return <Review profile={current.id} then={review[1] ? decodeURIComponent(review[1]) : null} />
    if (hash === '#/errors') return <ErrorsPage profile={current.id} />
    if (hash === '#/profile')
      return <ProfilePage profiles={profiles} current={current} onSelect={select} onChanged={reload} />
    return <Home key={current.id} profile={current.id} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="wordmark" href="#/" title="wise-scholar">
          <Logo />
        </a>
        <span className="grow" />
        <span className="status">agent: {agent}</span>
        <ThemeToggle />
        {current && (
          <a className="btn as-link" href="#/profile">
            {current.name}
          </a>
        )}
      </header>
      {page()}
    </div>
  )
}
