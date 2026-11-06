let plain: string | null = null

export function clearTabMark() {
  if (plain === null) return
  document.title = plain
  plain = null
  document.removeEventListener('visibilitychange', cameBack)
}

function cameBack() {
  if (!document.hidden) clearTabMark()
}

// only a hidden tab is marked: a learner looking at the page sees the turn end there
export function markTab(mark: string) {
  if (!document.hidden) return
  if (plain === null) {
    plain = document.title
    document.addEventListener('visibilitychange', cameBack)
  }
  document.title = `${mark} ${plain}`
}
