import assert from 'node:assert/strict'
import test from 'node:test'
import i18n, { fileSize, percent, serverMessage } from '../src/i18n.ts'
import ar from '../src/locales/ar.json' with { type: 'json' }
import en from '../src/locales/en.json' with { type: 'json' }
import fr from '../src/locales/fr.json' with { type: 'json' }

type Tree = { [key: string]: string | Tree }
const FORMS = /_(zero|one|two|few|many|other)$/

function flatten(tree: Tree, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === 'string') out.set(prefix + key, value)
    else for (const [k, v] of flatten(value, `${prefix}${key}.`)) out.set(k, v)
  }
  return out
}

const placeholders = (text: string) => new Set(text.match(/\{\{\w+\}\}/g) ?? [])

/** The keys a language must define for the English ones: a plural key once per plural category of that language. */
function expected(lang: string): string[] {
  const forms = new Intl.PluralRules(lang).resolvedOptions().pluralCategories
  const bases = new Set([...flatten(en.translation).keys()].map((k) => k.replace(FORMS, FORMS.test(k) ? '_*' : '')))
  return [...bases].flatMap((k) => (k.endsWith('_*') ? forms.map((f) => k.replace('*', f)) : [k])).sort()
}

for (const [lang, dict] of Object.entries({ en, fr, ar })) {
  test(`${lang} defines exactly the English keys, in each of its plural forms`, () => {
    assert.deepEqual([...flatten(dict.translation).keys()].sort(), expected(lang))
  })

  test(`${lang} keeps the placeholders of the English text`, () => {
    const english = new Map<string, Set<string>>()
    for (const [key, text] of flatten(en.translation)) {
      const base = key.replace(FORMS, '')
      english.set(base, new Set([...(english.get(base) ?? []), ...placeholders(text)]))
    }
    for (const [key, text] of flatten(dict.translation)) {
      const wanted = english.get(key.replace(FORMS, '')) ?? new Set()
      const used = placeholders(text)
      // A plural form may spell its number out ("two reviews"); every other text needs each placeholder.
      const missing = FORMS.test(key) ? [] : [...wanted].filter((p) => !used.has(p))
      const extra = [...used].filter((p) => !wanted.has(p))
      assert.deepEqual([missing, extra], [[], []], `${lang} ${key}`)
    }
  })
}

test('fr and ar translate the same server messages', () => {
  assert.deepEqual(Object.keys(fr.server).sort(), Object.keys(ar.server).sort())
})

test('plurals, server messages and numbers follow the language', async () => {
  await i18n.changeLanguage('ar')
  assert.equal(i18n.t('today.reviews', { count: 0 }), 'لا مراجعات في دوراتك')
  assert.equal(i18n.t('today.reviews', { count: 1 }), 'مراجعة واحدة في دوراتك')
  assert.equal(i18n.t('today.reviews', { count: 2 }), 'مراجعتان في دوراتك')
  assert.equal(i18n.t('today.reviews', { count: 100 }), '100 مراجعة في دوراتك')
  assert.match(fileSize(1_500_000), /1\.5/)
  assert.equal(i18n.t('today.reviews', { count: 5 }), '5 مراجعات في دوراتك')
  assert.equal(i18n.t('today.reviews', { count: 11 }), '11 مراجعة في دوراتك')
  assert.equal(serverMessage('already answered'), ar.server['already answered'])
  assert.equal(serverMessage('speech worker crashed: exit 1'), 'speech worker crashed: exit 1')
  assert.match(percent(0.5), /50/)
  await i18n.changeLanguage('fr')
  assert.equal(i18n.t('profile.courses', { count: 1 }), '1 cours')
  assert.match(fileSize(1_500_000), /^1,5\sMo$/)
  assert.match(percent(0.5), /^50\s%$/)
  await i18n.changeLanguage('en')
  assert.equal(i18n.t('map.hints', { count: 1 }), '1 hint')
})
