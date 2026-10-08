import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { browserLocale } from './locale'
import ar from './locales/ar.json'
import en from './locales/en.json'
import fr from './locales/fr.json'

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation'
    resources: typeof en
  }
}

i18n.use(initReactI18next).init({
  resources: { en, fr, ar },
  lng: browserLocale(),
  fallbackLng: 'en',
  initAsync: false,
  interpolation: { escapeValue: false },
})

/** The page's language and direction follow the interface language from the first paint on. */
function applyToPage(language: string) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = language
  document.documentElement.dir = i18n.dir(language)
}
i18n.on('languageChanged', applyToPage)
applyToPage(i18n.language)

const untyped = i18n.t as (key: string, options: object) => string

/** A key built at run time (a tool name, a playbook id); the fallback covers the ones the dictionary lacks. */
export function lookup(key: string, fallback: string): string {
  return untyped(key, { defaultValue: fallback })
}

/** A server error detail in the interface language; details without a translation pass through. */
export function serverMessage(detail: string): string {
  return untyped(detail, { ns: 'server', keySeparator: false, nsSeparator: false, defaultValue: detail })
}

// Western digits in every language, so counts read the same as the numbers in the tutor's math.
export const percent = (p: number) => new Intl.NumberFormat(i18n.language, { style: 'percent', numberingSystem: 'latn' }).format(p)

/** The day of a server timestamp (UTC, `YYYY-MM-DD hh:mm:ss`) written the way the language writes dates. */
export const day = (stamp: string) =>
  new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeZone: 'UTC', numberingSystem: 'latn' }).format(new Date(stamp.slice(0, 10)))

export function number(n: number): string {
  return new Intl.NumberFormat(i18n.language, { numberingSystem: 'latn', maximumFractionDigits: 1 }).format(n)
}

export function moment(stamp: string): string {
  return new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short', numberingSystem: 'latn' }).format(new Date(stamp))
}

export function fileSize(bytes: number): string {
  const mega = bytes >= 1_000_000
  return new Intl.NumberFormat(i18n.language, {
    style: 'unit',
    unit: mega ? 'megabyte' : 'kilobyte',
    unitDisplay: 'short',
    maximumFractionDigits: mega ? 1 : 0,
    numberingSystem: 'latn',
  }).format(bytes / (mega ? 1_000_000 : 1000))
}

export default i18n
