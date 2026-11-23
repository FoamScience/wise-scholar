// Replays an ink document (see ink.ts): each stroke's outline revealed along its timed centerline, eraser sweeps,
// ghosts, a pen, and a camera that follows the pen on narrow screens. Canvas, with an SVG fallback.
import { ANNOTATIONS, Settled, beatAt, duration, frameAt, hit, markAlt, onBoard, opening, plan, resolve, restAt } from './ink'
import type { Box, Frame, InkDoc, Plan, Tip } from './ink'

export type ThemeName = 'light' | 'dark'
type Look = { name: ThemeName; board: string; inks: Record<string, string>; pen: string; focus: string; chalk: boolean }

// Marker on a whiteboard, chalk on a blackboard: the same strokes, the inks' semantic names mapped to colours.
export const LOOKS: Record<ThemeName, Look> = {
  light: {
    name: 'light',
    board: '#fbfbf8',
    pen: '#3a3f47',
    focus: 'rgba(245, 197, 66, 0.28)',
    chalk: false,
    inks: { ink: '#1f2430', accent: '#1d4fbf', alert: '#c62828', muted: '#7d8590', good: '#2e7d32', note: '#7b3fa0' },
  },
  dark: {
    name: 'dark',
    board: '#26332d',
    pen: '#e8e6dc',
    focus: 'rgba(245, 223, 122, 0.16)',
    chalk: true,
    inks: { ink: '#f1efe6', accent: '#f5df7a', alert: '#f4a3a3', muted: '#a3ada7', good: '#b8e6a8', note: '#a8d4f0' },
  },
}

/** Below this width (CSS px) playback zooms to what is being written and follows the pen. */
export const NARROW = 640
const ZOOM_MAX = 3
const PINCH_MAX = 4
const MARGIN = 40
const EASE_MS = 250
const TAP_PX = 8
const HIGHLIGHT_ALPHA = 0.3
const MAX_LAYER_PX = 4096

/** Top-left of the view in page px and the zoom over the page fitting the view. */
export type Camera = { x: number; y: number; z: number }
export const FIT: Camera = { x: 0, y: 0, z: 1 }

export function clampCamera(c: Camera, page: [number, number], zMax = PINCH_MAX): Camera {
  const z = Math.min(zMax, Math.max(1, c.z))
  const [w, h] = page
  return { z, x: Math.min(w - w / z, Math.max(0, c.x)), y: Math.min(h - h / z, Math.max(0, c.y)) }
}

/** A view on a box, zoomed to read it; a box wider than the view is followed along `tipX`. */
export function cameraOn(box: Box, page: [number, number], tipX?: number): Camera {
  const [w, h] = page
  const z = Math.min(ZOOM_MAX, Math.max(1, h / (box[3] + 2 * MARGIN)))
  const vw = w / z
  const vh = h / z
  const wide = box[2] + 2 * MARGIN > vw
  const lo = box[0] - MARGIN + vw / 2
  const hi = box[0] + box[2] + MARGIN - vw / 2
  const cx = wide && tipX !== undefined ? Math.min(hi, Math.max(lo, tipX)) : wide ? lo : box[0] + box[2] / 2
  return clampCamera({ x: cx - vw / 2, y: box[1] + box[3] / 2 - vh / 2, z }, page)
}

export type Aim = { narrow: boolean; playing: boolean; reduced: boolean; user: Camera | null; marked: string | null; cam: Camera }

/** Where the camera wants to be for a frame. Reduced motion never moves it on its own: only the learner's zoom does. */
export function aim(p: Plan, f: Frame, a: Aim): Camera {
  if (a.user && !a.playing) return a.user
  if (a.reduced || !a.narrow) return FIT
  const at = (ref: string | null | undefined) => {
    const r = ref ? resolve(p, ref, f.t) : null
    return r && r.page === f.page ? r : null
  }
  if (!a.playing) {
    const m = at(a.marked)
    return m ? cameraOn(m.box, p.doc.page) : FIT
  }
  if (f.active >= 0 && p.doc.elements[f.active].page === f.page) return cameraOn(p.doc.elements[f.active].box, p.doc.page, f.pen?.x)
  const focus = at(f.beat >= 0 ? p.doc.beats[f.beat].focus : null)
  return focus ? cameraOn(focus.box, p.doc.page) : a.cam
}

