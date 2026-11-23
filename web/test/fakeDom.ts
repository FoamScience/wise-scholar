// Just enough of a DOM for mount() in inkPlayer.ts under node: elements, attributes, events, observers, frames.
// A canvas has no 2d context here, so the player takes its SVG fallback.
type Listener = (e: Record<string, unknown>) => void

export class FakeElement {
  tagName: string
  attrs = new Map<string, string>()
  children: FakeElement[] = []
  parentNode: FakeElement | null = null
  style: Record<string, string> = {}
  listeners = new Map<string, Listener[]>()
  className = ''
  type = ''
  hidden = false
  clientWidth = 0
  clientHeight = 0

  constructor(tag: string) {
    this.tagName = tag
  }
  setAttribute(k: string, v: string) {
    this.attrs.set(k, String(v))
  }
  getAttribute(k: string) {
    return this.attrs.get(k) ?? null
  }
  removeAttribute(k: string) {
    this.attrs.delete(k)
  }
  appendChild(c: FakeElement) {
    c.remove()
    c.parentNode = this
    this.children.push(c)
    return c
  }
  replaceChildren(...cs: FakeElement[]) {
    for (const c of [...this.children]) c.remove()
    for (const c of cs) this.appendChild(c)
  }
  remove() {
    if (!this.parentNode) return
    this.parentNode.children = this.parentNode.children.filter((c) => c !== this)
    this.parentNode = null
  }
  get isConnected(): boolean {
    return this.parentNode ? this.parentNode.isConnected : this.tagName === 'ROOT'
  }
  closest(sel: string): FakeElement | null {
    if (sel.startsWith('.') && this.className.split(' ').includes(sel.slice(1))) return this
    return this.parentNode?.closest(sel) ?? null
  }
  getContext() {
    return null
  }
  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }
  }
  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn])
  }
  removeEventListener(type: string, fn: Listener) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((f) => f !== fn))
  }
  dispatch(type: string, e: Record<string, unknown> = {}) {
    for (const fn of this.listeners.get(type) ?? []) fn({ type, target: this, preventDefault() {}, ...e })
  }
  click() {
    this.dispatch('click')
  }
  /** Every element below this one, depth first. */
  all(): FakeElement[] {
    return this.children.flatMap((c) => [c, ...c.all()])
  }
}

/** Installs the fake globals, with boards laid out `width` CSS px wide; returns a host and the pending frames. */
export function fakeDom(width: number) {
  const root = new FakeElement('ROOT')
  const frames: ((now: number) => void)[] = []
  const make = (tag: string) => {
    const e = new FakeElement(tag.toUpperCase())
    e.clientWidth = width
    e.clientHeight = (width * 10) / 16
    return e
  }
  Object.assign(globalThis, {
    document: { createElement: make, createElementNS: (_ns: string, tag: string) => make(tag) },
    window: { devicePixelRatio: 1 },
    ResizeObserver: class {
      cb: () => void
      constructor(cb: () => void) {
        this.cb = cb
      }
      observe() {
        this.cb()
      }
      disconnect() {}
    },
    requestAnimationFrame: (cb: (now: number) => void) => frames.push(cb),
    cancelAnimationFrame: () => (frames.length = 0),
  })
  const host = root.appendChild(make('div'))
  /** Runs the next animation frame at `now` ms. */
  const frame = (now: number) => frames.shift()?.(now)
  return { host, frame }
}
