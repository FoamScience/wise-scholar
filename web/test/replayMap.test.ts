import assert from 'node:assert/strict'
import { test } from 'node:test'
import i18n from '../src/i18n.ts'
import { unitDone } from '../src/course.ts'
import type { Block, Concept, Lesson } from '../src/course.ts'
import { conceptStats } from '../src/mapStats.ts'

const block = (id: number, kind: string): Block => ({ id, lesson_id: 1, kind, markdown: '', data: null, created: '', position: id })
const concept = (extra: Partial<Concept> = {}): Concept => ({ id: 1, module: 'M', title: 'U1', known: 0, mastery: null, kind: 'concept', due: 0, needs: [], placed_out: false, ...extra })
const lesson = (...kinds: string[]): Lesson => ({ id: 1, title: '', phase: 'lesson', concept_id: 1, messages: [], blocks: kinds.map((k, i) => block(i + 1, k)), running: false })

test('a known unit of a replay its reader never touched is done and placed out, though its imported lesson is there', async () => {
  await i18n.changeLanguage('en')
  const untouched = concept({ known: 1, placed_out: true })
  assert.equal(unitDone(untouched, lesson('prose', 'quiz')), true)
  assert.equal(conceptStats(untouched, lesson('prose', 'quiz'), i18n.t), 'placed out')
})

test('a known unit whose lesson was begun is done only once that lesson is finished', async () => {
  await i18n.changeLanguage('en')
  const begun = concept({ known: 1 })
  assert.equal(unitDone(begun, lesson('prose')), false)
  assert.equal(conceptStats(begun, lesson('prose'), i18n.t), 'started')
  assert.equal(unitDone(begun, lesson('prose', 'done')), true)
  assert.equal(unitDone(concept({ known: 1, placed_out: true }), undefined), true)
  assert.equal(unitDone(concept(), undefined), false)
})
