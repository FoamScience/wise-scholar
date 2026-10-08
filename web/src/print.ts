/** The print stylesheet shared by the book and the hand-outs: page size, margins, running head and page numbers. */
export function pageStyle(topic: string): string {
  const css = getComputedStyle(document.documentElement)
  const text = `font-family: ${css.getPropertyValue('--mono')}; font-size: 8pt; color: ${css.getPropertyValue('--muted')};`
  // A CSS string: anything outside letters, digits and spaces goes in as a hex escape.
  const quoted = `"${topic.replace(/[^\p{L}\p{N} ]/gu, (c) => `\\${c.codePointAt(0)!.toString(16)} `)}"`
  return `@page { background: ${css.getPropertyValue('--ground')}; @top-center { content: ${quoted}; ${text} } @bottom-center { content: counter(page); ${text} } }
@page :first { margin: 0; @top-center { content: none } @bottom-center { content: none } }`
}
