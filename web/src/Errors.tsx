import { useEffect, useState } from 'react'
import { api } from './api'
import Markdown from './Md'

type Entry = {
  id: number
  topic: string
  kind: 'quiz' | 'writing'
  prompt: string
  said: string
  correct: string
  explanation: string
  note: string
  pinned: number
  resolved: number
  created: string
}

/** The learner's own confident misses and corrected texts, with a note in their words; open ones lead the reviews. */
export function ErrorsPage({ profile }: { profile: number }) {
  const [entries, setEntries] = useState<Entry[] | null>(null)
  const [showResolved, setShowResolved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Entry[]>(`/api/errors?profile=${profile}`).then(setEntries, (e: Error) => setError(e.message))
  }, [profile])

  function patch(id: number, body: { note?: string; pinned?: boolean; resolved?: boolean }) {
    api<Entry>(`/api/errors/${id}`, body).then(
      (updated) => setEntries((all) => all && all.map((e) => (e.id === id ? updated : e))),
      (e: Error) => setError(e.message),
    )
  }

  if (!entries) return <main className="home">{error && <div className="error">{error}</div>}</main>
  const shown = entries.filter((e) => showResolved || !e.resolved)
  const open = entries.filter((e) => !e.resolved).length

  return (
    <main className="home">
      <div className="row">
        <h1 className="grow">Error notebook · {open} open</h1>
        <label className="small">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> show resolved
        </label>
      </div>
      {error && <div className="error">{error}</div>}
      {shown.length === 0 && <div className="muted">Nothing here. Confident misses and corrected texts land here on their own.</div>}
      {shown.map((e) => (
        <section key={e.id} className={`block entry${e.resolved ? ' resolved' : ''}`}>
          <div className="label">
            {e.kind === 'writing' ? 'Corrected text' : 'Confident miss'} · {e.topic} · {e.created.slice(0, 10)}
            {e.pinned ? <span className="chip">Pinned</span> : null}
          </div>
          {e.kind === 'quiz' && <Markdown>{e.prompt}</Markdown>}
          <div className="attempt">
            <span className="label">{e.kind === 'writing' ? 'You wrote' : 'You said'}</span>
            <span className="said">{e.said}</span>
          </div>
          <div className="solution">
            <div className="label">{e.kind === 'writing' ? 'Corrected' : 'Right answer'}</div>
            <Markdown>{e.correct}</Markdown>
            {e.explanation && <Markdown>{e.explanation}</Markdown>}
          </div>
          <label className="small" htmlFor={`note-${e.id}`}>
            In your own words: what went wrong, what to watch for
          </label>
          <textarea
            id={`note-${e.id}`}
            className="field"
            rows={2}
            defaultValue={e.note}
            onBlur={(ev) => ev.target.value !== e.note && patch(e.id, { note: ev.target.value })}
          />
          <div className="row">
            <button type="button" className="btn" onClick={() => patch(e.id, { pinned: !e.pinned })}>
              {e.pinned ? 'Unpin' : 'Pin'}
            </button>
            <button type="button" className="btn" onClick={() => patch(e.id, { resolved: !e.resolved })}>
              {e.resolved ? 'Reopen' : 'Resolved'}
            </button>
          </div>
        </section>
      ))}
    </main>
  )
}
