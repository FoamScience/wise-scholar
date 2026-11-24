import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Markdown from '../src/Md.tsx'
import { sentenceAt, splitWords, wordsOf } from '../src/wordStates.ts'

const of = (kind: string, text: string, lang = 'de', glossary: string[] = []) => splitWords(text, glossary, lang).filter((p) => p.kind === kind).map((p) => p.text)
const words = (text: string, lang?: string, glossary?: string[]) => of('word', text, lang, glossary)

test('a text is cut into words that keep their marks, hyphens and scripts, and nothing is lost', () => {
  assert.deepEqual(words("L'été, 3 arc-en-ciel!"), ['L', 'été', 'arc-en-ciel'])
  assert.deepEqual(words('ما مَعْنى هذا؟'), ['ما', 'مَعْنى', 'هذا'])
  const text = ' Sie geht (heute) ins Kino. '
  assert.equal(splitWords(text, [], 'de').map((p) => p.text).join(''), text)
})

test('a glossary phrase stays whole, and a glossary word inside a longer word is not marked', () => {
  const pieces = splitWords('Der Hausarzt geht ins Kino, ins Haus.', ['ins Kino', 'Haus'], 'de')
  assert.deepEqual(pieces.filter((p) => p.kind === 'gloss').map((p) => p.text), ['ins Kino', 'Haus'])
  assert.ok(pieces.some((p) => p.kind === 'word' && p.text === 'Hausarzt'))
})

test('an entry that stands alone nowhere in the reading is marked inside a longer word', () => {
  assert.deepEqual(of('gloss', 'Der Hausarzt kommt.', 'de', ['Haus']), ['Haus'])
  assert.deepEqual(words('Der Hausarzt kommt.', 'de', ['Haus']), ['Der', 'kommt'])
  const [sentence, whole] = ['Der Hausarzt kommt.', 'Der Hausarzt kommt. Das Haus ist alt.']
  assert.deepEqual(splitWords(sentence, ['Haus'], 'de', whole).filter((p) => p.kind === 'gloss'), [])
})

test('a glossary word that letters touch stays tappable in scripts that join or do not space words', () => {
  assert.deepEqual(of('gloss', '他在图书馆看书。', 'zh', ['图书馆']), ['图书馆'])
  assert.deepEqual(of('gloss', '私は図書館で本を読みます。', 'ja', ['図書館']), ['図書館'])
  assert.deepEqual(of('gloss', 'هذا كتاب. والكتاب جديد.', 'ar', ['كتاب']), ['كتاب', 'كتاب'])
})

test('an unspaced sentence is cut into words, also without a glossary', () => {
  const ja = words('私は図書館で本を読みます。', 'ja')
  assert.ok(ja.includes('図書館') && ja.includes('本') && ja.length >= 6, ja.join('|'))
  for (const [lang, text] of [['zh', '他在图书馆看书。'], ['ja', '私は図書館で本を読みます。'], ['th', 'ฉันอ่านหนังสือในห้องสมุด']]) {
    assert.ok(words(text, lang).length > 2, lang)
    assert.equal(splitWords(text, [], lang).map((p) => p.text).join(''), text)
    assert.deepEqual(wordsOf([text], lang), [...new Set(words(text, lang))])
  }
})

test('without a segmenter an unspaced clause is plain text, and its glossary words still open', () => {
  const { Segmenter } = Intl
  Object.defineProperty(Intl, 'Segmenter', { value: undefined, configurable: true, writable: true })
  try {
    // a tag no other test uses, as segmenters are kept per language
    assert.deepEqual(splitWords('他在图书馆看书。', ['图书馆'], 'zh-SG').map((p) => p.kind), ['rest', 'gloss', 'rest'])
    assert.deepEqual(words('Ja, gut.', 'zh-SG'), ['Ja', 'gut'])
  } finally {
    Object.defineProperty(Intl, 'Segmenter', { value: Segmenter, configurable: true, writable: true })
  }
})

test('the distinct words of some texts, and the sentence around an offset', () => {
  assert.deepEqual(wordsOf(['Ja, ja.', 'Ja nein'], 'de'), ['Ja', 'ja', 'nein'])
  const text = 'Er kommt. Er geht heute. Gut!'
  assert.equal(sentenceAt(text, text.indexOf('geht')), 'Er geht heute.')
  assert.equal(sentenceAt(text, 0), 'Er kommt.')
})

test('words of a Markdown line carry their sentence; quotes and code are left alone', () => {
  const Word = ({ word, sentence }: { word: string; sentence: string }) => createElement('b', { title: sentence }, word)
  const html = renderToStaticMarkup(createElement(Markdown, { words: { lang: 'de', as: Word }, children: '> You are in a café.\n\nGuten *Tag*. Was nehmen Sie? `x`' }))
  assert.match(html, /<b title="Guten Tag\.">Tag<\/b>/)
  assert.match(html, /<b title="Was nehmen Sie\?[^"]*">nehmen<\/b>/)
  assert.match(html, /You are in a café\./)
  assert.match(html, /<code>x<\/code>/)
})
