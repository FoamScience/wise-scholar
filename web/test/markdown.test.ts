import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import { rehypePlugins, remarkPlugins } from '../src/markdown.ts'

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
