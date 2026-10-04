/** Split text into pieces, flagging the ones that are in `needles`. */
export function splitBy(text: string, needles: string[]): { text: string; hit: boolean }[] {
  const found = needles.filter(Boolean).sort((a, b) => b.length - a.length)
  if (found.length === 0) return [{ text, hit: false }]
  const pattern = new RegExp(`(${found.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`)
  return text
    .split(pattern)
    .filter(Boolean)
    .map((piece) => ({ text: piece, hit: found.includes(piece) }))
}

/** Split a paragraph into sentences at ., !, ? followed by whitespace; abbreviations are not handled. */
export function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?…])\s+(?=\S)/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** The direction most letters of a text are written in; undefined without letters. */
export function textDirection(text: string): 'rtl' | 'ltr' | undefined {
  const letters = text.match(/\p{L}/gu)?.length ?? 0
  const rtl = text.match(/[\p{Script=Arabic}\p{Script=Hebrew}]/gu)?.length ?? 0
  if (letters === 0) return undefined
  return rtl * 2 > letters ? 'rtl' : 'ltr'
}
