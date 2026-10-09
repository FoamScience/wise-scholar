import rough from 'roughjs'
import type { Options } from 'roughjs/bin/core'
import type { RoughSVG } from 'roughjs/bin/svg'

const SHAPES = new Set(['rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'path'])
// Art pack symbols, markers and clip shapes stay as drawn; only the tutor's own shapes get the hand-drawn look.
const KEPT = new Set(['defs', 'symbol', 'marker', 'clipPath', 'mask', 'pattern', 'linearGradient', 'radialGradient'])
const CARRIED = ['transform', 'opacity', 'fill-opacity', 'stroke-opacity', 'clip-path', 'mask', 'id']
// On the outline only, so the hachure fill keeps its own stroke.
const OUTLINE = ['marker-start', 'marker-mid', 'marker-end', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin']
const REFERENCE_WIDTH = 600

/** Redraws the figure's shapes with a sketchy stroke, in place; text and the art pack's icons are left alone. */
export function sketch(svg: SVGSVGElement) {
  const rc = rough.svg(svg)
  const width = svg.viewBox.baseVal.width || REFERENCE_WIDTH
  const scale = width / REFERENCE_WIDTH
  let seed = 1
  const walk = (parent: Element) => {
    for (const el of [...parent.children]) {
      if (KEPT.has(el.localName)) continue
      if (SHAPES.has(el.localName)) replace(el, rc, scale, seed++)
      else walk(el)
    }
  }
  walk(svg)
}

function inherited(el: Element, name: string): string | null {
  return el.closest(`[${name}]`)?.getAttribute(name) ?? null
}

function num(el: Element, name: string): number {
  return Number(el.getAttribute(name)) || 0
}

function points(el: Element): [number, number][] {
  const values = (el.getAttribute('points') ?? '').trim().split(/[\s,]+/).map(Number)
  const out: [number, number][] = []
  for (let i = 0; i + 1 < values.length; i += 2) out.push([values[i], values[i + 1]])
  return out
}

function replace(el: Element, rc: RoughSVG, scale: number, seed: number) {
  const fill = inherited(el, 'fill') ?? '#000'
  const stroke = inherited(el, 'stroke') ?? 'none'
  const options: Options = {
    seed,
    roughness: scale,
    bowing: 1,
    maxRandomnessOffset: 2 * scale,
    fill: fill === 'none' ? undefined : fill,
    fillStyle: 'hachure',
    hachureGap: 5 * scale,
    fillWeight: 0.6 * scale,
    stroke,
    strokeWidth: Number(inherited(el, 'stroke-width')) || scale,
  }
  let drawn: SVGGElement
  switch (el.localName) {
    case 'rect':
      drawn = rc.rectangle(num(el, 'x'), num(el, 'y'), num(el, 'width'), num(el, 'height'), options)
      break
    case 'circle':
      drawn = rc.circle(num(el, 'cx'), num(el, 'cy'), 2 * num(el, 'r'), options)
      break
    case 'ellipse':
      drawn = rc.ellipse(num(el, 'cx'), num(el, 'cy'), 2 * num(el, 'rx'), 2 * num(el, 'ry'), options)
      break
    case 'line':
      drawn = rc.line(num(el, 'x1'), num(el, 'y1'), num(el, 'x2'), num(el, 'y2'), options)
      break
    case 'polyline':
      drawn = rc.linearPath(points(el), options)
      break
    case 'polygon':
      drawn = rc.polygon(points(el), options)
      break
    default:
      drawn = rc.path(el.getAttribute('d') ?? '', options)
  }
  for (const name of CARRIED) {
    const value = el.getAttribute(name)
    if (value !== null) drawn.setAttribute(name, value)
  }
  const outline = drawn.lastElementChild
  if (outline)
    for (const name of OUTLINE) {
      const value = el.getAttribute(name)
      if (value !== null) outline.setAttribute(name, value)
    }
  el.replaceWith(drawn)
}
