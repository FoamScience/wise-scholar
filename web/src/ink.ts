// The open side of wise-board: an ink document (schema in the wise-board repo, crates/wb-ink/SCHEMA.md) read into one
// shape whatever its schema version, and the pure lookups a player needs at a time t. No DOM here.
// A document is untrusted: everything the schema does not allow is refused before a player sees it.
export type Box = [number, number, number, number]
export type Tip = [number, number, number] // x, y, reveal radius
export type InkElement = { id: string; kind: string; page: number; box: Box; marks: Map<string, Box>; ink: string; alt: string }
export type InkStroke = { el: number; marks: string[]; outline: string; path: [number, number, number, number, number][]; ink?: string }
export type Sweep = { start: number; t: number; r: number; path: [number, number, number][]; strokes: number[] }
export type InkBeat = { say: string; start: number; end: number; draw: number[]; erase: Sweep[]; focus?: string; page: number }
export type Ghost = { beat: number; t: number; page: number; opacity: number; outline: string }
export type InkDoc = {
  schema: number
  page: [number, number]
  pages: number
  elements: InkElement[]
  strokes: InkStroke[]
  preamble: number[]
  beats: InkBeat[]
  ghosts: Ghost[]
}

export class InkError extends Error {}

export const INKS = new Set(['ink', 'accent', 'alert', 'muted', 'good', 'note'])
export const ANNOTATIONS = new Set(['circle', 'box', 'underline', 'cross', 'highlight', 'check', 'brace', 'arrow'])
const MAX_T = 2 ** 53
// Bounds the schema leaves open, wide enough for any board wise-board writes.
const MAX_LEN = 1e6
const MAX_PAGES = 1000
const OPACITY: [number, number] = [0.04, 0.08]
const OUTLINE = /^[MLZ0-9.eE+\-\s,]*$/

type Raw = Record<string, unknown>

function fail(what: string): never {
  throw new InkError(`ink document: ${what}`)
}

function obj(v: unknown, at: string): Raw {
  if (!v || typeof v !== 'object' || Array.isArray(v)) fail(`${at} is not an object`)
  return v as Raw
}

// Dense, so a hole in a built (not parsed) array is checked like any other value instead of skipped.
function list(v: unknown, at: string): unknown[] {
  if (!Array.isArray(v)) fail(`${at} is not a list`)
  return Array.from(v)
}

function num(v: unknown, at: string, lo = -MAX_LEN, hi = MAX_LEN): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) fail(`${at} is not a number`)
  if (v < lo || v > hi) fail(`${at} is out of bounds`)
  return v
}

function str(v: unknown, at: string): string {
  if (typeof v !== 'string') fail(`${at} is not a string`)
  return v
}

function time(v: unknown, at: string): number {
  const t = num(v, at, 0, MAX_T)
  if (!Number.isInteger(t)) fail(`${at} is not a time`)
  return t
}

function index(v: unknown, count: number, at: string): number {
  const i = num(v, at, 0, MAX_T)
  if (!Number.isInteger(i) || i >= count) fail(`${at} is out of range`)
  return i
}

function box(v: unknown, at: string): Box {
  const b = list(v, at)
  if (b.length !== 4) fail(`${at} is not a box`)
  return [num(b[0], `${at}[0]`), num(b[1], `${at}[1]`), num(b[2], `${at}[2]`, 0), num(b[3], `${at}[3]`, 0)]
}

function outline(v: unknown, at: string): string {
  const d = str(v, at)
  if (!OUTLINE.test(d)) fail(`${at} holds more than M, L, Z and numbers`)
  return d
}

