import type { CompletionSource } from '@codemirror/autocomplete'
import { indentWithTab } from '@codemirror/commands'
import { LanguageDescription, syntaxHighlighting } from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { Compartment, EditorState } from '@codemirror/state'
import type { TransactionSpec } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { classHighlighter } from '@lezer/highlight'
import { basicSetup } from 'codemirror'
import type { Completion } from './course'
import { diffSummary, offered } from './editorSync'
import type { DiffSummary } from './editorSync'

export type Editor = {
  text: () => string
  setText: (text: string) => void
  setReadOnly: (readOnly: boolean) => void
  /** Show the text against this original; null shows it plain again. */
  setDiff: (original: string | null) => Promise<void>
  destroy: () => void
}

const tooltip = { backgroundColor: 'var(--code-bg)', color: 'var(--code-ink)', border: '1px solid var(--code-comment)' }

const theme = EditorView.theme({
  '&': { maxHeight: '420px', backgroundColor: 'var(--code-bg)', color: 'var(--code-ink)', fontSize: '0.875rem' },
  '&.cm-focused': { outline: '2px solid var(--color-accent)', outlineOffset: '-2px' },
  '.cm-scroller': { fontFamily: 'var(--mono)', overflow: 'auto' },
  '.cm-gutters': { backgroundColor: 'var(--code-bg)', color: 'var(--code-comment)', border: '0' },
  '.cm-content': { caretColor: 'var(--code-ink)' },
  '.cm-cursor': { borderInlineStartColor: 'var(--code-ink)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in oklab, var(--code-ink) 8%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in oklab, var(--code-ink) 8%, transparent)' },
  '.cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'color-mix(in oklab, var(--code-ink) 30%, transparent) !important',
  },
  '&.cm-merge-b .cm-changedLine': { backgroundColor: 'color-mix(in oklab, var(--code-added) 9%, transparent)' },
  '&.cm-merge-b .cm-changedText': { background: 'color-mix(in oklab, var(--code-added) 9%, transparent)' },
  '&.cm-merge-b .cm-changedLineGutter': { background: 'var(--code-added)' },
  '.cm-deletedChunk': { backgroundColor: 'color-mix(in oklab, var(--code-removed) 10%, transparent)' },
  '&.cm-merge-b .cm-deletedText': { background: 'color-mix(in oklab, var(--code-removed) 10%, transparent)' },
  '.cm-deletedLine del': { textDecoration: 'line-through', textDecorationColor: 'color-mix(in oklab, var(--code-removed) 60%, transparent)' },
  '.cm-changedLine .tok-comment, .cm-deletedLine .tok-comment': { color: 'var(--code-ink)' },
  '.cm-deletedLineGutter': { background: 'var(--code-removed)' },
  '.cm-tooltip': tooltip,
  '.cm-tooltip.cm-completionInfo': tooltip,
  '.cm-completionDetail': { color: 'var(--code-comment)' },
  '.cm-tooltip-autocomplete ul li[aria-selected]': { backgroundColor: 'color-mix(in oklab, var(--code-ink) 22%, var(--code-bg))', color: 'var(--code-ink)' },
})

const loadMerge = () => import('@codemirror/merge').then(({ unifiedMergeView, getChunks }) => ({ unifiedMergeView, getChunks }))

/** Turns one editor's diff against an original on and off; the merge code loads the first time a diff is shown, and
 * again after a load that failed. onDiff hears what the diff holds when it is shown and each time that changes. */
export function diffSwitch(
  view: { readonly state: EditorState; dispatch: (spec: TransactionSpec) => void },
  compartment: Compartment,
  onDiff: (summary: DiffSummary) => void,
  load: () => Promise<Pick<typeof import('@codemirror/merge'), 'unifiedMergeView' | 'getChunks'>> = loadMerge,
) {
  let wanted: string | null = null
  let shown: string | null = null
  let gone = false
  let merge: Awaited<ReturnType<typeof load>> | null = null
  let loading: ReturnType<typeof load> | null = null
  let told: DiffSummary | null = null
  const tell = () => {
    const summary = diffSummary(merge?.getChunks(view.state)?.chunks ?? [])
    if (summary !== told) onDiff((told = summary))
  }
  return {
    set: async (original: string | null) => {
      wanted = original
      if (original === shown) return
      if (original !== null && !merge) {
        try {
          merge = await (loading ??= load())
        } catch (err) {
          loading = null
          if (gone || wanted !== original) return
          throw err
        }
      }
      if (gone || wanted !== original || shown === original) return
      if (shown !== null) view.dispatch({ effects: compartment.reconfigure([]) })
      shown = original
      told = null
      if (original === null || !merge) return
      view.dispatch({ effects: compartment.reconfigure(merge.unifiedMergeView({ original, mergeControls: false })) })
      tell()
    },
    changed: () => {
      if (shown !== null) tell()
    },
    stop: () => {
      gone = true
    },
  }
}

function source(completions: Completion[]): CompletionSource {
  return (context) => {
    const line = context.state.doc.lineAt(context.pos)
    const match = offered(line.text.slice(0, context.pos - line.from), completions, context.explicit)
    if (!match) return null
    return {
      from: line.from + match.from,
      validFor: /^[\w$]*$/,
      options: match.options.map((o) => ({
        label: o.insert,
        displayLabel: o.label,
        detail: o.signature || undefined,
        info: o.doc || undefined,
        boost: 99,
      })),
    }
  }
}

export function createEditor(props: {
  parent: HTMLElement
  text: string
  path: string
  label: string
  completions: Completion[]
  readOnly: boolean
  /** Reachable with Tab while read-only, for a view that is only read. */
  focusable?: boolean
  onChange: () => void
  onDiff?: (summary: DiffSummary) => void
}): Editor {
  const language = new Compartment()
  const readOnly = new Compartment()
  const diff = new Compartment()
  const hints = [{ autocomplete: source(props.completions) }]
  const locked = (on: boolean) => [EditorState.readOnly.of(on), EditorView.editable.of(!on)]
  const diffs = diffSwitch({ get state() { return view.state }, dispatch: (spec) => view.dispatch(spec) }, diff, (summary) => props.onDiff?.(summary))
  const view = new EditorView({
    parent: props.parent,
    state: EditorState.create({
      doc: props.text,
      extensions: [
        basicSetup,
        theme,
        EditorState.languageData.of(() => hints),
        keymap.of([indentWithTab]),
        syntaxHighlighting(classHighlighter),
        EditorView.contentAttributes.of({ 'aria-label': props.label, dir: 'ltr' }),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return
          props.onChange()
          diffs.changed()
        }),
        language.of([]),
        readOnly.of(locked(props.readOnly)),
        diff.of([]),
        props.focusable ? EditorView.contentAttributes.of({ tabindex: '0' }) : [],
      ],
    }),
  })
  LanguageDescription.matchFilename(languages, props.path)
    ?.load()
    .then((support) => view.dispatch({ effects: language.reconfigure(support) }))
    .catch(() => {})
  return {
    text: () => view.state.doc.toString(),
    setText: (text) => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } }),
    setReadOnly: (on) => view.dispatch({ effects: readOnly.reconfigure(locked(on)) }),
    setDiff: diffs.set,
    destroy: () => {
      diffs.stop()
      view.destroy()
    },
  }
}
