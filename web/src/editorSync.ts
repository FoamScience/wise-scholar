import type { Completion } from './course'
import type { createEditor } from './editor'

/** The editor keeps lines joined by \n; a file saved with \r\n keeps its line endings. */
export const sameText = (a: string, b: string) => a.replace(/\r\n/g, '\n') === b.replace(/\r\n/g, '\n')
export const toDisk = (doc: string, saved: string) => (saved.includes('\r\n') ? doc.replace(/\n/g, '\r\n') : doc)

export type DiffSummary = 'same' | 'added' | 'removed' | 'both'

/** What a diff holds: no change, only text the original lacked, only original text that is gone, or both. */
export function diffSummary(chunks: readonly { fromA: number; toA: number; fromB: number; toB: number }[]): DiffSummary {
  const removed = chunks.some((c) => c.fromA < c.toA)
  const added = chunks.some((c) => c.fromB < c.toB)
  return removed && added ? 'both' : removed ? 'removed' : added ? 'added' : 'same'
}

/** The legend under a starter diff names only the marks it shows. */
export const LEGEND = { same: 'exercise.noChanges', added: 'exercise.changesAdded', removed: 'exercise.changesRemoved', both: 'exercise.changesLegend' } as const

type EditorModule = { createEditor: (props: Parameters<typeof createEditor>[0]) => { setDiff: (original: string | null) => Promise<void>; destroy: () => void } }

/** Loads the editor into host as a read-only, focusable view of `to` marked with its changes from `from`; returns what
 * closes it. failed hears an editor or diff that could not be loaded while the view is still open. */
export function openDiff(
  host: HTMLElement,
  file: { path: string; from: string; to: string },
  load: () => Promise<EditorModule>,
  on: { loaded: () => void; diff: (summary: DiffSummary) => void; failed: () => void },
): () => void {
  let gone = false
  let editor: ReturnType<EditorModule['createEditor']> | undefined
  load()
    .then(({ createEditor }) => {
      if (gone) return
      editor = createEditor({
        parent: host, text: file.to, path: file.path, label: file.path, completions: [], readOnly: true, focusable: true,
        onChange: () => {}, onDiff: on.diff,
      })
      on.loaded()
      return editor.setDiff(file.from)
    })
    .catch(() => {
      if (!gone) on.failed()
    })
  return () => {
    gone = true
    editor?.destroy()
  }
}

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