// A timed path, never empty, its times never decreasing. Values past the ones a schema defines are ignored (forward
// compatibility), so each point is cut to its known length.
function path(v: unknown, at: string, check: ((x: number, k: number, where: string) => number)[]): number[][] {
  const pts = list(v, at)
  if (!pts.length) fail(`${at} is empty`)
  const out = pts.map((p, j) => {
    const q = list(p, `${at}[${j}]`)
    if (q.length < check.length) fail(`${at}[${j}] has fewer than ${check.length} values`)
    return check.map((c, k) => c(q[k] as number, k, `${at}[${j}][${k}]`))
  })
  if (out.some((p, j) => j > 0 && p[2] < out[j - 1][2])) fail(`${at} goes back in time`)
  return out
}

const coord = (x: unknown, _k: number, at: string) => num(x, at)
const at_ = (x: unknown, _k: number, at: string) => time(x, at)
const STROKE_POINT = [coord, coord, at_, (x: unknown, _k: number, at: string) => num(x, at, 0, 1), (x: unknown, _k: number, at: string) => num(x, at, 0)]
const ERASER_POINT = [coord, coord, at_]

/** Schema 1 or 2, read into the current shape. Fields a reader does not know are left out. */
function read(raw: Raw, schema: 1 | 2): InkDoc {
  const size = list(raw.page, 'page')
  if (size.length !== 2) fail('page is not a size')
  const page: [number, number] = [num(size[0], 'page[0]', 1), num(size[1], 'page[1]', 1)]
  const pages = num(raw.pages, 'pages', 1, MAX_PAGES)
  if (!Number.isInteger(pages)) fail('pages is not a count')
  const onPage = (v: unknown, at: string) => index(v, pages, at)

  const elements = list(raw.elements, 'elements').map((v, i): InkElement => {
    const e = obj(v, `elements[${i}]`)
    const marks = e.marks === undefined ? {} : obj(e.marks, `elements[${i}].marks`)
    return {
      id: str(e.id, `elements[${i}].id`),
      kind: str(e.kind, `elements[${i}].kind`),
      page: onPage(e.page, `elements[${i}].page`),
      box: box(e.box, `elements[${i}].box`),
      marks: new Map(Object.entries(marks).map(([k, m]) => [k, box(m, `elements[${i}].marks.${k}`)])),
      ink: str(e.ink, `elements[${i}].ink`),
      alt: str(e.alt, `elements[${i}].alt`),
    }
  })

  const strokes = list(raw.strokes, 'strokes').map((v, i): InkStroke => {
    const s = obj(v, `strokes[${i}]`)
    return {
      el: index(s.el, elements.length, `strokes[${i}].el`),
      marks: s.marks === undefined ? [] : list(s.marks, `strokes[${i}].marks`).map((m, j) => str(m, `strokes[${i}].marks[${j}]`)),
      outline: outline(s.outline, `strokes[${i}].outline`),
      path: path(s.path, `strokes[${i}].path`, STROKE_POINT) as InkStroke['path'],
      // an ink this player does not know falls back to the element's
      ...(typeof s.ink === 'string' && INKS.has(s.ink) ? { ink: s.ink } : {}),
    }
  })
  strokes.forEach((s, i) => {
    if (i > 0 && strokeStart(s) < strokeEnd(strokes[i - 1])) fail(`strokes[${i}] starts before strokes[${i - 1}] ends`)
  })
  const stroke = (v: unknown, at: string) => index(v, strokes.length, at)
  const preamble = list(raw.preamble, 'preamble').map((x, k) => stroke(x, `preamble[${k}]`))
  const preambleEnd = preamble.length ? Math.max(...preamble.map((i) => strokeEnd(strokes[i]))) : 0

  const erased = new Set<number>()
  let clock = -1
  const beats = list(raw.beats, 'beats').map((v, i): InkBeat => {
    const b = obj(v, `beats[${i}]`)
    const start = time(b.start, `beats[${i}].start`)
    const end = time(b.end, `beats[${i}].end`)
    if (end < start) fail(`beats[${i}] ends before it starts`)
    if (i === 0 && start !== preambleEnd) fail('beats[0] does not start where the preamble ends')
    if (i > 0 && start !== clock) fail(`beats[${i}] does not start where beats[${i - 1}] ends`)
    clock = end
    const draw = list(b.draw, `beats[${i}].draw`).map((x, k) => stroke(x, `beats[${i}].draw[${k}]`))
    draw.forEach((s, k) => {
      if (strokeStart(strokes[s]) < start || strokeEnd(strokes[s]) > end) fail(`beats[${i}].draw[${k}] is drawn outside its beat`)
      if (k > 0 && s <= draw[k - 1]) fail(`beats[${i}].draw is not in time order`)
    })
    let swept = start
    const erase = list(b.erase, `beats[${i}].erase`).map((w, j): Sweep => {
      const at = `beats[${i}].erase[${j}]`
      const e = obj(w, at)
      const t = time(e.t, `${at}.t`)
      // schema 1 erases at an instant, with no eraser to show
      const sweep: Sweep =
        schema === 1
          ? { start: t, t, r: 0, path: [], strokes: [] }
          : {
              start: time(e.start, `${at}.start`),
              t,
              r: num(e.r, `${at}.r`, Number.MIN_VALUE),
              path: path(e.path, `${at}.path`, ERASER_POINT) as Sweep['path'],
              strokes: [],
            }
      if (schema === 2 && (sweep.path[0][2] !== sweep.start || sweep.path.at(-1)![2] !== t)) fail(`${at}.path does not run from start to t`)
      if (sweep.start < swept || t > end) fail(`${at} is outside its beat or before the previous sweep ends`)
      swept = t
      sweep.strokes = list(e.strokes, `${at}.strokes`).map((x, k) => stroke(x, `${at}.strokes[${k}]`))
      for (const s of sweep.strokes) {
        if (erased.has(s)) fail(`stroke ${s} is erased twice`)
        if (strokeEnd(strokes[s]) > sweep.start) fail(`${at} erases stroke ${s} before it is written`)
        erased.add(s)
      }
      return sweep
    })
    return {
      say: str(b.say, `beats[${i}].say`),
      start,
      end,
      draw,
      erase,
      focus: b.focus === undefined ? undefined : str(b.focus, `beats[${i}].focus`),
      page: onPage(b.page, `beats[${i}].page`),
    }
  })

  let shown = 0
  const ghosts = list(raw.ghosts, 'ghosts').map((v, i) => {
    const g = readGhost(obj(v, `ghosts[${i}]`), i, beats, pages, schema)
    if (g.t < shown) fail(`ghosts[${i}] appears before ghosts[${i - 1}]`)
    shown = g.t
    return g
  })
  return { schema, page, pages, elements, strokes, preamble, beats, ghosts }
}

