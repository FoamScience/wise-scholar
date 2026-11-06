import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import { typedPlaceholder } from '../src/typing.ts'

function run(titles: string[], calm: boolean, ms: number): { shown: string[]; stop: () => void } {
  mock.timers.enable({ apis: ['setTimeout'] })
  const shown: string[] = []
  const stop = typedPlaceholder(titles, calm, (text) => shown.push(text))
  for (let t = 0; t < ms; t += 5) mock.timers.tick(5)
  return { shown, stop }
}

test('types a title, holds it, erases it and goes on to the next', () => {
  const { shown, stop } = run(['ab', 'c'], false, 5400)
  stop()
  mock.timers.reset()
  assert.deepEqual(shown.slice(0, 6), ['a', 'ab', 'a', '', 'c', ''])
})

test('never splits a character made of two code units', () => {
  const { shown, stop } = run(['𝛑x'], false, 500)
  stop()
  mock.timers.reset()
  assert.equal(shown[0], '𝛑')
})

test('under reduced motion a whole title replaces the last and wraps around', () => {
  const { shown, stop } = run(['Tensor networks', 'Valves'], true, 9500)
  stop()
  mock.timers.reset()
  assert.deepEqual(shown.slice(0, 3), ['Tensor networks', 'Valves', 'Tensor networks'])
})

test('stopping ends the typing', () => {
  const { shown, stop } = run(['abc'], false, 500)
  stop()
  const at = shown.length
  mock.timers.tick(5000)
  mock.timers.reset()
  assert.equal(shown.length, at)
})
