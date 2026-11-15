import assert from 'node:assert/strict'
import { test } from 'node:test'
import { courseRoute, profileRoute } from '../src/route.ts'

test('a course hash names its workspace, opened at a unit, a start or a search hit', () => {
  assert.deepEqual(courseRoute('#/course/7'), { page: 'workspace', courseId: 7, concept: null, start: null, found: null })
  assert.deepEqual(courseRoute('#/course/7?concept=3'), { page: 'workspace', courseId: 7, concept: 3, start: null, found: null })
  assert.deepEqual(courseRoute('#/course/7?start=writing'), { page: 'workspace', courseId: 7, concept: null, start: 'writing', found: null })
  assert.deepEqual(courseRoute('#/course/7?lesson=4&chat=12'), { page: 'workspace', courseId: 7, concept: null, start: null, found: { lesson: 4, at: 'msg-12' } })
  assert.deepEqual(courseRoute('#/course/7?lesson=4&card=9'), { page: 'workspace', courseId: 7, concept: null, start: null, found: { lesson: 4, at: 'block-9' } })
  assert.equal(courseRoute('#/course/7?start=other'), null)
})

test('a course hash names its search, recap, book, publishing and handouts', () => {
  assert.deepEqual(courseRoute('#/course/7/search?q=blade%20angle&kind=card'), { page: 'search', courseId: 7, query: 'blade angle', kind: 'card' })
  assert.deepEqual(courseRoute('#/course/7/search?q=x'), { page: 'search', courseId: 7, query: 'x', kind: '' })
  assert.deepEqual(courseRoute('#/course/7/recap'), { page: 'recap', courseId: 7, preview: false })
  assert.deepEqual(courseRoute('#/course/7/recap?preview'), { page: 'recap', courseId: 7, preview: true })
  assert.deepEqual(courseRoute('#/course/7/book'), { page: 'book', courseId: 7 })
  assert.deepEqual(courseRoute('#/course/7/publish'), { page: 'publish', courseId: 7 })
  assert.deepEqual(courseRoute('#/lesson/5/handout/teacher'), { page: 'handout', lessonId: 5, version: 'teacher' })
  assert.equal(courseRoute('#/lesson/5/handout/parent'), null)
  assert.equal(courseRoute('#/review'), null)
})

test('a profile hash names its review, graph and pages; anything else is home', () => {
  assert.deepEqual(profileRoute('#/review'), { page: 'review', then: null })
  assert.deepEqual(profileRoute('#/review?then=%23%2Fcourse%2F7'), { page: 'review', then: '#/course/7' })
  assert.deepEqual(profileRoute('#/graph'), { page: 'graph', course: null })
  assert.deepEqual(profileRoute('#/graph?course=7'), { page: 'graph', course: 7 })
  for (const page of ['explore', 'errors', 'sitting', 'commands', 'usage', 'settings']) assert.deepEqual(profileRoute(`#/${page}`), { page })
  assert.equal(profileRoute('#/'), null)
  assert.equal(profileRoute('#/errors/old'), null)
  assert.equal(profileRoute('#/course/7'), null)
})
