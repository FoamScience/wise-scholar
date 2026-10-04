import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import Markdown from '../src/Md.tsx'
import { rehypePlugins, remarkPlugins } from '../src/markdown.ts'
import i18n from '../src/i18n.ts'
import { splitSentences } from '../src/text.ts'

// The interface language otherwise follows the machine's locale.
await i18n.changeLanguage('en')

const render = (text: string) =>
  renderToStaticMarkup(createElement(ReactMarkdown, { remarkPlugins, rehypePlugins }, text))

test('inline math between single dollars is typeset', () => {
  const html = render('The norm $\\lVert x \\rVert_2 = \\sqrt{x^\\top x}$ here.')
  assert.ok(html.includes('class="katex"'))
  assert.ok(!html.includes('$'))
})

test('display math between double dollars is typeset as a block', () => {
  const html = render('Solve:\n\n$$\n\\int_0^1 x^2 \\, dx = \\frac{1}{3}\n$$\n')
  assert.ok(html.includes('katex-display'))
  assert.ok(html.includes('<annotation encoding="application/x-tex">'))
})

test('dollars in code spans and escaped dollars stay text', () => {
  const html = render('Run `echo $HOME and $PATH`, then pay \\$5.')
  assert.ok(html.includes('<code>echo $HOME and $PATH</code>'))
  assert.ok(html.includes('pay $5'))
  assert.ok(!html.includes('katex'))
})

test('math inside a table cell and malformed math do not break rendering', () => {
  assert.ok(render('| a | b |\n|---|---|\n| $x^2$ | 1 |').includes('class="katex"'))
  assert.ok(render('$\\frac{1}{$').length > 0)
})

test('sentences split at terminal punctuation and keep it', () => {
  assert.deepEqual(splitSentences('Am Montag war er beim Arzt. Danach? Nein! Er blieb zu Hause…  Fertig.'), [
    'Am Montag war er beim Arzt.',
    'Danach?',
    'Nein!',
    'Er blieb zu Hause…',
    'Fertig.',
  ])
  assert.deepEqual(splitSentences('Um 3.5 Uhr'), ['Um 3.5 Uhr'])
})

test('fenced code in Haskell and Python gets syntax classes', () => {
  const haskell = render('```haskell\nmain :: IO ()\nmain = putStrLn "hi" -- greet\n```')
  assert.ok(haskell.includes('hljs-type') || haskell.includes('hljs-title'))
  assert.ok(haskell.includes('hljs-string') && haskell.includes('hljs-comment'))
  const python = render('```python\ndef f(x):\n    return x * 2\n```')
  assert.ok(python.includes('hljs-keyword') && python.includes('hljs-number'))
  assert.ok(!render('```\nplain\n```').includes('hljs-'))
})

test('a mermaid block becomes a diagram placeholder, not highlighted code', () => {
  const html = renderToStaticMarkup(createElement(Markdown, null, '```mermaid\nflowchart LR\n  A --> B\n```'))
  assert.ok(html.includes('class="mermaid"'))
  assert.ok(!html.includes('hljs'))
})

test('a correction shows removed and added words, and nothing for an identical text', async () => {
  const { Correction } = await import('../src/Diff.tsx')
  const html = renderToStaticMarkup(createElement(Correction, { attempt: 'Ich helfe den Mann.', corrected: 'Ich helfe dem Mann.' }))
  assert.ok(html.includes('<del>den</del>') && html.includes('<ins>dem</ins>'))
  const same = renderToStaticMarkup(createElement(Correction, { attempt: 'Gut.', corrected: 'Gut.' }))
  assert.ok(!same.includes('<del>') && same.includes('already matched'))
})

test('a figure embedded in prose renders as an image with its alt text', () => {
  const html = render('See ![a labelled cell](/api/figures/12.svg) above.')
  assert.ok(html.includes('<img') && html.includes('src="/api/figures/12.svg"') && html.includes('alt="a labelled cell"'))
})

test('a plot card renders its accessible container before the library loads', async () => {
  const { PlotCard } = await import('../src/PlotCard.tsx')
  const html = renderToStaticMarkup(createElement(PlotCard, { id: 3, title: 'Decay', data: { spec: { marks: [] }, alt: 'exp(-x) falling' } }))
  assert.ok(html.includes('aria-label="exp(-x) falling"') && html.includes('Decay'))
})
