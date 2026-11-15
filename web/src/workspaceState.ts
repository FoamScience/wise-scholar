import { useEffect, useRef, useState } from 'react'
import type { Dispatch, KeyboardEvent, SetStateAction } from 'react'
import { api } from './api'
import i18n from './i18n'
import { loadGiven, saveGiven } from './offline'
import type { Given } from './offline'
import type { Block, CourseDetail, Lesson, Message } from './course'
import type { Source } from './Sources'
import { courseChange, lessonChange, sourcesChange, type TutorEvent } from './courseEvents'
import { clearTabMark, markTab } from './tabMark'


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
  'add_widget',
  'pose_writing',
  'pose_vocab_check',
  'pose_speaking',
  'pose_teachback',
  'make_podcast',
]

const seenKey = (lesson: number) => `seen-${lesson}`

function loadSeen(lesson: number): number | null {
  try {
    const seen = localStorage.getItem(seenKey(lesson))
    return seen === null ? null : Number(seen)
  } catch {
    return null
  }
}

function saveSeen(lesson: number, message: number) {
  try {
    localStorage.setItem(seenKey(lesson), String(message))
  } catch {
    // storage blocked: nothing counts as new
  }
}

type Opening = { courseId: number; concept: number | null; start: 'episode' | 'writing' | null; foundLesson: number | null }

function askWarmup(courseId: number) {
  const here = location.hash
  api<{ due: number }>(`/api/courses/${courseId}/warmup`).then(
    (w) => {
      // only from the page that asked: a second answer, or one arriving after the learner moved on, does nothing
      // replaced, not pushed: going back from the lesson must not land on the warm-up again
      if (w.due && location.hash === here) location.replace(`#/review?then=${encodeURIComponent(here)}`)
    },
    () => {},
  )
}

/** The lesson a search result or a unit on the map asked for, if the course has it. */
function wantedLesson(c: CourseDetail, foundLesson: number | null, concept: number | null) {
  if (foundLesson !== null) return c.lessons.find((l) => l.id === foundLesson)
  return concept === null ? undefined : c.lessons.find((l) => l.concept_id === concept)
}

/** Work the server does out of sight once the course opens. */
function courseUpkeep(c: CourseDetail) {
  // a map made before units had prerequisites gets them worked out once, out of sight
  if (c.concepts.length > 0 && !c.prerequisites) api(`/api/courses/${c.id}/prerequisites`, {}).catch(() => {})
  if (c.concepts.length > 0 && !c.cover) api(`/api/courses/${c.id}/cover`, {}).catch(() => {})
  // finished lessons whose claims were not taken out yet, older ones included, go to the extractor
  if (c.mode === 'learner') api(`/api/courses/${c.id}/claims`, {}).catch(() => {})
}

