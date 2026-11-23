import assert from 'node:assert/strict'
import { test } from 'node:test'
import { INKS, frameAt, plan, readInk } from '../src/ink.ts'
import { FIT, LOOKS, aim, cameraOn, clampCamera, inkColour, mount, runs } from '../src/inkPlayer.ts'
import type { Aim } from '../src/inkPlayer.ts'
import { fakeDom } from './fakeDom.ts'
import type { FakeElement } from './fakeDom.ts'
import { doc2 } from './inkDoc.ts'

const PAGE: [number, number] = [1600, 1000]

test('the camera stays on the page and within its zoom', () => {
  assert.deepEqual(clampCamera({ x: -50, y: 900, z: 9 }, PAGE), { x: 0, y: 750, z: 4 })
  assert.deepEqual(clampCamera({ x: 10, y: 10, z: 0.5 }, PAGE), { x: 0, y: 0, z: 1 })
})

test('a camera on a box zooms to read it and follows the pen along a wide one', () => {
  const small = cameraOn([600, 400, 200, 60], PAGE)
  assert.equal(small.z, 3)
  assert.equal(small.x + 1600 / 3 / 2, 700)
  const wide = [0, 400, 1400, 100] as [number, number, number, number]
  const at = (tip: number) => cameraOn(wide, PAGE, tip).x
  assert.ok(at(200) < at(800) && at(800) < at(1200))
  assert.equal(at(-500), at(0))
})

test('the reveal mask is stroked in runs of one width, a lone point as a dot', () => {
  assert.deepEqual(runs([[0, 0, 2]]), [{ width: 4, points: [[0, 0, 2], [0, 0, 2]] }])
  assert.deepEqual(runs([[0, 0, 2], [1, 0, 2], [2, 0, 3], [3, 0, 3]]), [
    { width: 4, points: [[0, 0, 2], [1, 0, 2]] },
    { width: 6, points: [[1, 0, 2], [2, 0, 3], [3, 0, 3]] },
  ])
})

test('the camera follows the pen on a narrow screen only, never on its own under reduced motion', () => {
  const p = plan(readInk(doc2()))
  const f = frameAt(p, 300)
  const a: Aim = { narrow: true, playing: true, reduced: false, user: null, marked: null, cam: FIT }
  assert.deepEqual(aim(p, f, a), cameraOn(p.doc.elements[1].box, PAGE, 50))
  assert.deepEqual(aim(p, f, { ...a, narrow: false }), FIT)
  assert.deepEqual(aim(p, f, { ...a, reduced: true }), FIT)
  // between strokes it holds on the beat's focus
  assert.deepEqual(aim(p, frameAt(p, 150), a), cameraOn([150, 100, 50, 60], PAGE))
  const user = { x: 100, y: 100, z: 2 }
  assert.deepEqual(aim(p, f, { ...a, playing: false, user }), user)
  assert.deepEqual(aim(p, frameAt(p, 900), { ...a, playing: false, marked: 'eq.k' }), cameraOn([150, 100, 50, 60], PAGE))
  assert.deepEqual(aim(p, frameAt(p, 900), { ...a, playing: false, marked: 'eq.k', reduced: true }), FIT)
})

test('an ink named after a prototype key takes the plain ink colour', () => {
  for (const name of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) assert.equal(inkColour(LOOKS.dark, name), LOOKS.dark.inks.ink)
  assert.equal(inkColour(LOOKS.dark, 'accent'), LOOKS.dark.inks.accent)
  for (const look of Object.values(LOOKS)) assert.deepEqual(new Set(Object.keys(look.inks)), INKS)
})

const strokeEls = (host: FakeElement) => {
  const outlines = doc2().strokes.map((s) => s.outline)
  return host.all().filter((e) => e.tagName === 'PATH' && outlines.includes(e.getAttribute('d') ?? ''))
}
const strokeOf = (e: FakeElement) => doc2().strokes.findIndex((s) => s.outline === e.getAttribute('d'))

test('without a canvas context the board falls back to SVG, labelled as an image', () => {
  const { host } = fakeDom(800)
  const player = mount(host as unknown as HTMLElement, readInk(doc2()), { label: 'Handwritten board: Waves' })
  const svg = host.all().find((e) => e.tagName === 'SVG')!
  assert.equal(svg.getAttribute('role'), 'img')
  assert.equal(svg.getAttribute('aria-label'), 'Handwritten board: Waves')
  player.show(0)
  assert.deepEqual(strokeEls(host).map(strokeOf).sort(), [0, 1, 2])
  player.destroy()
  assert.equal(host.children.length, 0)
})

