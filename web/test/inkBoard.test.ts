import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import i18n from '../src/i18n.ts'
import { prefill, readInk } from '../src/ink.ts'
import { InkBoardCard } from '../src/InkBoard.tsx'
import Markdown from '../src/Md.tsx'
import { doc2 } from './inkDoc.ts'

await i18n.changeLanguage('en')

test('"ask about this" starts from the element or the mark it names', () => {
  const doc = readInk(doc2())
  const about = (what: string) => `About ${what}: `
  assert.equal(prefill(doc, 'eq', about), 'About $a = {\\frac{1}{2}} b$: ')
  assert.equal(prefill(doc, 'eq.k', about), 'About $\\frac{1}{2}$: ')
  assert.equal(prefill(doc, 'more', about), 'About Next page: ')
  assert.equal(prefill(doc, 'nothing', about), '')
})

test('a board block shows its controls and its parts to a screen reader, or says it cannot be shown', () => {
  const html = renderToStaticMarkup(createElement(InkBoardCard, { id: 7, caption: 'Waves', data: { script: '', doc: doc2() }, onAsk: () => {} }))
  assert.ok(html.includes('id="block-7"'))
  assert.ok(html.includes('Play on the board'))
  assert.ok(html.includes('Tap or click part of the board to ask about it.'))
  assert.ok(html.includes('<ul class="sr-only"><li dir="auto">Waves</li>'))
  const bad = renderToStaticMarkup(createElement(InkBoardCard, { id: 7, caption: '', data: { doc: { ...doc2(), schema: 9 } } }))
  assert.ok(bad.includes('This board cannot be shown in this version of the app.'))
})

test('a lesson link to a board part is a keyboard-reachable term naming it', () => {
  const html = renderToStaticMarkup(createElement(Markdown, null, 'See [the circle](#board-3-circle%20main.sum) and [the sum](#board-3-main.sum).'))
  assert.ok(html.includes('<span class="term" role="button" data-board="3" data-board-ref="circle main.sum" tabindex="0">the circle</span>'), html)
  assert.ok(html.includes('data-board-ref="main.sum"'))
})
