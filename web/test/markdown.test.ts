import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import Markdown, { AnswerText, InlineMarkdown } from '../src/Md.tsx'
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

test('a paragraph that is only $$…$$ on one line is displayed too, other inline math is not', () => {
  const html = render('The type as a function:\n\n$$\\text{isBig} : \\mathbb{Z} \\to \\{0, 1\\}$$\n\nand inline $$a$$ here, or alone:\n\n$x$')
  assert.equal(html.match(/katex-display/g)?.length, 1)
  assert.match(html, /<p><span class="katex-display">/)
  assert.match(html, /inline <span class="katex">/)
  assert.match(html, /<p><span class="katex">/)
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

test('each block takes the direction most of its prose is written in, ignoring code and math', () => {
  const html = renderToStaticMarkup(
    createElement(
      Markdown,
      null,
      [
        'جرّب `print("hello world from python, a long line of code")` ثم $E = mc^2 + \\text{energy}$',
        'The word كتاب means book, and it costs $5 or $10.',
        '$$x^2 + y^2 = z^2$$',
        '```python\nprint(1)\n```',
      ].join('\n\n'),
    ),
  )
  assert.match(html, /<p dir="rtl">جرّب/)
  assert.match(html, /<p dir="ltr">The word/)
  assert.match(html, /<p><span class="katex/)
  assert.ok(html.includes('<pre>'))
})

test('a link to #part-id names a figure part and other links stay links', () => {
  const html = renderToStaticMarkup(createElement(Markdown, { children: 'The [left ventricle](#part-ventricle) pumps; see [docs](https://example.org).' }))
  assert.ok(html.includes('<span class="term" data-ref="ventricle" tabindex="0">left ventricle</span>'))
  assert.ok(html.includes('<a href="https://example.org">docs</a>'))
})

test('inline text renders math with no paragraph around it', () => {
  const html = renderToStaticMarkup(createElement(InlineMarkdown, { children: 'about $44.73^\\circ$ or `x`' }))
  assert.match(html, /^about <span class="katex">/)
  assert.ok(html.includes('<code>x</code>'))
  assert.ok(!html.includes('<p>'))
})

test('inline text is not read as blocks', () => {
  const inline = (text: string) => renderToStaticMarkup(createElement(InlineMarkdown, { children: text }))
  assert.equal(inline('1. Intro'), '1. Intro')
  assert.equal(inline('- x'), '- x')
  assert.equal(inline('# x'), '# x')
  assert.ok(inline('1. $x^2$').startsWith('1. <span class="katex">'))
})

test('a picked option renders as the tutor wrote it; a typed answer stays verbatim unless it holds math', () => {
  const answer = (text: string, picked?: boolean) => renderToStaticMarkup(createElement(AnswerText, { text, picked }))
  assert.ok(answer('It is at least about $44.73^\\circ$, and may be larger', true).includes('class="katex"'))
  assert.ok(answer('call `len(x)`', true).includes('<code>len(x)</code>'))
  assert.equal(answer('a*b*c and # not a heading'), '<span dir="auto">a*b*c and # not a heading</span>')
  assert.equal(answer('costs $5'), '<span dir="auto">costs $5</span>')
  assert.ok(answer('so $x^2$ grows').includes('class="katex"'))
})
