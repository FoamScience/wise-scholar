import { useEffect, useState } from 'react'
import { useSuggestions } from './Explore'
import { typedPlaceholder } from './typing'

/** What the new-course field shows: the learner's suggested courses, or the resting text without any or once they type. */
export function useSuggestedPlaceholder(profile: number, enabled: boolean, typing: boolean, resting: string): string {
  const { state } = useSuggestions(profile, enabled)
  const titles = (state?.suggestions ?? []).map((s) => s.title).join('\n')
  const [shown, setShown] = useState('')
  useEffect(() => {
    setShown('')
    if (!titles || typing) return
    return typedPlaceholder(titles.split('\n'), matchMedia('(prefers-reduced-motion: reduce)').matches, setShown)
  }, [titles, typing])
  return titles && !typing ? shown : resting
}
