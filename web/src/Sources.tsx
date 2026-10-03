import { useRef, useState } from 'react'
import { api } from './api'

export type Source = { id: number; name: string; size: number; status: 'processing' | 'ready' | 'failed'; error: string | null; sections: number }

function mb(size: number): string {
  return size >= 1_000_000 ? `${(size / 1_000_000).toFixed(1)} MB` : `${Math.round(size / 1000)} kB`
}

/** The learner's own files for a course; processed in the background, the tutor reads them a section at a time. */
export function SourcesPanel(props: { courseId: number; sources: Source[]; onChange: (s: Source[]) => void; onError: (m: string) => void }) {
  const input = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)

  async function upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    setBusy(true)
    try {
      const res = await fetch(`/api/courses/${props.courseId}/sources`, { method: 'POST', body: form })
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
      props.onChange([...props.sources, (await res.json()) as Source])
    } catch (err) {
      props.onError((err as Error).message)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  function remove(source: Source) {
    api(`/api/sources/${source.id}/delete`, {}).then(
      () => props.onChange(props.sources.filter((s) => s.id !== source.id)),
      (err: Error) => props.onError(err.message),
    )
  }

  return (
    <div className="sources">
      <div className="label">Your sources</div>
      {props.sources.map((s) => (
        <div key={s.id} className="source-row" title={s.error ?? undefined}>
          <span className="grow">
            {s.name} <span className="muted">· {mb(s.size)}</span>
          </span>
          <span className={`chip${s.status === 'failed' ? ' warn' : ''}`}>
            {s.status === 'ready' ? `${s.sections} sections` : s.status === 'failed' ? 'failed' : 'processing…'}
          </span>
          <button type="button" className="link" aria-label={`Remove ${s.name}`} onClick={() => remove(s)}>
            ×
          </button>
        </div>
      ))}
      <input
        ref={input}
        type="file"
        accept=".pdf,.epub,.html,.htm,.md,.markdown,.txt,.rst,.py,.rs,.js,.ts,.tsx,.c,.cpp,.h,.hs,.go,.java,.kt,.rb,.sh,.toml,.yaml,.yml,.json,.csv,.tex"
        hidden
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
      />
      <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? 'Uploading…' : 'Add a file'}
      </button>
      <div className="small">A book, documentation or your notes. The tutor searches it and reads one section at a time.</div>
    </div>
  )
}
