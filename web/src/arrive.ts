import { useLayoutEffect } from 'react'
import type { RefObject } from 'react'

const ARRIVING = '.block:not(.skeleton), .remark, .quiz-result'

/** Cards, remarks and quiz results added to the box rise in once; what is there when the box first shows for this key stays still. */
export function useArrivals(box: RefObject<HTMLElement | null>, key: unknown) {
  useLayoutEffect(() => {
    if (!box.current) return
    const watch = new MutationObserver((records) => {
      const removed = new Set(records.flatMap((r) => [...r.removedNodes]))
      // a finished reply swaps the streamed remark for the saved one the learner has already read
      const replaced = [...removed].some((n) => n instanceof HTMLElement && n.matches('.remark'))
      const targets = records
        .flatMap((r) => [...r.addedNodes])
        // a reorder removes and adds the same node: a move, not an arrival
        .filter((n): n is HTMLElement => n instanceof HTMLElement && !removed.has(n))
        .map((n) => (n.matches(ARRIVING) ? n : n.querySelector<HTMLElement>(ARRIVING)))
        .filter((n) => n !== null && !(replaced && n.matches('.remark')))
      if (!targets.length) return
      const root = getComputedStyle(document.documentElement)
      const duration = parseFloat(root.getPropertyValue('--motion'))
      if (!duration) return
      for (const target of targets)
        target!.animate([{ opacity: 0, translate: '0 8px' }, { opacity: 1, translate: '0 0' }], { duration, easing: root.getPropertyValue('--ease') })
    })
    watch.observe(box.current, { childList: true, subtree: true })
    return () => watch.disconnect()
  }, [box, key])
}
