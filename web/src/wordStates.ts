import type { Element, ElementContent, Root } from 'hast'
import { useEffect, useSyncExternalStore } from 'react'
import { api } from './api'
import { splitSentences } from './text'

export type WordState = 'new' | 'seen' | 'learning' | 'known'
export type Piece = { text: string; kind: 'word' | 'gloss' | 'rest' }

const LETTER = '\\p{L}\\p{M}'
const WORD = new RegExp(`\\p{L}[${LETTER}]*(?:-\\p{L}[${LETTER}]*)*`, 'gu')

// scripts written without spaces between words: their words come from the browser's dictionary
const UNSPACED = /[\p{scx=Han}\p{scx=Hiragana}\p{scx=Katakana}\p{scx=Thai}\p{scx=Lao}\p{scx=Khmer}\p{scx=Myanmar}]/u
// scripts that write no prefix or particle onto a word without it being another word
const ALPHABET = /^[\p{Script=Latin}\p{Script=Greek}\p{Script=Cyrillic}\p{M}\p{P}\p{Zs}]+$/u

const segmenters = new Map<string, Intl.Segmenter | null>()

function segmenter(lang: string): Intl.Segmenter | null {
  let found = segmenters.get(lang)
  if (found === undefined) {
    try {
      found = new Intl.Segmenter(lang || undefined, { granularity: 'word' })
    } catch {
      // no segmenter in this browser, or no such language
      found = null
    }
    segmenters.set(lang, found)
  }
  return found
}

type Span = { start: number; end: number }

/** Where the words of a text stand. Without a segmenter an unspaced clause has none, as it is no one word. */
function wordSpans(text: string, lang: string): Span[] {
  return [...text.matchAll(WORD)].flatMap((match) => {
    const { index } = match
    if (!UNSPACED.test(match[0])) return [{ start: index, end: index + match[0].length }]
    return [...(segmenter(lang)?.segment(match[0]) ?? [])]
      .filter((s) => s.isWordLike)
      .map((s) => ({ start: index + s.index, end: index + s.index + s.segment.length }))
  })
}

/** Where the glossary entries stand: anywhere the letters do, except that an entry in an alphabet that stands alone
 * somewhere in the whole reading is not marked inside a longer word. */
function glossSpans(text: string, glossary: string[], whole: string): Span[] {
  const entries = glossary
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
    .map((entry) => {
      const literal = entry.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const alone = `(?<![${LETTER}])${literal}(?![${LETTER}])`
      return ALPHABET.test(entry) && new RegExp(alone, 'u').test(whole) ? alone : literal
    })
  if (!entries.length) return []
  return [...text.matchAll(new RegExp(entries.join('|'), 'gu'))].map((m) => ({ start: m.index, end: m.index + m[0].length }))
}

/** A text cut into its words, the given glossary entries (which may be phrases) and what stands between them, such as
 * the rest of a word an entry is part of. whole is the reading the text is a sentence of. */
export function splitWords(text: string, glossary: string[], lang: string, whole = text): Piece[] {
  const glosses = glossSpans(text, glossary, whole)
  const words = wordSpans(text, lang).filter((w) => !glosses.some((g) => g.start < w.end && w.start < g.end))
  const spans = [...glosses.map((s) => ({ ...s, kind: 'gloss' as const })), ...words.map((s) => ({ ...s, kind: 'word' as const }))].sort((a, b) => a.start - b.start)
  const pieces: Piece[] = []
  let at = 0
  for (const { start, end, kind } of spans) {
    if (start > at) pieces.push({ text: text.slice(at, start), kind: 'rest' })
    pieces.push({ text: text.slice(start, end), kind })
    at = end
  }
  if (at < text.length) pieces.push({ text: text.slice(at), kind: 'rest' })
  return pieces
}

/** The distinct words of some texts. */
export function wordsOf(texts: string[], lang: string): string[] {
  return [...new Set(texts.flatMap((text) => wordSpans(text, lang).map((w) => text.slice(w.start, w.end))))]
}

/** The sentence of a text that holds the character at an offset. */
export function sentenceAt(text: string, offset: number): string {
  let end = 0
  for (const sentence of splitSentences(text)) {
    end = text.indexOf(sentence, end) + sentence.length
    if (offset < end) return sentence
  }
  return text.trim()
}

const SKIPPED = new Set(['code', 'pre', 'a', 'blockquote'])
const BLOCKS = new Set(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th'])

function textOf(node: ElementContent): string {
  if (node.type === 'text') return node.value
  return node.type === 'element' ? node.children.map(textOf).join('') : ''
}

/** Wraps each word of a Markdown text in a `tap-word` element that carries its sentence; quotes, code and links stay. */
export function rehypeWords({ lang }: { lang: string }) {
  return (tree: Root) => {
    const wrap = (parent: Element | Root, block: { text: string; at: number } | null) => {
      const children: ElementContent[] = []
      for (const child of parent.children as ElementContent[]) {
        if (child.type === 'element' && BLOCKS.has(child.tagName)) {
          if (block) block.at += textOf(child).length
          wrap(child, { text: textOf(child), at: 0 })
        }
        else if (child.type === 'element' && !SKIPPED.has(child.tagName)) wrap(child, block)
        else if (child.type === 'text' && block) {
          for (const piece of splitWords(child.value, [], lang)) {
            const text: ElementContent = { type: 'text', value: piece.text }
            children.push(
              piece.kind === 'word'
                ? { type: 'element', tagName: 'tap-word', properties: { word: piece.text, sentence: sentenceAt(block.text, block.at) }, children: [text] }
                : text,
            )
            block.at += piece.text.length
          }
          continue
        } else if (block) block.at += textOf(child).length
        children.push(child)
      }
      parent.children = children
    }
    wrap(tree, null)
  }
}

type Store = { states: Record<string, WordState>; asked: Set<string>; listeners: Set<() => void> }
const stores = new Map<number, Store>()
const NONE: Record<string, WordState> = {}

function storeOf(courseId: number): Store {
  let store = stores.get(courseId)
  if (!store) stores.set(courseId, (store = { states: NONE, asked: new Set(), listeners: new Set() }))
  return store
}

// the server takes at most 3000 words a call
const BATCH = 3000

async function load(courseId: number, words: string[]) {
  const store = storeOf(courseId)
  for (let i = 0; i < words.length; i += BATCH) {
    const batch = words.slice(i, i + BATCH)
    try {
      const states = await api<Record<string, WordState>>(`/api/courses/${courseId}/words/states`, { words: batch })
      store.states = { ...store.states, ...states }
    } catch {
      // uncoloured words can still be tapped; the next text that holds them asks again
      for (const w of batch) if (!(w in store.states)) store.asked.delete(w)
    }
    for (const listener of store.listeners) listener()
  }
}

/** Reads every word's state again: a word saved or known changes its other forms too. */
export function refreshWords(courseId: number) {
  return load(courseId, [...storeOf(courseId).asked])
}

/** How well the learner knows the words of some texts, shared by every text of the course on the page. */
export function useWordStates(courseId: number | null, texts: string[], lang: string): Record<string, WordState> {
  const joined = texts.join('\n')
  useEffect(() => {
    if (courseId === null) return
    const store = storeOf(courseId)
    const missing = wordsOf([joined], lang).filter((w) => !store.asked.has(w))
    if (!missing.length) return
    for (const w of missing) store.asked.add(w)
    void load(courseId, missing)
  }, [courseId, joined, lang])
  return useSyncExternalStore(
    (listener) => {
      if (courseId === null) return () => {}
      const { listeners } = storeOf(courseId)
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => (courseId === null ? NONE : storeOf(courseId).states),
  )
}
