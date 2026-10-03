import { useEffect, useRef, useState } from 'react'

let seq = 0

/** The app's palette as mermaid theme variables, read live so a theme toggle re-colours diagrams. */
function themeVariables() {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return {
    background: v('--panel'),
    primaryColor: v('--teal-tint'),
    primaryTextColor: v('--ink'),
    primaryBorderColor: v('--teal'),
    secondaryColor: v('--amber-tint'),
    secondaryTextColor: v('--ink'),
    secondaryBorderColor: v('--amber'),
    tertiaryColor: v('--ground'),
    tertiaryTextColor: v('--ink'),
    tertiaryBorderColor: v('--line-strong'),
    lineColor: v('--line-strong'),
    textColor: v('--ink'),
    mainBkg: v('--teal-tint'),
    nodeBorder: v('--teal'),
    clusterBkg: v('--ground'),
    clusterBorder: v('--line'),
    edgeLabelBackground: v('--panel'),
    noteBkgColor: v('--amber-tint'),
    noteTextColor: v('--ink'),
    noteBorderColor: v('--amber-line'),
    fontFamily: v('--sans'),
  }
}

/** A key that changes whenever the shown theme does: the toggle or the system setting. */
function useTheme(): string {
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

export default function Mermaid({ code }: { code: string }) {
  const box = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const theme = useTheme()

  useEffect(() => {
    let live = true
    import('mermaid').then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', themeVariables: themeVariables() })
      try {
        const { svg } = await mermaid.render(`mmd-${++seq}`, code)
        if (!live || !box.current) return
        box.current.innerHTML = svg
        setError(null)
      } catch (err) {
        if (live) setError((err as Error).message)
      }
    })
    return () => {
      live = false
    }
  }, [code, theme])

  if (error)
    return (
      <div className="mermaid-error">
        <pre>{code}</pre>
        <div className="error">Diagram did not render: {error}</div>
      </div>
    )
  return <div ref={box} className="mermaid" />
}
