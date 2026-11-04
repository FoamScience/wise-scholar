import assert from 'node:assert/strict'
import { test } from 'node:test'
import { offered, sameText, toDisk } from '../src/editorSync.ts'

const hints = [
  { label: 'math.sqrt', signature: 'sqrt(x)', doc: 'Square root.' },
  { label: '.append', signature: 'append(x)', doc: '' },
  { label: 'print', signature: '', doc: '' },
]

test('a bare word is completed with the whole name', () => {
  const match = offered('y = pr', hints, false)!
  assert.equal(match.from, 4)
  assert.deepEqual(match.options.map((o) => o.insert), ['math.sqrt', 'append', 'print'])
})

test('after a dot only the last part goes in, right after the dot', () => {
  const match = offered('x = math.sq', hints, false)!
  assert.equal(match.from, 9)
  assert.deepEqual(match.options.map((o) => o.insert), ['sqrt', 'append', 'print'])
  assert.equal(offered('items.', hints, false)!.from, 6)
})

test('nothing typed offers nothing until asked', () => {
  assert.equal(offered('x = ', hints, false), null)
  assert.equal(offered('x = ', hints, true)!.from, 4)
  assert.equal(offered('pr', [], true), null)
})

test('a file with CRLF line endings keeps them and does not read as changed', () => {
  assert.ok(sameText('a\nb', 'a\r\nb'))
  assert.equal(toDisk('a\nb', 'x\r\ny'), 'a\r\nb')
  assert.equal(toDisk('a\nb', 'x\ny'), 'a\nb')
})
