// A small board used by the ink and player tests.
const line = (x: number, y: number, t0: number, t1: number, el = 0) => ({
  el,
  outline: `M${x} ${y - 2}L${x + 100} ${y - 2}L${x + 100} ${y + 2}L${x} ${y + 2}Z`,
  path: [
    [x, y, t0, 0.5, 2],
    [x + 100, y, t1, 0.5, 2],
  ],
})

// Two elements on page 0, one on page 1: a preamble stroke, then beat 0 writes `eq`, beat 1 wipes it and turns the page.
export function doc2() {
  return {
    schema: 2,
    page: [1600, 1000],
    pages: 2,
    elements: [
      { id: 'title', kind: 'title', page: 0, box: [0, 0, 200, 40], ink: 'ink', alt: 'Waves' },
      { id: 'eq', kind: 'eq', page: 0, box: [0, 100, 300, 60], marks: { k: [150, 100, 50, 60] }, ink: 'accent', alt: 'a = \\mark{k}{\\frac{1}{2}} b', future: 1 },
      { id: 'more', kind: 'text', page: 1, box: [0, 0, 300, 60], ink: 'ink', alt: 'Next page' },
    ],
    strokes: [
      line(0, 20, 0, 100),
      { ...line(0, 120, 200, 400, 1), marks: ['k'] },
      { ...line(0, 140, 450, 600, 1), path: [[0, 140, 450, 0.5, 2, 99], [100, 140, 600, 0.5, 2, 99]] },
      line(0, 20, 2000, 2100, 2),
    ],
    preamble: [0],
    beats: [
      { say: 'An equation.', start: 100, end: 1000, draw: [1, 2], erase: [], focus: 'eq.k', page: 0 },
      {
        say: 'Wipe it, then turn the page.',
        start: 1000,
        end: 3000,
        draw: [3],
        erase: [{ start: 1200, t: 1400, r: 20, path: [[0, 130, 1200], [300, 130, 1400]], strokes: [1, 2] }],
        page: 0,
      },
    ],
    ghosts: [{ beat: 1, t: 1400, page: 0, opacity: 0.06, outline: 'M0 100L300 100L300 160Z' }],
    later: { unknown: true },
  }
}