type Scene = { frame: Frame; cam: Camera; look: Look; mark: Box | null }

interface Renderer {
  node: HTMLElement | SVGSVGElement
  size(width: number, height: number, dpr: number): void
  draw(scene: Scene): void
  /** Frees the pixels and caches while the board is off screen; the next size() brings them back. */
  release(): void
}

export function inkColour(look: Look, name: string): string {
  return Object.hasOwn(look.inks, name) ? look.inks[name] : look.inks.ink
}

const inkOf = (doc: InkDoc, look: Look, stroke: number) => inkColour(look, doc.elements[doc.strokes[stroke].el].ink)
const under = (doc: InkDoc, stroke: number) => doc.elements[doc.strokes[stroke].el].kind === 'highlight'

// Consecutive segments of a revealed centerline that share one width: the mask is stroked run by run, round-capped,
// each segment as wide as the larger reveal radius at its ends.
export function runs(tips: Tip[]): { width: number; points: Tip[] }[] {
  if (tips.length === 1) return [{ width: 2 * tips[0][2], points: [tips[0], tips[0]] }]
  const out: { width: number; points: Tip[] }[] = []
  for (let j = 0; j + 1 < tips.length; j++) {
    const width = 2 * Math.max(tips[j][2], tips[j + 1][2])
    const last = out.at(-1)
    if (last && last.width === width) last.points.push(tips[j + 1])
    else out.push({ width, points: [tips[j], tips[j + 1]] })
  }
  return out
}

const polyline = (points: number[][]) => points.map((p, k) => `${k ? 'L' : 'M'}${p[0]} ${p[1]}`).join('')

const grains = new Map<string, HTMLCanvasElement>()

// Deterministic grain, so chalk looks the same on every replay; made once per page load.
function grain(size: number, seed: number, alpha: number, density: number): HTMLCanvasElement {
  const key = `${size}/${seed}/${alpha}/${density}`
  const made = grains.get(key)
  if (made) return made
  const c = document.createElement('canvas')
  c.width = c.height = size
  const g = c.getContext('2d')!
  const img = g.createImageData(size, size)
  let s = seed
  const rand = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32)
  for (let i = 0; i < img.data.length; i += 4) {
    if (rand() > density) continue
    img.data[i + 3] = Math.round(255 * alpha * rand())
    img.data[i] = img.data[i + 1] = img.data[i + 2] = 255
  }
  g.putImageData(img, 0, 0)
  grains.set(key, c)
  return c
}

// The pen and the eraser in CSS px, whatever the zoom; the pen's tip at the origin.
const PEN = 'M0 0L6 -3.5L6 3.5ZM6 -4H32V4H6Z'
const ERASER = 'M-10 -6H10V6H-10Z'
const PEN_ANGLE = -34
let penPaths: { pen: Path2D; eraser: Path2D } | null = null

function drawPen(c: CanvasRenderingContext2D, look: Look, x: number, y: number, down: boolean, eraser: boolean, s: number) {
  penPaths ??= { pen: new Path2D(PEN), eraser: new Path2D(ERASER) }
  c.save()
  c.translate(x, y - (down ? 0 : 6))
  c.scale(1 / s, 1 / s)
  c.globalAlpha = 0.85
  c.fillStyle = look.pen
  if (!eraser) c.rotate((PEN_ANGLE * Math.PI) / 180)
  c.fill(eraser ? penPaths.eraser : penPaths.pen)
  c.restore()
}

