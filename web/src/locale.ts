export const LOCALES = { en: 'English', fr: 'Français', ar: 'العربية' } as const
export type Locale = keyof typeof LOCALES

const KEY = 'wise-scholar.locale'
const isLocale = (code: string | null | undefined): code is Locale => !!code && code in LOCALES

/** The language this browser last chose, else the first of its preferred languages the interface has. */
export function browserLocale(): Locale {
  try {
    const saved = localStorage.getItem(KEY)
    if (isLocale(saved)) return saved
  } catch {
    /* storage may be unavailable */
  }
  return navigator.languages.map((l) => l.split('-')[0].toLowerCase()).find(isLocale) ?? 'en'
}

export function rememberLocale(locale: Locale) {
  try {
    localStorage.setItem(KEY, locale)
  } catch {
    /* storage may be unavailable */
  }
}
