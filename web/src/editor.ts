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