test('a stroke is filled with its own ink, else with its element ink', () => {
  const { host } = fakeDom(800)
  const d = doc2()
  const strokes = d.strokes as { ink?: unknown }[]
  strokes[1].ink = 'alert'
  strokes[2].ink = 'crimson'
  const player = mount(host as unknown as HTMLElement, readInk(d), { label: 'board' })
  player.show(0)
  const fill = new Map(strokeEls(host).map((e) => [strokeOf(e), e.getAttribute('fill')]))
  const look = Object.values(LOOKS).find((l) => l.inks.ink === fill.get(0))!
  assert.ok(look)
  assert.equal(fill.get(1), look.inks.alert)
  assert.equal(fill.get(2), look.inks.accent)
  player.destroy()
})

test('reduced motion shows the beat playing at once, and the board on screen is the one a tap hits', () => {
  const { host } = fakeDom(800)
  const player = mount(host as unknown as HTMLElement, readInk(doc2()), { reducedMotion: true })
  const asked: string[] = []
  player.on('ask', (ref) => asked.push(ref))
  player.seek(150)
  assert.deepEqual(strokeEls(host).map(strokeOf).sort(), [0, 1, 2])
  assert.ok(strokeEls(host).every((e) => !e.getAttribute('mask')))
  // page (20, 130) is on `eq`, written later in the beat; the board is 800 px wide, half the page
  const box = host.children[0]
  box.dispatch('pointerdown', { pointerId: 1, clientX: 10, clientY: 65 })
  box.dispatch('pointerup', { pointerId: 1, clientX: 10, clientY: 65 })
  assert.deepEqual(asked, ['eq'])
  player.motion(false)
  player.seek(300)
  assert.deepEqual(strokeEls(host).map((e) => [strokeOf(e), Boolean(e.getAttribute('mask'))]).sort(), [[0, false], [1, true]])
  box.dispatch('pointerdown', { pointerId: 2, clientX: 10, clientY: 72 })
  box.dispatch('pointerup', { pointerId: 2, clientX: 10, clientY: 72 })
  assert.deepEqual(asked, ['eq', 'eq'])
  player.seek(150)
  box.dispatch('pointerdown', { pointerId: 3, clientX: 10, clientY: 65 })
  box.dispatch('pointerup', { pointerId: 3, clientX: 10, clientY: 65 })
  assert.deepEqual(asked, ['eq', 'eq'])
  player.destroy()
})

test('each element and mark on the board is a keyboard button that asks about it', () => {
  const { host } = fakeDom(800)
  const player = mount(host as unknown as HTMLElement, readInk(doc2()))
  const asked: string[] = []
  player.on('ask', (ref) => asked.push(ref))
  const parts = () => host.all().filter((e) => e.className === 'ink-part')
  const label = (e: FakeElement) => e.getAttribute('aria-label')
  assert.deepEqual(parts().map(label), ['Waves', 'a = \\mark{k}{\\frac{1}{2}} b', '\\frac{1}{2}', 'Next page'])
  player.seek(150)
  assert.deepEqual(parts().filter((e) => !e.hidden).map(label), ['Waves'])
  player.show(0)
  assert.deepEqual(parts().filter((e) => !e.hidden).map(label), ['Waves', 'a = \\mark{k}{\\frac{1}{2}} b', '\\frac{1}{2}'])
  parts()[2].click()
  assert.deepEqual(asked, ['eq.k'])
  player.show(1)
  assert.deepEqual(parts().filter((e) => !e.hidden).map(label), ['Next page'])
  player.destroy()
})

test('on a narrow screen playback zooms in, and at rest the page fits', () => {
  const { host, frame } = fakeDom(390)
  const player = mount(host as unknown as HTMLElement, readInk(doc2()))
  const svg = host.all().find((e) => e.tagName === 'SVG')!
  const viewWidth = () => Number(svg.getAttribute('viewBox')!.split(' ')[2])
  assert.equal(viewWidth(), 1600)
  player.play()
  frame(performance.now() + 1e6)
  frame(performance.now() + 2e6)
  assert.ok(viewWidth() < 1600, `view ${viewWidth()}`)
  player.pause()
  assert.equal(viewWidth(), 1600)
  player.destroy()
})
