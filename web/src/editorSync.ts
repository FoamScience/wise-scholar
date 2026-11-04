import type { Completion } from './course'

/** The editor keeps lines joined by \n; a file saved with \r\n keeps its line endings. */
export const sameText = (a: string, b: string) => a.replace(/\r\n/g, '\n') === b.replace(/\r\n/g, '\n')
export const toDisk = (doc: string, saved: string) => (saved.includes('\r\n') ? doc.replace(/\n/g, '\r\n') : doc)

export type Offered = { label: string; insert: string; signature: string; doc: string }

/** What the editor offers for the code left of the cursor: `from` is the offset in that text where the insert goes. */
export function offered(before: string, completions: Completion[], explicit: boolean): { from: number; options: Offered[] } | null {
  const token = /[\w$.]*$/.exec(before)?.[0] ?? ''
  if (!token && !explicit) return null
  const dot = token.lastIndexOf('.')
  const from = before.length - token.length + dot + 1
  const options = completions.map((c) => {
    const name = c.label.replace(/^\./, '')
    const last = name.slice(name.lastIndexOf('.') + 1)
    return { label: name, insert: dot >= 0 || c.label.startsWith('.') ? last : name, signature: c.signature, doc: c.doc }
  })
  return options.length ? { from, options } : null
}
