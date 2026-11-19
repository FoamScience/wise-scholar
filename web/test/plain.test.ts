import assert from 'node:assert/strict'
import { test } from 'node:test'
import { plain, plainParts } from '../src/plain.ts'

test('Markdown and LaTeX marks drop out of a mention and its symbols read as text', () => {
  assert.equal(plain('**Decide:** can the pump meet $\\text{NPSH}_{3\\%} \\ge 1.3$?'), 'Decide: can the pump meet NPSH_3% ≥ 1.3?')
  assert.equal(plain('$$S \\approx 180$ and snake_case and _stressed_'), 'S ≈ 180 and snake_case and stressed')
  assert.equal(plain('cut inside $\\text{NPSH'), 'cut inside NPSH')
})

test('a snippet keeps its matched words when a mark opens in one piece and closes in another', () => {
  assert.deepEqual(plainParts([['…eye with $S \\approx 18', false], ['0', true], ['$.\n\n**Dec', false], ['ide', true], [':** go', false]]), [
    ['…eye with S ≈ 18', false],
    ['0', true],
    ['. Dec', false],
    ['ide', true],
    [': go', false],
  ])
  assert.deepEqual(plainParts([['$\\text{', false], ['NPSH', true], ['}_{3\\%}$ is a head', false]]), [
    ['NPSH', true],
    ['_3% is a head', false],
  ])
})
