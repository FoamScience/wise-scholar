import type { CompletionSource } from '@codemirror/autocomplete'
import { indentWithTab } from '@codemirror/commands'
import { LanguageDescription, syntaxHighlighting } from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { Compartment, EditorState } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { classHighlighter } from '@lezer/highlight'
import { basicSetup } from 'codemirror'
import type { Completion } from './course'
import { offered } from './editorSync'

export type Editor = {
  text: () => string
  setText: (text: string) => void
  setReadOnly: (readOnly: boolean) => void
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
  '.cm-tooltip': tooltip,
  '.cm-tooltip.cm-completionInfo': tooltip,
  '.cm-completionDetail': { color: 'var(--code-comment)' },
  '.cm-tooltip-autocomplete ul li[aria-selected]': { backgroundColor: 'color-mix(in oklab, var(--code-ink) 22%, var(--code-bg))', color: 'var(--code-ink)' },
})

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
  onChange: () => void
}): Editor {
  const language = new Compartment()
  const readOnly = new Compartment()
  const hints = [{ autocomplete: source(props.completions) }]
  const locked = (on: boolean) => [EditorState.readOnly.of(on), EditorView.editable.of(!on)]
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
          if (update.docChanged) props.onChange()
        }),
        language.of([]),
        readOnly.of(locked(props.readOnly)),
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
    destroy: () => view.destroy(),
  }
}
