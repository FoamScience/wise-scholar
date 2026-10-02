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
