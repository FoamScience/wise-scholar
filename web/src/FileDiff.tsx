import { useEffect, useRef, useState } from 'react'
import { openDiff } from './editorSync'
import type { DiffSummary } from './editorSync'

const loadEditor = () => import('./editor')

/** A file that is not edited here, read-only, with what changed from another text marked in it; plain text until the
 * editor is first up. */
export function FileDiff(props: {
  path: string
  from: string
  to: string
  onDiff: (summary: DiffSummary) => void
  onFailed: () => void
}) {
  const { path, from, to } = props
  const host = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    latest.current = props
  })

  useEffect(() => {
    if (!host.current) return
    return openDiff(host.current, { path, from, to }, loadEditor, {
      loaded: () => setLoaded(true),
      diff: (summary) => latest.current.onDiff(summary),
      failed: () => latest.current.onFailed(),
    })
  }, [path, from, to])

  return (
    <>
      {!loaded && <pre className="m-0 max-h-[420px] overflow-auto rounded-none">{to}</pre>}
      <div ref={host} className="code-editor" dir="ltr" />
    </>
  )
}
