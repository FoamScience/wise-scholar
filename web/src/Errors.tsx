import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { day } from './i18n'
import { Correction } from './Diff'
import Markdown from './Md'
import { textDirection } from './text'

export type Entry = {
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
  const { t } = useTranslation()
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
        <h1 className="grow">{t('notebook.heading', { n: open })}</h1>
        <label className="small">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> {t('notebook.showResolved')}
        </label>
      </div>
      {error && <div className="error">{error}</div>}
      {shown.length === 0 && <div className="muted">{t('notebook.empty')}</div>}
      {shown.map((e) => (
        <section key={e.id} className={`block entry${e.resolved ? ' resolved' : ''}`}>
          <div className="label">
            {e.kind === 'writing' ? t('common.correctedText') : t('notebook.confidentMiss')} · {e.topic} · {day(e.created)}
            {e.pinned ? <span className="chip">{t('notebook.pinned')}</span> : null}
          </div>
          {e.kind === 'quiz' && <Markdown>{e.prompt}</Markdown>}
          <div className="attempt">
            <span className="label">{e.kind === 'writing' ? t('notebook.youWrote') : t('notebook.youSaid')}</span>
            <span className="said" dir={textDirection(e.said)}>
              {e.said}
            </span>
          </div>
          <div className="solution">
            <div className="label">{e.kind === 'writing' ? t('notebook.corrected') : t('notebook.rightAnswer')}</div>
            {e.kind === 'writing' ? <Correction attempt={e.said} corrected={e.correct} /> : <Markdown>{e.correct}</Markdown>}
            {e.explanation && <Markdown>{e.explanation}</Markdown>}
          </div>
          <label className="small" htmlFor={`note-${e.id}`}>
            {t('notebook.note')}
          </label>
          <textarea
            id={`note-${e.id}`}
            className="field" dir="auto"
            rows={2}
            defaultValue={e.note}
            onBlur={(ev) => ev.target.value !== e.note && patch(e.id, { note: ev.target.value })}
          />
          <div className="row">
            <button type="button" className="btn" onClick={() => patch(e.id, { pinned: !e.pinned })}>
              {e.pinned ? t('notebook.unpin') : t('notebook.pin')}
            </button>
            <button type="button" className="btn" onClick={() => patch(e.id, { resolved: !e.resolved })}>
              {e.resolved ? t('notebook.reopen') : t('notebook.resolve')}
            </button>
          </div>
        </section>
      ))}
    </main>
  )
}
