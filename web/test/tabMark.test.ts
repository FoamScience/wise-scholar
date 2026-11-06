import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import { clearTabMark, markTab } from '../src/tabMark.ts'

const page = Object.assign(new EventTarget(), { hidden: false, title: 'wise-scholar' })
Object.defineProperty(globalThis, 'document', { value: page })

function show() {
  page.hidden = false
  page.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  show()
  page.title = 'wise-scholar'
})

test('a tab in view is not marked', () => {
  markTab('✓')
  assert.equal(page.title, 'wise-scholar')
})

test('a hidden tab is marked until the learner comes back', () => {
  page.hidden = true
  markTab('✓')
  assert.equal(page.title, '✓ wise-scholar')
  show()
  assert.equal(page.title, 'wise-scholar')
})

test('a new turn takes the mark away while the tab stays hidden', () => {
  page.hidden = true
  markTab('✓')
  clearTabMark()
  assert.equal(page.title, 'wise-scholar')
})

test('a later turn replaces the mark instead of adding one', () => {
  page.hidden = true
  markTab('✕')
  markTab('✓')
  assert.equal(page.title, '✓ wise-scholar')
})
