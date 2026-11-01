import assert from 'node:assert/strict'
import { test } from 'node:test'
import { replayShown } from '../src/course.ts'
import type { Block } from '../src/course.ts'

const block = (id: number, kind: string, data: unknown = null): Block => ({ id, lesson_id: 1, kind, markdown: '', data, created: '', position: id })

test('a replayed unit shows up to its first open check, and opens on as each check is done', () => {
  const unit = [
    block(1, 'prose'),
    block(2, 'challenge', { attempts: [], pretest: true }),
    block(3, 'prose'),
    block(4, 'quiz', { answer: null }),
    block(5, 'exercise', { attempts: ['x'], solved: false, gave_up: false }),
    block(6, 'prose'),
  ]
  assert.equal(replayShown(unit), 2)
  unit[1] = block(2, 'challenge', { attempts: ['a guess'], pretest: true })
  assert.equal(replayShown(unit), 4)
  unit[3] = block(4, 'quiz', { answer: 'open answer', correct: undefined })
  assert.equal(replayShown(unit), 4)
  unit[3] = block(4, 'quiz', { answer: 'x', correct: false })
  assert.equal(replayShown(unit), 5)
  unit[4] = block(5, 'exercise', { attempts: ['x'], gave_up: true })
  assert.equal(replayShown(unit), 6)
})
