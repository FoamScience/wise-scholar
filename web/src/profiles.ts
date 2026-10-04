import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { Locale } from './locale'

export type Profile = { id: number; name: string; courses: number; locale: Locale }

const KEY = 'wise-scholar.profile'

function remembered(): number | null {
  try {
    return Number(localStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}

/** The profiles on this install and the one this browser has selected. */
export function useProfiles() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null)
  const [selected, setSelected] = useState<number | null>(remembered)

  const reload = useCallback(() => api<Profile[]>('/api/profiles').then(setProfiles, () => setProfiles([])), [])
  useEffect(() => {
    reload()
  }, [reload])

  const select = useCallback((id: number) => {
    try {
      localStorage.setItem(KEY, String(id))
    } catch {
      // The choice then lasts only until the page reloads.
    }
    setSelected(id)
  }, [])

  const current = profiles?.find((p) => p.id === selected) ?? profiles?.[0] ?? null
  return { profiles, current, select, reload }
}