/** The course, its sources, the shown lesson and the last error, loaded once and kept current by the course's event stream. */
export function useCourseStream({ courseId, concept, start, foundLesson }: Opening) {
  const [error, setError] = useState('')
  const [course, setCourse] = useState<CourseDetail | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [lessonId, setLessonId] = useState<number | null>(null)
  const [streaming, setStreaming] = useState('')
  const [activity, setActivity] = useState('')
  const [writing, setWriting] = useState(false)

  function patchLesson(id: number, patch: (l: Lesson) => Lesson) {
    setCourse((c) => c && { ...c, lessons: c.lessons.map((l) => (l.id === id ? patch(l) : l)) })
  }

  function addLesson(lesson: Lesson) {
    setCourse((c) => c && (c.lessons.some((l) => l.id === lesson.id) ? c : { ...c, lessons: [...c.lessons, lesson] }))
  }

  function finishTurn(ev: Extract<TutorEvent, { type: 'turn.done' }>) {
    const { message } = ev
    patchLesson(ev.lesson_id, (l) => ({
      ...l,
      running: false,
      messages: message ? [...l.messages, message] : l.messages,
    }))
    setStreaming('')
    setActivity('')
    setWriting(false)
    if (ev.ok) markTab('✓')
    else if (ev.error !== 'stopped') {
      markTab('✕')
      setError(ev.error ?? i18n.t('chat.turnFailed'))
    }
  }

  useEffect(() => {
    const refreshTotals = () =>
      api<CourseDetail>(`/api/courses/${courseId}`).then(
        ({ concepts, strands, vocabulary, recap }) => setCourse((c) => c && { ...c, concepts, strands, vocabulary, recap }),
        () => {},
      )
    const source = new EventSource(`/api/courses/${courseId}/events`)
    source.onmessage = (raw) => {
      const ev: TutorEvent = JSON.parse(raw.data)
      const toLesson = lessonChange(ev)
      if (toLesson) patchLesson(...toLesson)
      const toCourse = courseChange(ev)
      if (toCourse) setCourse((c) => c && toCourse(c))
      const toSources = sourcesChange(ev)
      if (toSources) setSources(toSources)
      if (ev.type === 'block.added' || ev.type === 'plan.ranked') setWriting(false)
      if (ev.type === 'block.added' || ev.type === 'block.updated') refreshTotals()
      if (ev.type === 'turn.started') {
        patchLesson(ev.lesson_id, (l) => ({ ...l, running: true }))
        clearTabMark()
        setActivity('thinking')
        setError('')
      } else if (ev.type === 'chat.delta') {
        setActivity('')
        setStreaming((s) => s + ev.text)
      } else if (ev.type === 'activity') {
        setActivity(ev.tool)
        setWriting(LESSON_AREA_TOOLS.includes(ev.tool))
      } else if (ev.type === 'lesson.created') {
        addLesson(ev.lesson)
      } else if (ev.type === 'turn.done') {
        finishTurn(ev)
      }
    }
    // a sitting opens with a few due reviews before the lesson; a card looked up by search opens straight away
    if (!start && foundLesson === null && navigator.onLine) askWarmup(courseId)
    api<Source[]>(`/api/courses/${courseId}/sources`).then(setSources, () => {})

    function create(path: string, then?: () => void) {
      api<Lesson>(path, {}).then(
        (created) => {
          setCourse((cur) => cur && { ...cur, lessons: [...cur.lessons, created] })
          setLessonId(created.id)
          then?.()
        },
        (err: Error) => setError(err.message),
      )
    }

    api<CourseDetail>(`/api/courses/${courseId}`).then(
      (c) => {
        setCourse(c)
        const wanted = wantedLesson(c, foundLesson, concept)
        setLessonId(wanted ? wanted.id : c.lessons[c.lessons.length - 1].id)
        if (start) create(`/api/courses/${courseId}/${start}`, () => (location.hash = `#/course/${courseId}`))
        if (!wanted && concept !== null) create(`/api/concepts/${concept}/lesson`)
        if (c.lessons.some((l) => l.running)) setActivity('thinking')
        courseUpkeep(c)
      },
      (e) => setError(e.message),
    )
    return () => source.close()
  }, [courseId, concept, start, foundLesson])

  return { course, setCourse, sources, setSources, lessonId, setLessonId, streaming, activity, writing, error, setError, patchLesson, addLesson }
}

/** Answers given while offline, kept per lesson in this browser until the batch goes to the server. */
export function useOfflineAnswers(lessonId: number | null, patchLesson: (id: number, patch: (l: Lesson) => Lesson) => void, setError: (message: string) => void) {
  const [kept, setKept] = useState<{ lesson: number | null; answers: Record<number, Given> }>({ lesson: null, answers: {} })
  const [sending, setSending] = useState(false)
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

  return { given, give, sending, prepareOffline, sendBatch }
}

/** Tutor messages the chat has not shown yet; the open chat marks them all read. */
export function useUnread(lessonId: number | null, lesson: Lesson | null, open: boolean): number {
  const lastTutor = lesson?.messages.findLast((m) => m.role === 'tutor')?.id ?? 0

  // the open chat shows every message: the badge counts the tutor's from after the last one it showed; a lesson
  // first seen in this browser starts with all of them read
  useEffect(() => {
    if (lessonId && (open || loadSeen(lessonId) === null)) saveSeen(lessonId, lastTutor)
  }, [open, lessonId, lastTutor])
  if (!lesson || open) return 0
  const seenUpTo = loadSeen(lesson.id) ?? lastTutor
  return lesson.messages.filter((m) => m.role === 'tutor' && m.id > seenUpTo).length
}

type Following = { lesson: Lesson | null; ranked: number | undefined; writing: boolean; open: boolean; streaming: string; found: { lesson: number; at: string } | null }

