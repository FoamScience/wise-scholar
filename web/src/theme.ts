import { useEffect, useState } from 'react'

/** A key that changes whenever the shown theme does: the toggle or the system setting. */
export function useTheme(): string {
  const current = () => `${document.documentElement.dataset.theme ?? ''}|${matchMedia('(prefers-color-scheme: dark)').matches}`
  const [theme, setTheme] = useState(() => (typeof document === 'undefined' ? '' : current()))
  useEffect(() => {
    const update = () => setTheme(current())
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const media = matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', update)
    return () => {
      observer.disconnect()
      media.removeEventListener('change', update)
    }
  }, [])
  return theme
}
