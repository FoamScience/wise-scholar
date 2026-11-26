import assert from 'node:assert/strict'
import { test } from 'node:test'
import { solutionOf, type ExerciseData } from '../src/course.ts'
import { LEGEND, SOLUTION_LEGEND, pressComparison } from '../src/editorSync.ts'
import en from '../src/locales/en.json' with { type: 'json' }

const exercise = (data: object) => ({ files: ['a.py', 'b.py'], run: '', last_run: null, solution: null, ...data }) as unknown as ExerciseData

test("a file is compared with the solution's version of it once the solution is shown, also an empty one", () => {
  const d = exercise({ solution: 'Return it.', solution_files: { 'a.py': 'a = 2\n', 'b.py': '' } })
  assert.equal(solutionOf(d, 'a.py'), 'a = 2\n')
  assert.equal(solutionOf(d, 'b.py'), '')
})

test('no solution to compare with before it is shown, without solution files, or for a file it lacks', () => {
  assert.equal(solutionOf(exercise({ solution_files: { 'a.py': 'a = 2\n' } }), 'a.py'), null)
  assert.equal(solutionOf(exercise({ solution: 'Return it.' }), 'a.py'), null)
  assert.equal(solutionOf(exercise({ solution: 'Return it.', solution_files: { 'a.py': 'a = 2\n' } }), 'b.py'), null)
  assert.equal(solutionOf(exercise({ solution: 'Return it.', solution_files: {} }), 'constructor'), null)
})

test("the solution's legend names the solution, and only the marks it shows", () => {
  const words = (key: string) => (en.translation.exercise as Record<string, string>)[key.split('.')[1]]
  assert.deepEqual(Object.keys(SOLUTION_LEGEND), Object.keys(LEGEND))
  for (const key of Object.values(SOLUTION_LEGEND)) assert.match(words(key), /solution/)
  assert.doesNotMatch(words(SOLUTION_LEGEND.added), /struck/i)
  assert.doesNotMatch(words(SOLUTION_LEGEND.removed), /edge/i)
  assert.match(words(SOLUTION_LEGEND.both), /Struck.*edge/)
})

const texts = { starter: 'a = 1\n', solution: 'a = 2\n' }
const shown = (base: 'starter' | 'solution', from: string) => ({ base, summary: { of: null, from, is: 'both' as const } })

test('switching to a comparison of the same text keeps its summary, as the diff and its legend stay', () => {
  const equal = { starter: 'a = 1\n', solution: 'a = 1\n' }
  assert.deepEqual(pressComparison(shown('starter', 'a = 1\n'), 'solution', equal, null), { base: 'solution', summary: shown('starter', 'a = 1\n').summary })
})

test('switching to another text, turning on, turning off or another view starts the summary over', () => {
  assert.deepEqual(pressComparison(shown('starter', 'a = 1\n'), 'solution', texts, null), { base: 'solution', summary: null })
  assert.deepEqual(pressComparison({ base: null, summary: shown('starter', 'a = 1\n').summary }, 'starter', texts, null), { base: 'starter', summary: null })
  assert.deepEqual(pressComparison(shown('solution', 'a = 2\n'), 'solution', texts, null), { base: null, summary: null })
  assert.deepEqual(pressComparison(shown('starter', 'a = 1\n'), 'solution', { ...texts, solution: 'a = 1\n' }, 'the read-only text'), { base: 'solution', summary: null })
})
