import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { PlotSpec } from '../src/PlotCard.tsx'
import { crosses, place, span, spot } from '../src/plotPoints.ts'

const head: PlotSpec = {
  x: { domain: [2.5, 16] },
  y: { domain: [0.9, 1.01] },
  marks: [
    { type: 'rule', x: 14 },
    { type: 'rule', x: 3.2 },
    { type: 'rule', y: 0.97 },
  ],
}

test('an axis spans its stated domain, else what its marks reach', () => {
  assert.deepEqual(span(head, 'x'), [2.5, 16])
  const drawn: PlotSpec = { marks: [{ type: 'line', data: [{ s: 0.2 }, { s: -1 }], x: 's', y: 'cp' }, { type: 'rule', x: 3 }] }
  assert.deepEqual(span(drawn, 'x'), [-1, 3])
  assert.equal(span(drawn, 'y'), null)
})

test('a note on a vertical rule is written beside it, toward the side it fits', () => {
  assert.deepEqual(place(head, 3.3, 0.905, 0.2), { textAnchor: 'start', dx: 6 })
  assert.deepEqual(place(head, 14, 0.92, 0.3), { textAnchor: 'end', dx: -6 })
})

test('a note is drawn inward only where it would run past the frame', () => {
  assert.deepEqual(place(head, 8.6, 0.95, 0.4), { textAnchor: 'middle', dx: 0 })
  assert.deepEqual(place(head, 15, 1.005, 0.1), { textAnchor: 'middle', dx: 0 })
  assert.deepEqual(place(head, 15, 1.005, 0.3), { textAnchor: 'end', dx: 0 })
  assert.deepEqual(place(head, 2.6, 1.005, 0.3), { textAnchor: 'start', dx: 0 })
  assert.deepEqual(place(head, 'a band', 0.95), { textAnchor: 'middle', dx: 0 })
})

test('a note on a horizontal rule sits above it', () => {
  assert.deepEqual(place(head, 8, 0.97, 0.1), { textAnchor: 'middle', dx: 0, lineAnchor: 'bottom', dy: -3 })
})

test('a curve crosses a box when any of its segments passes through it, sampled or not', () => {
  const rows = [{ x: 0.8, y: 0.05, series: 'p' }, { x: 1, y: -0.1, series: 'p' }, { x: 0, y: 5, series: 'q' }]
  assert.ok(crosses(rows, [0.75, 1], [0, 0.05]))
  assert.ok(!crosses(rows, [0.91, 1], [0, 0.05]))
  assert.ok(!crosses(rows, [0.75, 1], [1, 2]))
})

test("a horizontal rule's label leaves the end where a curve runs through it", () => {
  const cp = (side: string, points: [number, number][]) => ({ type: 'line' as const, x: 's', y: 'cp', stroke: 'side', data: points.map(([s, v]) => ({ s, cp: v, side })) })
  const spec: PlotSpec = {
    x: { domain: [0, 1] },
    y: { domain: [-1.4, 1.1] },
    marks: [cp('pressure', [[0, 1], [0.05, 0.3], [0.8, 0.05], [1, -0.1]]), cp('suction', [[0, 1], [0.05, -0.95], [1, -0.1]]), { type: 'rule', y: 0 }],
  }
  assert.deepEqual(spot(spec, 0, 0.08, 0.05), { left: false, below: false })
  const line = (points: [number, number][]): PlotSpec => ({ x: { domain: [0, 1] }, y: { domain: [-1, 1] }, marks: [{ type: 'line', x: 'x', y: 'y', data: points.map(([x, y]) => ({ x, y })) }] })
  assert.deepEqual(spot(line([[0, -1], [0.5, 0.03], [1, 0.03]]), 0, 0.1, 0.025), { left: false, below: true })
  assert.deepEqual(spot(line([[0, -1], [0.6, -1], [0.7, 0], [1, 0]]), 0, 0.1, 0.025), { left: true, below: false })
})

test('a bar or area reaches down to the zero it is drawn from, and a rect spans its corners', () => {
  const bars: PlotSpec = { marks: [{ type: 'bar', x: 'k', y: 'n', data: [{ k: 'a', n: 3 }, { k: 'b', n: 5 }] }] }
  assert.deepEqual(span(bars, 'y'), [0, 5])
  const area: PlotSpec = { marks: [{ type: 'area', x: 't', y: 'v', data: [{ t: 1, v: -2 }, { t: 4, v: -1 }] }] }
  assert.deepEqual(span(area, 'y'), [-2, 0])
  assert.deepEqual(span(area, 'x'), [1, 4])
  const rect: PlotSpec = { marks: [{ type: 'rect', x1: 'a', x2: 'b', y1: 'c', y2: 'd', data: [{ a: 1, b: 2, c: 10, d: 20 }, { a: 3, b: 7, c: 5, d: 8 }] }] }
  assert.deepEqual(span(rect, 'x'), [1, 7])
  assert.deepEqual(span(rect, 'y'), [5, 20])
})

test("a horizontal rule's label on a log axis is kept off a curve where the curve is drawn, not where its numbers fall", () => {
  // a rule at 300 on 1..1000: a curve at 700 is two fifths of the frame above it when linear, under a sixth when log
  const curve = (type?: 'log'): PlotSpec => ({
    x: { domain: [0, 1] },
    y: { domain: [1, 1000], type },
    marks: [{ type: 'line', x: 'x', y: 'y', data: [{ x: 0.8, y: 700 }, { x: 1, y: 700 }] }],
  })
  assert.deepEqual(spot(curve(), 300, 0.1, 0.2), { left: false, below: false })
  assert.deepEqual(spot(curve('log'), 300, 0.1, 0.2), { left: false, below: true })
})

test('a note is on a rule by how far apart they are drawn on a sqrt axis, not by their numbers', () => {
  // x 1 and 2 on 0..100 are a hundredth apart in numbers, but four hundredths apart drawn on a sqrt axis
  const spec = (type?: 'sqrt'): PlotSpec => ({ x: { domain: [0, 100], type }, y: { domain: [0, 1] }, marks: [{ type: 'rule', x: 1 }] })
  assert.deepEqual(place(spec(), 2, 0.5, 0.1), { textAnchor: 'start', dx: 6 })
  assert.deepEqual(place(spec('sqrt'), 2, 0.5, 0.1), { textAnchor: 'middle', dx: 0 })
})
