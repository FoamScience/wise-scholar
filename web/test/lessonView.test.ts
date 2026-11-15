import assert from 'node:assert/strict'
import { test } from 'node:test'
import i18n from '../src/i18n.ts'
import { lessonView } from '../src/course.ts'
import type { Block, Concept, CourseDetail, Lesson } from '../src/course.ts'
import { conceptStats } from '../src/mapStats.ts'

const block = (id: number, kind: string, data: unknown = null): Block => ({ id, lesson_id: 1, kind, markdown: '', data, created: '', position: id })
const concept = (id: number, extra: Partial<Concept> = {}): Concept => ({ id, module: 'M', title: `U${id}`, known: 0, mastery: null, kind: 'concept', due: 0, needs: [], ...extra })
const lesson = (extra: Partial<Lesson> = {}): Lesson => ({ id: 1, title: '', phase: 'lesson', concept_id: 1, messages: [], blocks: [], running: false, ...extra })
const course = (extra: Partial<CourseDetail> = {}) =>
  ({ ranking: [], concepts: [concept(1), concept(2, { known: 1 }), concept(3, { mastery: 1 }), concept(4)], mode: 'learner', ...extra }) as CourseDetail

test('an interview shows the plan once the tutor ranked approaches, and is empty until then', () => {
  const interview = lesson({ phase: 'interview', concept_id: null })
  assert.equal(lessonView(course(), interview).showPlan, false)
  assert.equal(lessonView(course(), interview).empty, true)
  const ranked = course({ ranking: [{ mechanism: 'm', rationale: '', title: '', summary: '', evidence: [] }] })
  assert.equal(lessonView(ranked, interview).showPlan, true)
  assert.equal(lessonView(ranked, interview).empty, false)
})

test('a finished unit points to the next one not known or mastered, and can no longer be taken offline', () => {
  const open = lesson({ blocks: [block(1, 'prose')] })
  assert.equal(lessonView(course(), open).finished, false)
  assert.equal(lessonView(course(), open).nextUnit, undefined)
  assert.equal(lessonView(course(), open).canPrepare, true)
  const done = lesson({ blocks: [block(1, 'prose'), block(2, 'done')] })
  assert.equal(lessonView(course(), done).finished, true)
  assert.equal(lessonView(course(), done).nextUnit?.id, 4)
  assert.equal(lessonView(course(), done).canPrepare, false)
  assert.equal(lessonView(course({ mode: 'teacher' }), open).canPrepare, false)
  assert.equal(lessonView(course(), lesson({ batch: 1 })).canPrepare, false)
})

test('the card count keeps room for the summary still to come, and settles once the unit is done', () => {
  const outline = block(1, 'outline', { steps: ['a'], at: 0, added: null, cards: 4 })
  assert.equal(lessonView(course(), lesson({ blocks: [outline, block(2, 'prose')] })).cardTotal, 4)
  const past = [outline, ...[2, 3, 4, 5].map((id) => block(id, 'prose'))]
  assert.equal(lessonView(course(), lesson({ blocks: past })).cardTotal, 5)
  assert.equal(lessonView(course(), lesson({ blocks: [...past, block(6, 'done')] })).cardTotal, 5)
  assert.equal(lessonView(course(), lesson({ blocks: [block(2, 'prose')] })).cardTotal, undefined)
})

test("a unit's line on the map says where it stands, its challenges and its reviews due", async () => {
  await i18n.changeLanguage('en')
  const t = i18n.t
  assert.equal(conceptStats(concept(1, { due: 2 }), undefined, t), 'not started, 2 reviews due')
  assert.equal(conceptStats(concept(1, { known: 1 }), undefined, t), 'placed out')
  assert.equal(conceptStats(concept(1), undefined, t, true), 'no plan yet')
  assert.equal(conceptStats(concept(1), lesson({ blocks: [block(1, 'done')] }), t, true), 'planned')
  const outline = block(1, 'outline', { steps: ['a', 'b', 'c'], at: 1, added: null })
  assert.equal(conceptStats(concept(1), lesson({ blocks: [outline] }), t), 'Step 2 of 3')
  assert.equal(conceptStats(concept(1), lesson({ blocks: [] }), t), 'started')
  const challenges = [
    block(2, 'challenge', { solved: true, hints: ['h'], gave_up: false }),
    block(3, 'exercise', { solved: false, hints: ['h', 'i'], gave_up: true }),
  ]
  assert.equal(conceptStats(concept(1, { due: 1 }), lesson({ blocks: [outline, ...challenges] }), t), 'Step 2 of 3, 1/2 solved, 3 hints, gave up 1×, 1 review due')
  assert.equal(conceptStats(concept(1, { kind: 'practice' }), lesson({ blocks: [block(1, 'done')] }), t), 'Done')
})
