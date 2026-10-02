import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import Markdown from './Md'
import { api } from './api'
import { QuizCard, Review, ReviewPanels } from './Quiz'
import type { QuizData } from './Quiz'
import { LevelPanel, ReadingCard } from './Language'
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
type Message = { id: number; lesson_id: number; role: 'learner' | 'tutor'; text: string }
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
}
type Block = { id: number; lesson_id: number; kind: string; markdown: string; data: unknown }
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
type CourseDetail = Course & {
  placement: string | null
  ranking: Ranked[]
  concepts: Concept[]
  lessons: Lesson[]
  strands: { input: number; output: number; language: number; fluency: number } | null
  vocabulary: { total: number; due: number }
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
  pose_writing: 'preparing a writing task…',
  bash: 'testing in the workspace…',
  read: 'reading your files…',
  write: 'writing exercise files…',
  edit: 'writing exercise files…',
  give_hint: 'writing a hint…',
  reveal: 'opening the solution…',
  mark_solved: 'checking your answer…',
  set_placement: 'working out your level…',
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
  'pose_writing',
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
      <section className="block answered">
        <div className="muted">{props.block.markdown}</div>
        <span className="chip">{answer}</span>
      </section>
    )

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) props.onAnswer(text.trim())
  }

  return (
    <section className="block question">
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

function ChallengeCard(props: { block: Block; disabled: boolean; onAct: Act }) {
  const [text, setText] = useState('')
  const d = props.block.data as ChallengeData
  const open = !d.solved && d.solution === null

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    props.onAct('attempt', { answer: text.trim() })
    setText('')
  }

  return (
    <section className="block challenge">
      <div className="label">
        {d.writing ? (d.fluency ? 'Write fast' : 'Write') : 'Work it out'}
        {d.solved && <span className="chip">{d.writing ? 'Done' : 'Solved'}</span>}
      </div>
      <Markdown>{props.block.markdown}</Markdown>

      <Ladder data={d} />

      {open && (
        <>
          <form onSubmit={submit}>
            <label htmlFor={`attempt-${props.block.id}`}>Your answer</label>
            <textarea
              id={`attempt-${props.block.id}`}
              className="field"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="row">
              <HintButton data={d} disabled={props.disabled} onAct={props.onAct} />
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
          <Markdown>{d.solution}</Markdown>
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
    <section className="block challenge">
      <div className="label">
        Exercise
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
          <pre>{f.content ?? 'This file is missing from the workspace.'}</pre>
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

function conceptStats(concept: Concept, lesson: Lesson | undefined): string {
  if (!lesson) return concept.known ? 'placed out' : 'not started'
  const cs = lesson.blocks
    .filter((b) => b.kind === 'challenge' || b.kind === 'exercise')
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

function Workspace({ courseId }: { courseId: number }) {
  const [course, setCourse] = useState<CourseDetail | null>(null)
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
    api<CourseDetail>(`/api/courses/${courseId}`).then(
      (c) => {
        setCourse(c)
        setLessonId(c.lessons[c.lessons.length - 1].id)
        if (c.lessons.some((l) => l.running)) setActivity('thinking…')
      },
      (e) => setError(e.message),
    )
    return () => source.close()
  }, [courseId])

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
  const empty = lesson.blocks.length === 0 && !showPlan

  return (
    <div className="workspace">
      <nav className="map" aria-label="Course map">
        <div className="label">Course map</div>
        {course.level && (
          <div>
            Level <span className="chip">{course.level}</span>
          </div>
        )}
        {course.strands && course.concepts.length > 0 && (
          <LevelPanel
            level={course.level}
            strands={course.strands}
            vocabulary={course.vocabulary}
            units={course.concepts}
          />
        )}
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
              {c.module !== course.concepts[i - 1]?.module && <strong>{c.module}</strong>}
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
              onAdd={(word) => post(`/api/blocks/${b.id}/vocabulary`, { word })}
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
              onAct={(action, body = {}) => post(`/api/blocks/${b.id}/${action}`, body)}
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
        {lesson.phase === 'placement' && course.placement && (
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
          {lesson.messages.map((m) =>
            m.role === 'learner' ? (
              <div key={m.id} className="bubble learner">
                {m.text}
              </div>
            ) : (
              <div key={m.id} className="bubble">
                <Markdown>{m.text}</Markdown>
              </div>
            ),
          )}
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

export default function App() {
  const hash = useHash()
  const [agent, setAgent] = useState('')
  const { profiles, current, select, reload } = useProfiles()
  useEffect(() => {
    api<{ agent: string }>('/api/meta').then((m) => setAgent(m.agent), () => {})
  }, [])
  const match = hash.match(/^#\/course\/(\d+)$/)

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
    if (match) return <Workspace key={match[1]} courseId={Number(match[1])} />
    if (hash === '#/review') return <Review profile={current.id} />
    if (hash === '#/profile')
      return <ProfilePage profiles={profiles} current={current} onSelect={select} onChanged={reload} />
    return <Home key={current.id} profile={current.id} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="wordmark" href="#/">
          wise-scholar
        </a>
        <span className="grow" />
        <span className="status">agent: {agent}</span>
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