function canvasRenderer(p: Plan, c2d: CanvasRenderingContext2D): Renderer {
  const { doc } = p
  const main = c2d.canvas
  const make = () => document.createElement('canvas')
  const ink = make(), scratch = make(), layerInk = make(), layerUnder = make()
  const ictx = ink.getContext('2d')!, sctx = scratch.getContext('2d')!
  const lctx = layerInk.getContext('2d')!, uctx = layerUnder.getContext('2d')!
  // Built on first use: a long board pays only for the strokes shown.
  const outlines: (Path2D | undefined)[] = new Array(doc.strokes.length)
  const ghostPaths: (Path2D | undefined)[] = new Array(doc.ghosts.length)
  const outline = (i: number) => (outlines[i] ??= new Path2D(doc.strokes[i].outline))
  const ghost = (g: number) => (ghostPaths[g] ??= new Path2D(doc.ghosts[g].outline))
  let chalk: CanvasPattern | null = null
  let dust: CanvasPattern | null = null
  const cache = new Settled()
  let width = 1, dpr = 1, res = 1, look: Look = LOOKS.light

  const fit = () => (width * dpr) / doc.page[0]

  function reset() {
    const w = Math.ceil(doc.page[0] * res)
    const h = Math.ceil(doc.page[1] * res)
    for (const [l, x] of [[layerInk, lctx], [layerUnder, uctx]] as const) {
      if (l.width !== w || l.height !== h) {
        l.width = w
        l.height = h
      } else {
        x.setTransform(1, 0, 0, 1, 0, 0)
        x.clearRect(0, 0, w, h)
      }
      x.setTransform(res, 0, 0, res, 0, 0)
    }
  }

  function paint(i: number) {
    const x = under(doc, i) ? uctx : lctx
    x.fillStyle = inkOf(doc, look, i)
    x.fill(outline(i))
  }

  function view(x: CanvasRenderingContext2D, cam: Camera) {
    const s = fit() * cam.z
    x.setTransform(s, 0, 0, s, -cam.x * s, -cam.y * s)
  }

  function clearScratch(cam: Camera) {
    sctx.setTransform(1, 0, 0, 1, 0, 0)
    sctx.globalCompositeOperation = 'source-over'
    sctx.clearRect(0, 0, scratch.width, scratch.height)
    view(sctx, cam)
  }

  function reveal(i: number, tips: Tip[], cam: Camera) {
    clearScratch(cam)
    sctx.lineCap = sctx.lineJoin = 'round'
    sctx.strokeStyle = '#000'
    for (const run of runs(tips)) {
      sctx.lineWidth = run.width
      sctx.stroke(new Path2D(polyline(run.points)))
    }
    sctx.globalCompositeOperation = 'source-in'
    sctx.fillStyle = inkOf(doc, look, i)
    sctx.fill(outline(i))
  }

  function wipe(strokes: number[], r: number, path: [number, number][], cam: Camera) {
    clearScratch(cam)
    for (const i of strokes) {
      sctx.fillStyle = inkOf(doc, look, i)
      sctx.fill(outline(i))
    }
    if (path.length) {
      sctx.globalCompositeOperation = 'destination-out'
      sctx.lineCap = sctx.lineJoin = 'round'
      sctx.lineWidth = 2 * r
      sctx.stroke(new Path2D(polyline(path.length === 1 ? [path[0], path[0]] : path)))
    }
  }

  function compose(f: Frame, cam: Camera, below: boolean) {
    const s = fit() * cam.z
    ictx.globalAlpha = below ? HIGHLIGHT_ALPHA : 1
    ictx.setTransform(s / res, 0, 0, s / res, -cam.x * s, -cam.y * s)
    ictx.drawImage(below ? layerUnder : layerInk, 0, 0)
    ictx.setTransform(1, 0, 0, 1, 0, 0)
    for (const d of f.drawing) {
      if (under(doc, d.stroke) !== below) continue
      reveal(d.stroke, d.tips, cam)
      ictx.drawImage(scratch, 0, 0)
    }
    for (const e of f.erasing) {
      const strokes = e.strokes.filter((i) => under(doc, i) === below)
      if (!strokes.length) continue
      wipe(strokes, e.r, e.path, cam)
      ictx.drawImage(scratch, 0, 0)
    }
    ictx.globalAlpha = 1
  }

  return {
    node: main,
    size(w, h, ratio) {
      width = w
      dpr = ratio
      for (const c of [main, ink, scratch]) {
        c.width = Math.max(1, Math.round(w * dpr))
        c.height = Math.max(1, Math.round(h * dpr))
      }
      cache.clear()
    },
    release() {
      for (const c of [main, ink, scratch, layerInk, layerUnder]) c.width = c.height = 0
      outlines.fill(undefined)
      cache.clear()
    },
    draw(scene) {
      const { frame: f, cam, mark } = scene
      look = scene.look
      // Settled strokes are cached at a resolution fit for the zoom, so moving the camera does not repaint them.
      res = Math.min(MAX_LAYER_PX / doc.page[0], fit() * Math.max(1, Math.ceil(cam.z)))
      cache.next(p, f, `${res}/${look.name}`, reset, paint)

      c2d.setTransform(1, 0, 0, 1, 0, 0)
      c2d.fillStyle = look.board
      c2d.fillRect(0, 0, main.width, main.height)
      view(c2d, cam)
      const s = fit() * cam.z
      if (look.chalk) {
        dust ??= c2d.createPattern(grain(256, 11, 0.05, 0.5), 'repeat')
        c2d.fillStyle = dust ?? look.board
        c2d.fillRect(0, 0, doc.page[0], doc.page[1])
      }
      c2d.fillStyle = look.inks.ink
      for (const g of f.ghosts) {
        c2d.globalAlpha = doc.ghosts[g].opacity
        c2d.fill(ghost(g))
      }
      c2d.globalAlpha = 1
      if (mark) {
        c2d.fillStyle = look.focus
        c2d.beginPath()
        c2d.roundRect(mark[0] - 8, mark[1] - 8, mark[2] + 16, mark[3] + 16, 12)
        c2d.fill()
      }

      ictx.setTransform(1, 0, 0, 1, 0, 0)
      ictx.globalCompositeOperation = 'source-over'
      ictx.clearRect(0, 0, ink.width, ink.height)
      compose(f, cam, true)
      compose(f, cam, false)
      if (look.chalk) {
        // The grain goes on the composed ink, not stroke by stroke, so overlaps and the reveal mask never show.
        chalk ??= ictx.createPattern(grain(128, 7, 0.55, 0.35), 'repeat')
        if (chalk) {
          chalk.setTransform(new DOMMatrix([s / 2, 0, 0, s / 2, -cam.x * s, -cam.y * s]))
          ictx.globalCompositeOperation = 'destination-out'
          ictx.fillStyle = chalk
          ictx.fillRect(0, 0, ink.width, ink.height)
          ictx.globalCompositeOperation = 'source-over'
        }
      }
      c2d.setTransform(1, 0, 0, 1, 0, 0)
      c2d.drawImage(ink, 0, 0)
      view(c2d, cam)
      if (f.pen) drawPen(c2d, look, f.pen.x, f.pen.y, f.pen.down, f.pen.eraser, cam.z * (width / doc.page[0]))
    },
  }
}

