import assert from 'node:assert/strict'
import { test } from 'node:test'
import { lessonStream } from '../src/course.ts'
import type { Block, Message } from '../src/course.ts'

const block = (id: number, created: string): Block => ({ id, lesson_id: 1, kind: 'prose', markdown: '', data: null, created, position: id })
const message = (id: number, role: Message['role'], created: string): Message => ({ id, lesson_id: 1, role, text: '', created })
const ids = (items: ReturnType<typeof lessonStream>) => items.map((i) => ('block' in i ? `b${i.block.id}` : `m${i.message.id}`))

test('messages sit before the first block posted after them, and the rest close the stream', () => {
  const blocks = [block(1, '2026-10-18 10:00:05'), block(2, '2026-10-18 10:01:00')]
  const messages = [message(1, 'tutor', '2026-10-18 10:00:00'), message(2, 'learner', '2026-10-18 10:00:30'), message(3, 'tutor', '2026-10-18 10:02:00')]
  assert.deepEqual(ids(lessonStream(blocks, messages)), ['m1', 'b1', 'm2', 'b2', 'm3'])
})

test('in the same second a learner message comes before the block it triggered, a tutor message after it', () => {
  const blocks = [block(1, '2026-10-18 10:00:00')]
  assert.deepEqual(ids(lessonStream(blocks, [message(1, 'learner', '2026-10-18 10:00:00')])), ['m1', 'b1'])
  assert.deepEqual(ids(lessonStream(blocks, [message(1, 'tutor', '2026-10-18 10:00:00')])), ['b1', 'm1'])
})

test('blocks keep their own order even when the tutor moved one before an older one', () => {
  const blocks = [block(2, '2026-10-18 10:05:00'), block(1, '2026-10-18 10:00:00')]
  const messages = [message(1, 'tutor', '2026-10-18 10:02:00')]
  assert.deepEqual(ids(lessonStream(blocks, messages)), ['m1', 'b2', 'b1'])
})
