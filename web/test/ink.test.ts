import assert from 'node:assert/strict'
import { test } from 'node:test'
import { InkError, Settled, beatAt, boardLink, duration, frameAt, hit, markAlt, plan, readInk, resolve, restAt, settled } from '../src/ink.ts'
import type { Plan } from '../src/ink.ts'
import { doc2 } from './inkDoc.ts'

type Doc = ReturnType<typeof doc2>
const refused = (change: (d: Doc) => void, why?: RegExp) => {
  const d = doc2()
  change(d)
  assert.throws(() => readInk(d), (e: unknown) => e instanceof InkError && (!why || why.test(e.message)))
}
const done = (p: Plan, t: number) => settled(p, frameAt(p, t))

test('a document reads into one shape, its unknown fields and trailing point values left out', () => {
  const d = readInk(doc2())
  assert.deepEqual(d.elements[1].marks.get('k'), [150, 100, 50, 60])
  assert.equal(d.elements[0].marks.size, 0)
  assert.equal('future' in d.elements[1], false)
  assert.equal('later' in d, false)
  assert.deepEqual(d.strokes[2].path[0], [0, 140, 450, 0.5, 2])
})

test('a schema is looked up by number only, never through the prototype', () => {
  for (const schema of ['2', '1', 'constructor', 'toString', '__proto__', 3, 0, null]) refused((d) => ((d as { schema: unknown }).schema = schema), /schema/)
})

test('marks, ids and inks named after prototype keys find nothing', () => {
  const d = doc2()
  d.elements[1].marks = JSON.parse('{"k":[150,100,50,60],"__proto__":[1,1,1,1]}')
  const p = plan(readInk(d))
  for (const ref of ['eq.constructor', 'eq.toString', 'constructor', 'toString', 'eq.hasOwnProperty']) assert.equal(resolve(p, ref, 900), null, ref)
  assert.deepEqual(resolve(p, 'eq.__proto__', 900)?.box, [1, 1, 1, 1])
})

test('every validity rule of the schema refuses a document that breaks it', () => {
  refused((d) => (d.beats[0].draw = [9]), /out of range/)
  refused((d) => {
    d.beats[0].erase = [{ start: 300, t: 310, r: 5, path: [[0, 0, 300], [1, 1, 310]], strokes: [1] }]
    d.beats[1].erase = []
    d.ghosts = []
  }, /before it is written/)
  refused((d) => (d.beats[1].erase as unknown[]).push({ start: 1500, t: 1600, r: 5, path: [[0, 0, 1500], [0, 0, 1600]], strokes: [1] }), /erased twice/)
  refused((d) => (d.beats[0].start = 1.5), /not a time/)
  refused((d) => (d.strokes[0].outline = 'M0 0C1 1 2 2 3 3Z'), /outline/)
  refused((d) => (d.elements[2].page = 2), /out of range/)
  refused((d) => (d.strokes[1].path = []), /empty/)
  refused((d) => (d.strokes[1].path[1][2] = 150), /back in time/)
  refused((d) => (d.strokes[2].path[0][2] = 300), /starts before/)
  refused((d) => (d.strokes[1].path[0][3] = 2), /out of bounds/)
  refused((d) => (d.strokes[1].path[0][4] = -1), /out of bounds/)
  refused((d) => (d.strokes[1].path[0][4] = 1e9), /out of bounds/)
  refused((d) => (d.beats[1].erase[0].path = []), /empty/)
  refused((d) => (d.beats[1].erase[0].start = 1150), /from start to t/)
  refused((d) => (d.beats[1].erase[0].t = 1500), /from start to t/)
  refused((d) => {
    d.beats[1].erase[0] = { ...d.beats[1].erase[0], start: 900, path: [[0, 130, 900], [300, 130, 1400]] }
  }, /outside its beat/)
  refused((d) => (d.beats[1].erase[0].r = 0), /out of bounds/)
  refused((d) => (d.beats[1].erase[0].r = 1e9), /out of bounds/)
  refused((d) => (d.beats[1].start = 1100), /does not start where/)
  refused((d) => (d.beats[0].start = 50), /preamble/)
  refused((d) => (d.beats[1].end = 900), /ends before/)
  refused((d) => (d.beats[0].end = 500), /outside its beat|does not start/)
  refused((d) => (d.beats[0].draw = [2, 1]), /time order/)
  refused((d) => (d.ghosts[0].t = 1300), /end of a sweep/)
  refused((d) => (d.ghosts[0].beat = 0), /erases nothing/)
  refused((d) => (d.ghosts[0].opacity = 0.5), /out of bounds/)
  refused((d) => (d.ghosts[0].opacity = 0.01), /out of bounds/)
  refused((d) => (d.page = [0, 1000]), /out of bounds/)
  refused((d) => (d.page = [1e9, 1000]), /out of bounds/)
  refused((d) => (d.page = [1600]), /size/)
  refused((d) => (d.pages = 1.5), /count/)
  refused((d) => (d.pages = 1e9), /out of bounds/)
  refused((d) => (d.elements[0].box = [0, 0, -5, 40]), /out of bounds/)
  refused((d) => (d.elements[0].box = [1e9, 0, 5, 40]), /out of bounds/)
})

