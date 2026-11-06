const TYPE_MS = 55
const ERASE_MS = 25
const HOLD_MS = 2200
const GAP_MS = 400

/** A placeholder that types out each title in turn; under reduced motion each title just replaces the last. */
export function typedPlaceholder(titles: string[], calm: boolean, show: (text: string) => void): () => void {
  let title = 0
  let length = 0
  let erasing = false
  let timer: ReturnType<typeof setTimeout>
  const tick = () => {
    if (calm) {
      show(titles[title])
      title = (title + 1) % titles.length
      timer = setTimeout(tick, HOLD_MS * 2)
      return
    }
    const chars = Array.from(titles[title])
    length += erasing ? -1 : 1
    show(chars.slice(0, length).join(''))
    if (!erasing && length === chars.length) {
      erasing = true
      timer = setTimeout(tick, HOLD_MS)
    } else if (erasing && length === 0) {
      erasing = false
      title = (title + 1) % titles.length
      timer = setTimeout(tick, GAP_MS)
    } else {
      timer = setTimeout(tick, erasing ? ERASE_MS : TYPE_MS)
    }
  }
  timer = setTimeout(tick, GAP_MS)
  return () => clearTimeout(timer)
}