const SVG = 'http://www.w3.org/2000/svg'
let svgIds = 0

function svgRenderer(p: Plan): Renderer {
  const { doc } = p
  const id = `ink${++svgIds}`
  const el = <K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}, parent?: Element) => {
    const e = document.createElementNS(SVG, tag)
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v))
    parent?.appendChild(e)
    return e
  }
  const svg = el('svg', { role: 'img' })
  svg.style.display = 'block'
  const defs = el('defs', {}, svg)
  const filter = el('filter', { id: `${id}-chalk`, x: 0, y: 0, width: 1, height: 1 }, defs)
  el('feTurbulence', { type: 'fractalNoise', baseFrequency: 0.9, numOctaves: 2, seed: 7, result: 'n' }, filter)
  el('feColorMatrix', { in: 'n', type: 'matrix', values: '0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 -1.4 1.25', result: 'a' }, filter)
  el('feComposite', { in: 'SourceGraphic', in2: 'a', operator: 'in' }, filter)
  const reveal = el('mask', { id: `${id}-reveal`, maskUnits: 'userSpaceOnUse' }, defs)
  const sweep = el('mask', { id: `${id}-sweep`, maskUnits: 'userSpaceOnUse' }, defs)
  const board = el('rect', { x: -1e4, y: -1e4, width: 2e4, height: 2e4 }, svg)
  const ghostLayer = el('g', {}, svg)
  const focus = el('rect', { rx: 12 }, svg)
  const inkLayer = el('g', {}, svg)
  const underLayer = el('g', { opacity: HIGHLIGHT_ALPHA }, inkLayer)
  const overLayer = el('g', {}, inkLayer)
  const pen = el('g', {}, svg)
  const paths = new Map<number, SVGPathElement>()
  const masked = new Set<number>()
  const ghostPaths = new Map<number, SVGPathElement>()
  const cache = new Settled()
  let look: Look = LOOKS.light
  let width = 1

  const strokePath = (i: number) => {
    let e = paths.get(i)
    if (!e) {
      e = el('path', { d: doc.strokes[i].outline }, under(doc, i) ? underLayer : overLayer)
      paths.set(i, e)
    }
    e.setAttribute('fill', inkOf(doc, look, i))
    return e
  }

  function reset() {
    for (const e of paths.values()) e.remove()
    paths.clear()
  }

  function fill(m: SVGMaskElement, children: [string, Record<string, string | number>][]) {
    m.replaceChildren(...children.map(([tag, attrs]) => el(tag as 'path', attrs)))
  }

  return {
    node: svg,
    size(w, h) {
      width = w
      svg.setAttribute('width', String(w))
      svg.setAttribute('height', String(h))
    },
    release() {
      reset()
      cache.clear()
    },
    draw(scene) {
      const { frame: f, cam, mark } = scene
      look = scene.look
      svg.setAttribute('viewBox', `${cam.x} ${cam.y} ${doc.page[0] / cam.z} ${doc.page[1] / cam.z}`)
      board.setAttribute('fill', look.board)
      inkLayer.setAttribute('filter', look.chalk ? `url(#${id}-chalk)` : '')
      // strokes in motion are shown through a mask this frame only
      for (const i of masked) {
        const e = paths.get(i)
        if (e) {
          e.remove()
          paths.delete(i)
        }
      }
      masked.clear()
      cache.next(p, f, look.name, reset, (i) => strokePath(i).removeAttribute('mask'))
      const drawing = f.drawing[0]
      if (drawing) {
        strokePath(drawing.stroke).setAttribute('mask', `url(#${id}-reveal)`)
        masked.add(drawing.stroke)
        fill(reveal, runs(drawing.tips).map((r) => ['path', { d: polyline(r.points), fill: 'none', stroke: '#fff', 'stroke-width': r.width, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }]))
      }
      const erasing = f.erasing[0]
      if (erasing) {
        for (const i of erasing.strokes) {
          strokePath(i).setAttribute('mask', `url(#${id}-sweep)`)
          masked.add(i)
        }
        const path = erasing.path.length === 1 ? [erasing.path[0], erasing.path[0]] : erasing.path
        fill(sweep, [
          ['rect', { x: 0, y: 0, width: doc.page[0], height: doc.page[1], fill: '#fff' }],
          ...(path.length ? [['path', { d: polyline(path), fill: 'none', stroke: '#000', 'stroke-width': 2 * erasing.r, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }] as [string, Record<string, string | number>]] : []),
        ])
      }
      for (const [g, e] of ghostPaths) if (!f.ghosts.includes(g)) e.remove()
      for (const g of f.ghosts) {
        const e = ghostPaths.get(g) ?? el('path', { d: doc.ghosts[g].outline, opacity: doc.ghosts[g].opacity })
        ghostPaths.set(g, e)
        e.setAttribute('fill', look.inks.ink)
        if (!e.isConnected) ghostLayer.appendChild(e)
      }
      focus.setAttribute('display', mark ? 'inline' : 'none')
      if (mark) {
        for (const [k, v] of Object.entries({ x: mark[0] - 8, y: mark[1] - 8, width: mark[2] + 16, height: mark[3] + 16, fill: look.focus })) focus.setAttribute(k, String(v))
      }
      pen.replaceChildren()
      if (f.pen) {
        const s = doc.page[0] / (width * cam.z)
        const g = el('g', { transform: `translate(${f.pen.x} ${f.pen.y - (f.pen.down ? 0 : 6)}) scale(${s})`, fill: look.pen, opacity: 0.85 }, pen)
        el('path', { d: f.pen.eraser ? ERASER : PEN, transform: f.pen.eraser ? '' : `rotate(${PEN_ANGLE})` }, g)
      }
    },
  }
}