const v1 = (d: Doc) => ({
  ...d,
  schema: 1,
  beats: [d.beats[0], { ...d.beats[1], erase: [{ t: 1400, strokes: [1, 2] }] }],
  ghosts: [{ beat: 1, page: 0, outline: 'M0 100L300 100L300 160Z' }],
})

test('a schema 1 document erases at an instant and its ghosts show with the first erase', () => {
  const p = plan(readInk(v1(doc2())))
  assert.deepEqual(done(p, 1399), [0, 1, 2])
  assert.deepEqual(done(p, 1400), [0])
  assert.deepEqual(frameAt(p, 1400).ghosts, [0])
  assert.equal(p.doc.ghosts[0].opacity, 0.06)
})

test('a schema 1 erase in the first beat is read, and one outside its beat refused', () => {
  const d = doc2()
  const ok = { ...v1(d), beats: [{ ...d.beats[0], erase: [{ t: 800, strokes: [1] }] }, { ...d.beats[1], erase: [] }], ghosts: [] }
  const p = plan(readInk(ok))
  assert.deepEqual(done(p, 799), [0, 1, 2])
  assert.deepEqual(done(p, 800), [0, 2])
  assert.throws(() => readInk({ ...ok, beats: [{ ...d.beats[0], erase: [{ t: 1200, strokes: [1] }] }, ok.beats[1]] }), InkError)
  assert.throws(() => readInk({ ...ok, beats: [{ ...d.beats[0], erase: [{ t: 300, strokes: [1] }] }, ok.beats[1]] }), InkError)
})

test('a frame lists the stroke being written up to its tip, and the pen there', () => {
  const p = plan(readInk(doc2()))
  const f = frameAt(p, 300)
  assert.equal(f.beat, 0)
  assert.deepEqual(settled(p, f), [0])
  assert.deepEqual(f.drawing, [{ stroke: 1, tips: [[0, 120, 2], [50, 120, 2]] }])
  assert.deepEqual(f.pen, { x: 50, y: 120, down: true, eraser: false })
  assert.equal(f.active, 1)
  // between strokes the pen travels lifted
  assert.deepEqual(frameAt(p, 425).pen, { x: 50, y: 130, down: false, eraser: false })
})

test('a sweep hides its strokes from its start, leaves them gone at its end, and its ghost appears then', () => {
  const p = plan(readInk(doc2()))
  const f = frameAt(p, 1300)
  assert.deepEqual(settled(p, f), [0])
  assert.deepEqual(f.erasing, [{ strokes: [1, 2], r: 20, path: [[0, 130], [150, 130]] }])
  assert.deepEqual(f.pen, { x: 150, y: 130, down: true, eraser: true })
  assert.deepEqual(f.ghosts, [])
  assert.deepEqual(frameAt(p, 1400).erasing, [])
  assert.deepEqual(frameAt(p, 1400).ghosts, [0])
})

test('the view moves to the page a stroke starts on, and show(n) stands after beat n', () => {
  const p = plan(readInk(doc2()))
  assert.equal(frameAt(p, 1999).page, 0)
  assert.equal(frameAt(p, 2000).page, 1)
  assert.deepEqual(done(p, restAt(p.doc, 1)), [3])
  assert.equal(restAt(p.doc, -1), 100)
  assert.equal(restAt(p.doc, 9), 3000)
  assert.equal(beatAt(p, 99), -1)
  assert.equal(beatAt(p, 1000), 1)
})

test('refs resolve to an element or a mark, and a tap finds the smallest thing under it', () => {
  const p = plan(readInk(doc2()))
  assert.deepEqual(resolve(p, 'eq.k', 500), { el: 1, mark: 'k', box: [150, 100, 50, 60], page: 0 })
  assert.equal(resolve(p, 'eq.nope', 500), null)
  assert.equal(hit(p, 0, 160, 130, 700), 'eq.k')
  assert.equal(hit(p, 0, 20, 130, 700), 'eq')
  assert.equal(hit(p, 0, 20, 130, 150), null)
  assert.equal(hit(p, 0, 20, 130, 1500), null)
})

test('a mark asks about its own LaTeX', () => {
  assert.equal(markAlt('a = \\mark{k}{\\frac{1}{2}} b', 'k'), '\\frac{1}{2}')
  assert.equal(markAlt('a = b', 'k'), 'a = b')
})

