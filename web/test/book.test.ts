import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { TFunction } from 'i18next'
import { parts, timeline } from '../src/chapters.ts'
import type { Block, CourseDetail, Lesson, Message } from '../src/course.ts'

const block = (id: number, created: string): Block => ({ id, lesson_id: 1, kind: 'prose', markdown: '', data: null, created })
const message = (id: number, role: Message['role'], created: string): Message => ({ id, lesson_id: 1, role, text: '', created })
const lesson = (id: number, phase: string, concept_id: number | null): Lesson => ({
  id,
  title: `lesson ${id}`,
  phase,
  concept_id,
  messages: [],
  blocks: [],
  running: false,
})

test('a chapter runs in the order things happened; within a second the learner speaks, cards follow, the tutor closes', () => {
  const chapter = {
    ...lesson(1, 'lesson', 7),
    blocks: [block(2, '2026-10-04 10:00:05'), block(1, '2026-10-04 10:00:01')],
    messages: [message(9, 'tutor', '2026-10-04 10:00:05'), message(8, 'learner', '2026-10-04 10:00:05'), message(7, 'tutor', '2026-10-04 10:00:02')],
  }
  const order = timeline(chapter).map((i) => ('block' in i ? `b${i.block.id}` : `${i.message.role[0]}${i.message.id}`))
  assert.deepEqual(order, ['b1', 't7', 'l8', 'b2', 't9'])
})

test('the book opens with interview and placement, follows the course map, and ends with episodes and writing', () => {
  const course = {
    concepts: [
      { id: 1, module: 'Basics', title: 'a', known: 0, mastery: null },
      { id: 2, module: 'Basics', title: 'b', known: 0, mastery: null },
      { id: 3, module: 'Later', title: 'c', known: 0, mastery: null },
    ],
    lessons: [lesson(10, 'interview', null), lesson(11, 'lesson', 2), lesson(12, 'story', null), lesson(13, 'placement', null), lesson(14, 'lesson', 1)],
  } as unknown as CourseDetail
  const t = ((key: string) => key) as unknown as TFunction
  assert.deepEqual(
    parts(course, t).map((p) => [p.title, p.lessons.map((l) => l.id)]),
    [
      [null, [10, 13]],
      ['Basics', [14, 11]],
      ['book.extras', [12]],
    ],
  )
})
