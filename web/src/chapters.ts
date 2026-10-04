import type { TFunction } from 'i18next'
import type { Block, CourseDetail, Lesson, Message } from './course'

export type Item = { block: Block } | { message: Message }
export type Part = { title: string | null; lessons: Lesson[] }

/** A lesson's blocks and chat in the order they happened: within one second, the learner's message, then cards, then the tutor's reply. */
export function timeline(lesson: Lesson): Item[] {
  const rank = (i: Item) => ('block' in i ? 1 : i.message.role === 'learner' ? 0 : 2)
  const stamp = (i: Item) => ('block' in i ? i.block.created : i.message.created)
  const id = (i: Item) => ('block' in i ? i.block.id : i.message.id)
  const items: Item[] = [...lesson.blocks.map((block) => ({ block })), ...lesson.messages.map((message) => ({ message }))]
  return items.sort((a, b) => stamp(a).localeCompare(stamp(b)) || rank(a) - rank(b) || id(a) - id(b))
}

/** The book's parts: the opening lessons, one part per module with its started lessons, then episodes and writing sessions. */
export function parts(course: CourseDetail, t: TFunction): Part[] {
  const loose = course.lessons.filter((l) => l.concept_id === null)
  const opening = loose.filter((l) => l.phase === 'interview' || l.phase === 'placement')
  const extras = loose.filter((l) => !opening.includes(l))
  const modules = [...new Set(course.concepts.map((c) => c.module))].map((title) => ({
    title,
    lessons: course.concepts.filter((c) => c.module === title).flatMap((c) => course.lessons.filter((l) => l.concept_id === c.id)),
  }))
  return [{ title: null, lessons: opening }, ...modules, { title: t('book.extras'), lessons: extras }].filter((p) => p.lessons.length > 0)
}