test('a board link names any id the schema allows, percent-encoded', () => {
  assert.deepEqual(boardLink('#board-12-main.sum'), { block: 12, ref: 'main.sum' })
  assert.deepEqual(boardLink('#board-3-%23eq2'), { block: 3, ref: '#eq2' })
  assert.deepEqual(boardLink('#board-3-circle%20main.sum'), { block: 3, ref: 'circle main.sum' })
  assert.deepEqual(boardLink('#board-3-arrow%20why%20-%3E%20an.k%232'), { block: 3, ref: 'arrow why -> an.k#2' })
  assert.deepEqual(boardLink('#board-3-a1-b'), { block: 3, ref: 'a1-b' })
  assert.deepEqual(boardLink('#board-3-42'), { block: 3, ref: '42' })
  assert.equal(boardLink('#board-3-%E0%A4%A'), null)
  assert.equal(boardLink('#board--x'), null)
  assert.equal(boardLink('#part-x'), null)
})

test('the settled cache adds strokes as they settle and starts over after a seek back or a sweep', () => {
  const p = plan(readInk(doc2()))
  const cache = new Settled()
  const painted: number[] = []
  let resets = 0
  const reset = () => {
    resets++
    painted.length = 0
  }
  const step = (t: number) => cache.next(p, frameAt(p, t), 'k', reset, (i) => painted.push(i))
  step(150)
  step(500)
  step(700)
  assert.deepEqual([painted, resets], [[0, 1, 2], 1])
  step(1300)
  assert.deepEqual([painted, resets], [[0], 2])
  step(300)
  assert.deepEqual([painted, resets], [[0], 3])
})

// Random edits of a valid document: each is either refused with an InkError or replays without throwing.
test('a hostile document is refused or replayed, never crashing the reader or a frame', () => {
  let seed = 42
  const rand = (n: number) => ((seed = (seed * 1664525 + 1013904223) >>> 0) % n)
  const values: unknown[] = [-1, 0, 1, 1.5, 0.05, 1e9, -1e9, 2 ** 60, '', '1', 'constructor', '__proto__', null, [], {}, true, 'M0 0Z', [0, 0, 0, 0]]
  const slots = (v: unknown, out: [Record<string, unknown>, string][] = []) => {
    if (!v || typeof v !== 'object') return out
    const o = v as Record<string, unknown>
    for (const k of Object.keys(o)) {
      out.push([o, k])
      slots(o[k], out)
    }
    return out
  }
  for (let n = 0; n < 2000; n++) {
    const d = doc2() as unknown as Record<string, unknown>
    for (let edits = 1 + rand(3); edits > 0; edits--) {
      const all = slots(d)
      const [o, k] = all[rand(all.length)]
      if (rand(5) === 0) delete o[k]
      else o[k] = structuredClone(values[rand(values.length)])
    }
    let p: Plan
    try {
      p = plan(readInk(d))
    } catch (e) {
      assert.ok(e instanceof InkError, `${(e as Error).stack}\n${JSON.stringify(d)}`)
      continue
    }
    for (let t = 0; t <= duration(p.doc) + 100; t += 97) {
      const f = frameAt(p, t)
      settled(p, f)
      hit(p, f.page, 160, 130, t)
      resolve(p, 'eq.k', t)
    }
  }
})

// 50 beats of 100 strokes each; every fifth beat wipes the strokes of the beat before it.
function longBoard() {
  const strokes: unknown[] = []
  const beats: unknown[] = []
  let t = 0
  for (let b = 0; b < 50; b++) {
    const start = t
    const draw: number[] = []
    const erase: unknown[] = []
    if (b % 5 === 4) {
      erase.push({ start: t, t: t + 200, r: 30, path: [[0, 0, t], [1600, 1000, t + 200]], strokes: Array.from({ length: 100 }, (_, k) => (b - 1) * 100 + k) })
      t += 200
    }
    for (let k = 0; k < 100; k++) {
      draw.push(strokes.length)
      strokes.push({ el: b, outline: 'M0 0L10 0L10 10Z', path: [[k * 10, b * 20, t, 0.5, 2], [k * 10 + 5, b * 20, t + 20, 0.5, 2], [k * 10 + 9, b * 20, t + 40, 0.5, 2]] })
      t += 50
    }
    t += 1000
    beats.push({ say: `Beat ${b}`, start, end: t, draw, erase, page: 0 })
  }
  const elements = Array.from({ length: 50 }, (_, b) => ({ id: `e${b}`, kind: 'text', page: 0, box: [0, b * 20, 1000, 20], ink: 'ink', alt: `e${b}` }))
  return { schema: 2, page: [1600, 1000], pages: 1, elements, strokes, preamble: [], beats, ghosts: [] }
}

test('a 5000-stroke board plays each frame within budget', () => {
  const p = plan(readInk(longBoard()))
  assert.equal(p.doc.strokes.length, 5000)
  const cache = new Settled()
  let painted = 0
  const frames = 5000
  const step = duration(p.doc) / frames
  const began = performance.now()
  for (let k = 0; k <= frames; k++) cache.next(p, frameAt(p, k * step), 'k', () => {}, () => painted++)
  const perFrame = (performance.now() - began) / frames
  // each stroke is painted once, plus a repaint of what stands at each of the 10 sweeps
  assert.ok(painted <= 5000 + 10 * 5000, `${painted} paints`)
  assert.ok(perFrame < 0.1, `${perFrame.toFixed(3)} ms a frame`)
})