type Events = { beat: (n: number) => void; end: () => void; ask: (ref: string) => void; time: (ms: number) => void }

export type Player = {
  readonly doc: InkDoc
  readonly duration: number
  play(): void
  pause(): void
  /** A time in ms, or the start of a beat. */
  seek(to: number | { beat: number }): void
  rate(r: number): void
  /** The board at rest after beat n. */
  show(n: number): void
  /** Light up `id` or `id.mark`; null clears it. */
  highlight(ref: string | null): void
  theme(name: ThemeName): void
  /** Reduced motion: each beat shown at once, as show(n), and the camera left where the learner put it. */
  motion(reduced: boolean): void
  on<K extends keyof Events>(event: K, fn: Events[K]): () => void
  destroy(): void
}

export type PlayerOptions = { theme?: ThemeName; renderer?: 'canvas' | 'svg'; reducedMotion?: boolean; label?: string }

/** Plays a document (see readInk) in `host`. */
export function mount(host: HTMLElement, doc: InkDoc, opts: PlayerOptions = {}): Player {
  const p = plan(doc)
  const [W, H] = doc.page
  const box = document.createElement('div')
  box.style.cssText = `position:relative;width:100%;aspect-ratio:${W} / ${H};overflow:hidden;touch-action:pan-y;user-select:none`
  host.appendChild(box)
  const canvas = opts.renderer === 'svg' ? null : document.createElement('canvas')
  const c2d = canvas?.getContext('2d') ?? null
  const r = c2d ? canvasRenderer(p, c2d) : svgRenderer(p)
  r.node.style.width = r.node.style.height = '100%'
  r.node.setAttribute('role', 'img')
  r.node.setAttribute('aria-label', opts.label ?? doc.elements.find((e) => e.kind === 'title')?.alt ?? '')
  box.appendChild(r.node)

  const handlers: Partial<Record<keyof Events, Set<(...a: never[]) => void>>> = {}
  const emit = <K extends keyof Events>(k: K, ...a: Parameters<Events[K]>) => {
    for (const h of handlers[k] ?? []) (h as (...x: Parameters<Events[K]>) => void)(...a)
  }
  const total = duration(doc)
  let look = LOOKS[opts.theme ?? 'light']
  let reduced = opts.reducedMotion ?? false
  let t = opening(doc)
  let shown = t
  let speed = 1
  let playing = false
  let raf = 0
  let last = 0
  let width = 0
  let beat = beatAt(p, t)
  let marked: string | null = null
  let asked: string | null = null
  let cam: Camera = FIT
  let user: Camera | null = null
  let page = -1
  let asleep = false
  let partsKey = ''

  // A focusable button over each element and mark, so the keyboard can reach "ask about this"; taps go to the board.
  const parts = document.createElement('div')
  parts.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;transform-origin:0 0;pointer-events:none'
  box.appendChild(parts)
  const buttons: { el: number; node: HTMLButtonElement }[] = []
  doc.elements.forEach((e, i) => {
    if (ANNOTATIONS.has(e.kind)) return
    const add = (ref: string, b: Box, label: string) => {
      const node = document.createElement('button')
      node.type = 'button'
      node.className = 'ink-part'
      node.setAttribute('aria-label', label || ref)
      node.style.cssText = `position:absolute;left:${(b[0] / W) * 100}%;top:${(b[1] / H) * 100}%;width:${(b[2] / W) * 100}%;height:${(b[3] / H) * 100}%;background:none;border:0;padding:0;pointer-events:none`
      node.addEventListener('focus', () => player.highlight(ref))
      node.addEventListener('blur', () => asked !== ref && player.highlight(null))
      node.addEventListener('click', () => ask(ref))
      parts.appendChild(node)
      buttons.push({ el: i, node })
    }
    add(e.id, e.box, e.alt)
    for (const [m, b] of e.marks) add(`${e.id}.${m}`, b, markAlt(e.alt, m))
  })

  function ask(ref: string) {
    marked = asked = ref
    const at = resolve(p, ref, shown)
    if (width < NARROW && !reduced && at && !ANNOTATIONS.has(doc.elements[at.el].kind)) user = cameraOn(at.box, doc.page)
    emit('ask', ref)
    if (!playing) render()
  }

  function render(dt = 0) {
    const bi = beatAt(p, t)
    // Reduced motion shows the board after the beat playing: show(n), with no reveal and no pen.
    shown = reduced && bi >= 0 ? restAt(doc, bi) : t
    const f = frameAt(p, shown)
    if (reduced) f.pen = null
    const want = aim(p, f, { narrow: width < NARROW, playing, reduced, user, marked, cam })
    if (f.page !== page || !dt || reduced) cam = want
    else {
      const k = 1 - Math.exp(-dt / EASE_MS)
      cam = { x: cam.x + (want.x - cam.x) * k, y: cam.y + (want.y - cam.y) * k, z: cam.z + (want.z - cam.z) * k }
    }
    page = f.page
    if (!asleep) {
      const ref = marked ? resolve(p, marked, shown) : null
      const focusRef = bi >= 0 && t < doc.beats[bi].end ? doc.beats[bi].focus : undefined
      const focus = focusRef ? resolve(p, focusRef, shown) : null
      const mark = [ref, focus].find((x) => x && x.page === f.page)?.box ?? null
      r.draw({ frame: f, cam, look, mark })
      box.style.touchAction = cam.z > 1.01 ? 'none' : 'pan-y'
      parts.style.transform = `scale(${cam.z}) translate(${(-cam.x / W) * 100}%, ${(-cam.y / H) * 100}%)`
      const key = `${f.page}/${f.finished}/${f.sweepsStarted}`
      if (key !== partsKey) {
        partsKey = key
        for (const b of buttons) b.node.hidden = doc.elements[b.el].page !== f.page || !onBoard(p, b.el, shown)
      }
    }
    if (bi !== beat) {
      beat = bi
      if (bi >= 0) emit('beat', bi)
    }
    emit('time', t)
  }

  function resize() {
    width = box.clientWidth
    if (!asleep) r.size(width, box.clientHeight, window.devicePixelRatio || 1)
    render()
  }

  function tick(now: number) {
    const dt = Math.min(now - last, 100)
    last = now
    t = Math.min(total, t + dt * speed)
    render(dt)
    if (t >= total) {
      playing = false
      render()
      emit('end')
      return
    }
    raf = requestAnimationFrame(tick)
  }

  // Page coordinates of a point on the board.
  function toPage(e: PointerEvent): [number, number] {
    const rect = box.getBoundingClientRect()
    const s = (rect.width / W) * cam.z
    return [cam.x + (e.clientX - rect.left) / s, cam.y + (e.clientY - rect.top) / s]
  }

  const down = new Map<number, { x: number; y: number }>()
  let gesture: { cam: Camera; points: [number, number][]; moved: boolean } | null = null

  function start() {
    const pts = [...down.values()].map((q) => [q.x, q.y] as [number, number])
    gesture = { cam, points: pts, moved: gesture?.moved ?? false }
  }

  box.addEventListener('pointerdown', (e) => {
    if ((e.target as Element | null)?.closest?.('.ink-part')) return
    down.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (down.size === 1) gesture = null
    start()
  })
  box.addEventListener('pointermove', (e) => {
    if (!down.has(e.pointerId) || !gesture) return
    down.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const now = [...down.values()].map((q) => [q.x, q.y] as [number, number])
    const from = gesture.points
    if (now.length !== from.length) return
    const dist = (a: [number, number][]) => (a.length > 1 ? Math.hypot(a[0][0] - a[1][0], a[0][1] - a[1][1]) : 1)
    const mid = (a: [number, number][]) => [a.reduce((s, q) => s + q[0], 0) / a.length, a.reduce((s, q) => s + q[1], 0) / a.length]
    const [mx0, my0] = mid(from)
    const [mx1, my1] = mid(now)
    if (Math.hypot(mx1 - mx0, my1 - my0) > TAP_PX || Math.abs(dist(now) - dist(from)) > TAP_PX) gesture.moved = true
    if (!gesture.moved || (now.length === 1 && gesture.cam.z <= 1.01)) return
    const rect = box.getBoundingClientRect()
    const s0 = (rect.width / W) * gesture.cam.z
    const z = Math.min(PINCH_MAX, Math.max(1, (gesture.cam.z * dist(now)) / dist(from)))
    const s1 = (rect.width / W) * z
    // the page point under the first midpoint stays under the fingers
    const px = gesture.cam.x + (mx0 - rect.left) / s0
    const py = gesture.cam.y + (my0 - rect.top) / s0
    user = clampCamera({ x: px - (mx1 - rect.left) / s1, y: py - (my1 - rect.top) / s1, z }, doc.page)
    if (!playing) render()
    e.preventDefault()
  })
  const lift = (e: PointerEvent) => {
    if (!down.delete(e.pointerId)) return
    const g = gesture
    if (down.size) return start()
    gesture = null
    if (!g || g.moved || e.type === 'pointercancel') return
    const [x, y] = toPage(e)
    // the board on screen is the one at `shown`, which reduced motion holds at the end of the beat
    const ref = hit(p, page, x, y, shown)
    if (ref) return ask(ref)
    marked = asked = null
    user = null
    if (!playing) render()
  }
  box.addEventListener('pointerup', lift)
  box.addEventListener('pointercancel', lift)

  const resizing = new ResizeObserver(resize)
  resizing.observe(box)
  const seeing =
    typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver((entries) => {
          const off = !entries.at(-1)!.isIntersecting
          if (off === asleep) return
          asleep = off
          if (off) r.release()
          else resize()
        })
  seeing?.observe(box)

  const player: Player = {
    doc,
    duration: total,
    play() {
      if (playing) return
      if (t >= total) t = opening(doc)
      user = null
      playing = true
      last = performance.now()
      raf = requestAnimationFrame(tick)
    },
    pause() {
      playing = false
      cancelAnimationFrame(raf)
      render()
    },
    seek(to) {
      t = typeof to === 'number' ? Math.max(0, Math.min(total, to)) : (doc.beats[to.beat]?.start ?? opening(doc))
      render()
    },
    rate(x) {
      speed = x
    },
    show(n) {
      playing = false
      cancelAnimationFrame(raf)
      t = restAt(doc, n)
      render()
    },
    highlight(ref) {
      marked = ref
      if (!ref) user = asked = null
      if (!playing) render()
    },
    theme(name) {
      look = LOOKS[name]
      render()
    },
    motion(on) {
      reduced = on
      render()
    },
    on(event, fn) {
      const set = (handlers[event] ??= new Set())
      set.add(fn)
      return () => set.delete(fn)
    },
    destroy() {
      playing = false
      cancelAnimationFrame(raf)
      resizing.disconnect()
      seeing?.disconnect()
      r.release()
      box.remove()
    },
  }
  return player
}
