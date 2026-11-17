import assert from 'node:assert/strict'
import { test } from 'node:test'
import { onBoard } from '../src/board.ts'

test('a board shows its unstepped parts from the start, each stepped part once drawn, and no erased part', () => {
  const steps = [
    { say: 'A first guess.', draw: ['guess'], erase: [] },
    { say: 'The real cause.', draw: ['cause'], erase: ['guess', 'frame'] },
    { say: 'Its effect.', draw: ['effect'], erase: [] },
  ]
  const at = (n: number) => Object.fromEntries(onBoard(steps, n))
  assert.deepEqual(at(0), { guess: false, cause: false, frame: true, effect: false })
  assert.deepEqual(at(1), { guess: true, cause: false, frame: true, effect: false })
  assert.deepEqual(at(2), { guess: false, cause: true, frame: false, effect: false })
  assert.deepEqual(at(3), { guess: false, cause: true, frame: false, effect: true })
})