// Schema 1 reserved ghosts with no time or opacity: one appears with its beat's first erase, at mid opacity.
const GHOST_OPACITY = 0.06

/** Where ghost support plugs in: a wipe's faint mark, timed to one of its beat's sweeps. */
function readGhost(g: Raw, i: number, beats: InkBeat[], pages: number, schema: 1 | 2): Ghost {
  const beat = index(g.beat, beats.length, `ghosts[${i}].beat`)
  const sweeps = beats[beat].erase
  if (!sweeps.length) fail(`ghosts[${i}] belongs to a beat that erases nothing`)
  const t = schema === 1 ? sweeps[0].t : time(g.t, `ghosts[${i}].t`)
  if (!sweeps.some((w) => w.t === t)) fail(`ghosts[${i}].t is not the end of a sweep in its beat`)
  return {
    beat,
    t,
    page: index(g.page, pages, `ghosts[${i}].page`),
    opacity: schema === 1 ? GHOST_OPACITY : num(g.opacity, `ghosts[${i}].opacity`, OPACITY[0], OPACITY[1]),
    outline: outline(g.outline, `ghosts[${i}].outline`),
  }
}

// Every schema version, each read into the current shape.
const SCHEMAS = new Map<number, (raw: Raw) => InkDoc>([
  [1, (raw) => read(raw, 1)],
  [2, (raw) => read(raw, 2)],
])

