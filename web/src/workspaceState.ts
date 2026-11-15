import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import i18n from './i18n'
import { loadGiven, saveGiven } from './offline'
import type { Given } from './offline'
import type { Block, CourseDetail, Lesson } from './course'
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
    const here = location.hash
    if (!start && foundLesson === null && navigator.onLine)
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
        const wanted = foundLesson !== null ? c.lessons.find((l) => l.id === foundLesson) : concept === null ? undefined : c.lessons.find((l) => l.concept_id === concept)
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
        // a map made before units had prerequisites gets them worked out once, out of sight
        if (c.concepts.length > 0 && !c.prerequisites) api(`/api/courses/${courseId}/prerequisites`, {}).catch(() => {})
        if (c.concepts.length > 0 && !c.cover) api(`/api/courses/${courseId}/cover`, {}).catch(() => {})
        // finished lessons whose claims were not taken out yet, older ones included, go to the extractor
        if (c.mode === 'learner') api(`/api/courses/${courseId}/claims`, {}).catch(() => {})
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
