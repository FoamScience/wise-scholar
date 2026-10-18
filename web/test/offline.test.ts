import assert from 'node:assert/strict'
import { test } from 'node:test'
import { gradeOffline } from '../src/offline.ts'
import type { QuizData } from '../src/Quiz.tsx'

const card = (more: Partial<QuizData>): QuizData => ({ card_id: 1, kind: 'choice', options: [], answer: null, answer_key: 'Na', explanation: 'Metals lose electrons.', ...more })

test('a choice is graded on the device against the key the card carries', () => {
  assert.deepEqual(gradeOffline(card({ options: ['Na', 'Cl'] }), { answer: 'Na', confidence: 0.9 }), {
    correct: true, confident_miss: false, answer_key: 'Na', explanation: 'Metals lose electrons.', misplaced: undefined,
  })
  const miss = gradeOffline(card({ options: ['Na', 'Cl'] }), { answer: 'Cl', confidence: 0.75 })!
  assert.equal(miss.correct, false)
  assert.equal(miss.confident_miss, true)
  assert.equal(gradeOffline(card({}), { answer: 'Cl', confidence: 0.7 })!.confident_miss, false)
})

test('a sort lists its misplaced items in card order, and a broken answer misplaces all', () => {
  const sort = card({ kind: 'sort', options: [{ text: 'NaCl', category: 'ionic' }, { text: 'CO2', category: 'covalent' }], answer_key: '["ionic","covalent"]' })
  assert.deepEqual(gradeOffline(sort, { answer: '{"NaCl":"ionic","CO2":"ionic"}', confidence: 0.5 })!.misplaced, ['CO2'])
  assert.equal(gradeOffline(sort, { answer: '{"NaCl":"ionic","CO2":"covalent"}', confidence: 0.5 })!.correct, true)
  assert.deepEqual(gradeOffline(sort, { answer: 'not json', confidence: 0.5 })!.misplaced, ['NaCl', 'CO2'])
})

test('an open answer waits for the learner to grade it against the model answer', () => {
  const open = card({ kind: 'open', answer_key: 'Its ions move.' })
  assert.equal(gradeOffline(open, { answer: 'ions', confidence: 0.9 }), null)
  assert.equal(gradeOffline(open, { answer: 'ions', confidence: 0.9, self_correct: false })!.confident_miss, true)
  assert.equal(gradeOffline(open, { answer: 'ions', confidence: 0.9, self_correct: true })!.correct, true)
})