/** A stored document, checked as the schema's validity rules say; anything else throws InkError. */
export function readInk(json: unknown): InkDoc {
  const raw = obj(json, 'document')
  const reader = typeof raw.schema === 'number' ? SCHEMAS.get(raw.schema) : undefined
  if (!reader) fail(`schema ${JSON.stringify(raw.schema) ?? typeof raw.schema} is not one this player knows`)
  return reader(raw)
}

export const strokeStart = (s: InkStroke) => s.path[0][2]
export const strokeEnd = (s: InkStroke) => s.path.at(-1)![2]

/** Time the board stands at rest before beat 0, the preamble drawn. */
export const opening = (doc: InkDoc) => doc.beats[0]?.start ?? Math.max(0, ...doc.preamble.map((i) => strokeEnd(doc.strokes[i])))
export const duration = (doc: InkDoc) => doc.beats.at(-1)?.end ?? opening(doc)

/** The time `show(n)` stands at: the board after beat n. */
export const restAt = (doc: InkDoc, n: number) => (n < 0 || !doc.beats.length ? opening(doc) : doc.beats[Math.min(n, doc.beats.length - 1)].end)

/** How many of the ascending `xs` are at most `t`. */
function upTo(xs: ArrayLike<number>, t: number): number {
  let lo = 0
  let hi = xs.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (xs[mid] <= t) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** How many of the ascending `xs` are below `n`. */
function below(xs: ArrayLike<number>, n: number): number {
  return upTo(xs, n - 1)
}

/** Timing indices over a read document, built once, so that a frame costs O(log n) plus what is moving in it. */
export type Plan = {
  doc: InkDoc
  starts: Float64Array
  ends: Float64Array
  strokePage: Int32Array
  byPage: Int32Array[] // stroke indices on each page, ascending
  sweeps: { w: Sweep; beat: number; page: number }[] // every sweep, in time order
  sweepStarts: Float64Array
  sweepOf: Int32Array // the sweep that erases a stroke, or -1
  beatStarts: Float64Array
  ghostTimes: Float64Array
  elStart: Float64Array // an element is on the board from its first stroke…
  elGone: Float64Array // …until every stroke of it is erased
  ids: Map<string, number[]>
}

export function plan(doc: InkDoc): Plan {
  const n = doc.strokes.length
  const strokePage = Int32Array.from(doc.strokes, (s) => doc.elements[s.el].page)
  const byPage = Array.from({ length: doc.pages }, () => [] as number[])
  strokePage.forEach((pg, i) => byPage[pg].push(i))
  const sweeps = doc.beats.flatMap((b, beat) => b.erase.map((w) => ({ w, beat, page: w.strokes.length ? strokePage[w.strokes[0]] : -1 })))
  const sweepOf = new Int32Array(n).fill(-1)
  sweeps.forEach(({ w }, k) => w.strokes.forEach((s) => (sweepOf[s] = k)))
  const elStart = new Float64Array(doc.elements.length).fill(Infinity)
  const elGone = new Float64Array(doc.elements.length).fill(-Infinity)
  doc.strokes.forEach((s, i) => {
    elStart[s.el] = Math.min(elStart[s.el], strokeStart(s))
    elGone[s.el] = Math.max(elGone[s.el], sweepOf[i] < 0 ? Infinity : sweeps[sweepOf[i]].w.t)
  })
  const ids = new Map<string, number[]>()
  doc.elements.forEach((e, i) => ids.set(e.id, [...(ids.get(e.id) ?? []), i]))
  return {
    doc,
    starts: Float64Array.from(doc.strokes, strokeStart),
    ends: Float64Array.from(doc.strokes, strokeEnd),
    strokePage,
    byPage: byPage.map((xs) => Int32Array.from(xs)),
    sweeps,
    sweepStarts: Float64Array.from(sweeps, (s) => s.w.start),
    sweepOf,
    beatStarts: Float64Array.from(doc.beats, (b) => b.start),
    ghostTimes: Float64Array.from(doc.ghosts, (g) => g.t),
    elStart,
    elGone,
    ids,
  }
}

/** The beat playing at t, or -1 before the first. */
export const beatAt = (p: Plan, t: number) => upTo(p.beatStarts, t) - 1

function lerp(a: number[], b: number[], f: number, n: number): number[] {
  return Array.from({ length: n }, (_, k) => a[k] + (b[k] - a[k]) * f)
}

// The part of a timed path written by t, its last point interpolated; `keep` picks the values kept per point.
function prefix<P extends number[]>(path: P[], t: number, keep: number[]): number[][] {
  const out: number[][] = []
  const pick = (p: number[]) => keep.map((k) => p[k])
  for (let j = 0; j < path.length; j++) {
    const p = path[j]
    if (p[2] <= t) {
      out.push(pick(p))
      continue
    }
    if (j > 0) {
      const q = path[j - 1]
      const f = p[2] === q[2] ? 1 : (t - q[2]) / (p[2] - q[2])
      out.push(pick(lerp(q, p, f, p.length)))
    }
    break
  }
  return out
}

/** The centerline written by t, each point with its reveal radius. */
export const revealed = (s: InkStroke, t: number) => prefix(s.path, t, [0, 1, 4]) as Tip[]

/** The eraser's path travelled by t. */
export const swept = (w: Sweep, t: number) => prefix(w.path, t, [0, 1]) as [number, number][]

export type Pen = { x: number; y: number; down: boolean; eraser: boolean }
/** What a renderer draws at t. Settled strokes are not listed (see `settled` and `Settled`): those written by
 * `finished`, on `page`, and not erased by any of the first `sweepsStarted` sweeps. */
export type Frame = {
  t: number
  page: number
  beat: number
  finished: number
  sweepsStarted: number
  drawing: { stroke: number; tips: Tip[] }[]
  erasing: { strokes: number[]; r: number; path: [number, number][] }[]
  ghosts: number[]
  pen: Pen | null
  active: number // element being written or erased, or -1
}

/** The page on view at t: the beat's own, then whichever page the latest stroke or sweep in the beat started on. */
function pageAt(p: Plan, bi: number, started: number, sweepsStarted: number): number {
  const { doc } = p
  const from = bi < 0 ? 0 : doc.beats[bi].start
  let page = bi < 0 ? (doc.preamble.length ? p.strokePage[doc.preamble[0]] : 0) : doc.beats[bi].page
  let latest = -1
  const k = started - 1
  if (k >= 0 && p.starts[k] >= from) {
    page = p.strokePage[k]
    latest = p.starts[k]
  }
  const sw = p.sweeps[sweepsStarted - 1]
  if (sw && sw.beat === bi && sw.page >= 0 && sw.w.start >= latest) page = sw.page
  return page
}

const inBeat = (p: Plan, beat: InkBeat, k: number) => k >= 0 && k < p.starts.length && p.starts[k] >= beat.start && p.starts[k] < beat.end

// The end of a stroke in the beat on the page, where the pen rests before or after it.
function restPoint(p: Plan, beat: InkBeat, page: number, k: number, end: boolean) {
  if (!inBeat(p, beat, k) || p.strokePage[k] !== page) return null
  const { path } = p.doc.strokes[k]
  return path[end ? path.length - 1 : 0]
}

// The pen between strokes: moving from the end of the one written to the start of the next, or waiting at either.
function restingPen(p: Plan, beat: InkBeat, page: number, t: number, started: number): Pen | null {
  const prev = started - 1
  const next = started
  const a = restPoint(p, beat, page, prev, true)
  const b = restPoint(p, beat, page, next, false)
  if (a && b) {
    const f = p.starts[next] === p.ends[prev] ? 1 : (t - p.ends[prev]) / (p.starts[next] - p.ends[prev])
    return { x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f, down: false, eraser: false }
  }
  const at = a ?? b
  return at ? { x: at[0], y: at[1], down: false, eraser: false } : null
}

function penAt(p: Plan, bi: number, page: number, t: number, started: number, sweep: Sweep | undefined): Pen | null {
  if (sweep) {
    const tip = swept(sweep, t).at(-1)
    return tip ? { x: tip[0], y: tip[1], down: true, eraser: true } : null
  }
  if (bi < 0) return null
  const beat = p.doc.beats[bi]
  const prev = started - 1
  if (inBeat(p, beat, prev) && p.ends[prev] > t) {
    if (p.strokePage[prev] !== page) return null
    const tip = revealed(p.doc.strokes[prev], t).at(-1)!
    return { x: tip[0], y: tip[1], down: true, eraser: false }
  }
  return restingPen(p, beat, page, t, started)
}

/** Everything a renderer draws at t, found by binary search over the plan. */
export function frameAt(p: Plan, t: number): Frame {
  const { doc } = p
  const beat = beatAt(p, t)
  const started = upTo(p.starts, t)
  const finished = upTo(p.ends, t)
  const sweepsStarted = upTo(p.sweepStarts, t)
  const page = pageAt(p, beat, started, sweepsStarted)
  const drawing: Frame['drawing'] = []
  let active = -1
  for (let i = finished; i < started; i++) {
    active = doc.strokes[i].el
    if (p.strokePage[i] === page) drawing.push({ stroke: i, tips: revealed(doc.strokes[i], t) })
  }
  const erasing: Frame['erasing'] = []
  let sweep: Sweep | undefined
  for (let k = sweepsStarted - 1; k >= 0 && p.sweeps[k].w.t > t; k--) {
    const { w } = p.sweeps[k]
    sweep ??= w
    if (w.strokes.length) active = doc.strokes[w.strokes[0]].el
    const strokes = w.strokes.filter((s) => p.strokePage[s] === page)
    if (strokes.length) erasing.unshift({ strokes, r: w.r, path: swept(w, t) })
  }
  const ghosts: number[] = []
  const shownGhosts = upTo(p.ghostTimes, t)
  for (let g = 0; g < shownGhosts; g++) if (doc.ghosts[g].page === page) ghosts.push(g)
  const pen = penAt(p, beat, page, t, started, sweep)
  return { t, page, beat, finished, sweepsStarted, drawing, erasing, ghosts, pen, active }
}

const isSettled = (p: Plan, f: Frame, i: number) => i < f.finished && p.strokePage[i] === f.page && !(p.sweepOf[i] >= 0 && p.sweepOf[i] < f.sweepsStarted)

/** Every settled stroke of a frame, in drawing order: O(strokes on the page). */
export function settled(p: Plan, f: Frame): number[] {
  const out: number[] = []
  for (const i of p.byPage[f.page] ?? []) if (isSettled(p, f, i)) out.push(i)
  return out
}

/** Keeps a cache of settled strokes in step with the frames shown: each frame either adds the strokes settled since
 * the last one, or, after a seek back, a sweep, a page change or a new `key`, starts the cache over. */
export class Settled {
  private page = -1
  private pos = 0
  private sweeps = -1
  private key: unknown = null

  /** Calls `paint` for each stroke to add, after `reset` when the cache must be cleared first. */
  next(p: Plan, f: Frame, key: unknown, reset: () => void, paint: (stroke: number) => void) {
    const list = p.byPage[f.page] ?? new Int32Array()
    const to = below(list, f.finished)
    let from = this.pos
    if (f.page !== this.page || f.sweepsStarted !== this.sweeps || key !== this.key || to < this.pos) {
      reset()
      from = 0
    }
    for (let k = from; k < to; k++) if (isSettled(p, f, list[k])) paint(list[k])
    this.page = f.page
    this.pos = to
    this.sweeps = f.sweepsStarted
    this.key = key
  }

  clear() {
    this.page = -1
  }
}

const live = (p: Plan, el: number, t: number) => p.elStart[el] <= t && p.elGone[el] > t

/** Whether an element is on the board at t. */
export const onBoard = live

/** An element `id` or a mark `id.mark`, the latest live one at t when an id was reused. */
export function resolve(p: Plan, ref: string, t: number): { el: number; mark?: string; box: Box; page: number } | null {
  const find = (id: string) => {
    const all = p.ids.get(id) ?? []
    return all.findLast((i) => live(p, i, t)) ?? all.at(-1)
  }
  let el = find(ref)
  let mark: string | undefined
  if (el === undefined) {
    const dot = ref.lastIndexOf('.')
    if (dot < 0) return null
    el = find(ref.slice(0, dot))
    mark = ref.slice(dot + 1)
    if (el === undefined || !p.doc.elements[el].marks.has(mark)) return null
  }
  const e = p.doc.elements[el]
  return { el, mark, box: mark ? e.marks.get(mark)! : e.box, page: e.page }
}

const inside = (b: Box, x: number, y: number) => x >= b[0] && y >= b[1] && x <= b[0] + b[2] && y <= b[1] + b[3]

/** The element (or its mark) under a point of the page at t, as a ref; annotations only where nothing else is. */
export function hit(p: Plan, page: number, x: number, y: number, t: number): string | null {
  const els = p.doc.elements.flatMap((e, i) => (e.page === page && inside(e.box, x, y) && live(p, i, t) ? [i] : []))
  const area = (b: Box) => b[2] * b[3]
  const best = (xs: number[]) => xs.sort((a, b) => area(p.doc.elements[a].box) - area(p.doc.elements[b].box))[0]
  const el = best(els.filter((i) => !ANNOTATIONS.has(p.doc.elements[i].kind))) ?? best(els)
  if (el === undefined) return null
  const e = p.doc.elements[el]
  const mark = [...e.marks]
    .filter(([, b]) => inside(b, x, y))
    .sort((a, b) => area(a[1]) - area(b[1]))[0]?.[0]
  return mark ? `${e.id}.${mark}` : e.id
}

/** The source of `\mark{name}{…}` in an element's LaTeX, or the whole alt. */
export function markAlt(alt: string, mark?: string): string {
  if (!mark) return alt
  const at = alt.indexOf(`\\mark{${mark}}{`)
  if (at < 0) return alt
  const from = at + mark.length + 8
  let depth = 1
  for (let i = from; i < alt.length; i++) {
    if (alt[i] === '\\') i++
    else if (alt[i] === '{') depth++
    else if (alt[i] === '}' && --depth === 0) return alt.slice(from, i)
  }
  return alt
}

/** `#board-<block>-<ref>` from lesson text: the block, and the element or mark, percent-decoded so any id the schema
 * allows (`#eq2`, `circle main.sum`, `arrow why -> an.k`) can be linked. */
export function boardLink(href: string | undefined): { block: number; ref: string } | null {
  const m = href?.match(/^#board-(\d+)-(.+)$/)
  if (!m) return null
  try {
    return { block: Number(m[1]), ref: decodeURIComponent(m[2]) }
  } catch {
    return null
  }
}

/** What "ask about this" starts from: the element's source, as math when it is an equation. */
export function prefill(doc: InkDoc, ref: string, about: (what: string) => string): string {
  const dot = ref.lastIndexOf('.')
  const whole = doc.elements.findLast((e) => e.id === ref)
  const e = whole ?? doc.elements.findLast((x) => x.id === ref.slice(0, dot))
  if (!e) return ''
  // a whole equation keeps its marked parts, without the \mark{name} that names them
  const src = (whole ? e.alt.replace(/\\mark\{[^{}]*\}/g, '') : markAlt(e.alt, ref.slice(dot + 1))).replace(/\s+/g, ' ').trim()
  return src ? about(e.kind === 'eq' ? `$${src}$` : src) : ''
}