/** Scrolls the lesson and the chat along with what arrives, for a learner already at the end; marks a card found by search. */
export function useFollow({ lesson, ranked, writing, open, streaming, found }: Following) {
  const lessonBottom = useRef<HTMLDivElement>(null)
  const messagesBox = useRef<HTMLDivElement>(null)

  // follow new cards and messages only for a learner already at the end; one reading back stays where they are
  function nearEnd(): boolean {
    const main = lessonBottom.current?.closest('main')
    return !main || main.scrollHeight - main.scrollTop - main.clientHeight < 240
  }

  useEffect(() => {
    if (nearEnd()) lessonBottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [lesson?.blocks.length, ranked, writing])

  // the conversation opens at, and follows, its latest message, as a chat does
  useEffect(() => {
    if (messagesBox.current) messagesBox.current.scrollTop = messagesBox.current.scrollHeight
  }, [lesson?.messages.length, open])

  // a card or message found by search: its lesson opens on it, the chat too for a message, and it is marked a moment
  const shown = useRef<string | null>(null)
  useEffect(() => {
    if (!found || shown.current === found.at || lesson?.id !== found.lesson) return
    const target = document.getElementById(found.at)
    if (!target) return
    shown.current = found.at
    target.scrollIntoView({ block: 'center' })
    target.classList.add('found')
  }, [found, lesson])

  // a streamed reply carries along only a learner already at the end; one reading back stays where they are
  useEffect(() => {
    const box = messagesBox.current
    if (box && streaming && box.scrollHeight - box.scrollTop - box.clientHeight < 120) box.scrollTop = box.scrollHeight
  }, [streaming])

  return { lessonBottom, messagesBox }
}

/** Whether this sitting has answers to sum up, asked once the unit is finished. */
export function useAnsweredToday(lessonDone: boolean, profile: number): boolean {
  const [answeredToday, setAnsweredToday] = useState(false)
  useEffect(() => {
    if (!lessonDone) return
    api<{ answers: number; current?: boolean }>(`/api/sitting?profile=${profile}`).then((s) => setAnsweredToday(Boolean(s.current && s.answers)), () => {})
  }, [lessonDone, profile])
  return answeredToday
}

/** Moving a replayed course to the newer version on offer; the lesson shown stays unless the upgrade removed it. */
export function useUpgrade(
  courseId: number,
  setCourse: (course: CourseDetail) => void,
  setLessonId: Dispatch<SetStateAction<number | null>>,
  setError: (message: string) => void,
) {
  const [upgrading, setUpgrading] = useState(false)

  async function upgrade(hash: string) {
    setUpgrading(true)
    try {
      const c = await api<CourseDetail>(`/api/courses/${courseId}/upgrade`, { hash })
      setCourse(c)
      setLessonId((id) => (c.lessons.some((l) => l.id === id) ? id : c.lessons[c.lessons.length - 1].id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUpgrading(false)
    }
  }

  return { upgrading, upgrade }
}

/** The message being written to the tutor; Enter sends it, Shift+Enter breaks the line. changing: it asks for a map change. */
export function useChatDraft(lesson: Lesson | null, patchLesson: (id: number, patch: (l: Lesson) => Lesson) => void, setError: (message: string) => void) {
  const [draft, setDraft] = useState('')
  const [changing, setChanging] = useState(false)

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

  return { draft, setDraft, changing, setChanging, send, onKey }
}

/** The server's side of coming back: a finished course opens its recap once the tutor is done, and a unit left
 * open for a moment asks whether it opens with a recap of where the learner was. */
export function useLessonVisits(course: CourseDetail | null, courseId: number, lessonId: number | null) {
  // a course just finished opens its recap once, when the tutor is done answering
  const busy = course?.lessons.some((l) => l.running) ?? true
  useEffect(() => {
    if (course?.recap?.finished && !course.recap.seen && !busy) location.hash = `#/course/${courseId}/recap`
  }, [course?.recap, busy, courseId])

  useEffect(() => {
    // back at an unfinished unit after days away: the server decides whether it opens with a recap. Asked once the
    // lesson stays open a moment, so one shown on the way to another (a new unit being created) gets none.
    if (lessonId === null || !navigator.onLine) return
    const asked = setTimeout(() => api(`/api/lessons/${lessonId}/resume`, {}).catch(() => {}), 1500)
    return () => clearTimeout(asked)
  }, [lessonId])
}
