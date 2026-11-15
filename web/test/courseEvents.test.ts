import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Block, Capstone, CourseDetail, Lesson } from '../src/course.ts'
import { courseChange, lessonChange, sourcesChange } from '../src/courseEvents.ts'
import type { Source } from '../src/Sources.tsx'

const block = (id: number, markdown = ''): Block => ({ id, lesson_id: 1, kind: 'prose', markdown, data: null, created: '', position: id })
const lesson = { id: 1, blocks: [block(1), block(2)] } as Lesson
const capstone = (id: number, title: string) => ({ id, title }) as Capstone
const source = (id: number, name: string) => ({ id, name }) as Source

test('block events change the cards of the lesson they name', () => {
  const [added, add] = lessonChange({ type: 'block.added', lesson_id: 1, block: block(3) })!
  assert.equal(added, 1)
  assert.deepEqual(add(lesson).blocks.map((b) => b.id), [1, 2, 3])
  const [, update] = lessonChange({ type: 'block.updated', lesson_id: 1, block: block(2, 'new') })!
  assert.deepEqual(update(lesson).blocks.map((b) => b.markdown), ['', 'new'])
  const [, remove] = lessonChange({ type: 'block.removed', lesson_id: 1, id: 1 })!
  assert.deepEqual(remove(lesson).blocks.map((b) => b.id), [2])
  const [, order] = lessonChange({ type: 'lesson.ordered', lesson_id: 1, blocks: [block(2), block(1)] })!
  assert.deepEqual(order(lesson).blocks.map((b) => b.id), [2, 1])
  assert.equal(lessonChange({ type: 'plan.chosen', mechanism: 'x' }), null)
})

test('a capstone replaces the one with its id, or joins the course', () => {
  const course = { capstones: [capstone(1, 'old')] } as CourseDetail
  const set = (k: Capstone) => courseChange({ type: 'capstone.set', capstone: k })!(course).capstones.map((x) => x.title)
  assert.deepEqual(set(capstone(1, 'new')), ['new'])
  assert.deepEqual(set(capstone(2, 'more')), ['old', 'more'])
  const map = courseChange({ type: 'map.set', concepts: [] })!(course)
  assert.deepEqual(map.capstones, course.capstones)
  assert.equal(courseChange({ type: 'block.removed', lesson_id: 1, id: 1 }), null)
})

test('a source replaces the one with its id, joins the list, or goes', () => {
  const all = [source(1, 'a')]
  assert.deepEqual(sourcesChange({ type: 'source.updated', source: source(1, 'b') })!(all).map((s) => s.name), ['b'])
  assert.deepEqual(sourcesChange({ type: 'source.updated', source: source(2, 'c') })!(all).map((s) => s.name), ['a', 'c'])
  assert.deepEqual(sourcesChange({ type: 'source.removed', id: 1 })!(all), [])
  assert.equal(sourcesChange({ type: 'turn.started', lesson_id: 1 }), null)
})
