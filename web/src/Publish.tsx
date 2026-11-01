import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { day, fileSize } from './i18n'

type Licence = 'CC-BY-SA-4.0' | 'CC-BY-4.0' | 'CC-BY-NC-SA-4.0' | 'all-rights-reserved'
type Version = { hash: string; number: number; notes: string; licence: Licence; forkable: number; published: string; written: number; units: number }
type Preview = {
  sources: { id: number; name: string; size: number }[]
  from_workspace: { block: number; lesson: string; files: string[] }[]
  setup: string[]
  written: number
  units: number
  versions: Version[]
  forked_from: { topic: string; number: number; forkable: boolean } | null
  licences: Licence[]
}

/** Freeze the course as a version anyone can import, after checking what it carries; and its earlier versions. */
export function PublishPage({ courseId }: { courseId: number }) {
  const { t } = useTranslation()
  const [preview, setPreview] = useState<Preview | null>(null)
  const [notes, setNotes] = useState('')
  const [licence, setLicence] = useState<Licence>('CC-BY-SA-4.0')
  const [forkable, setForkable] = useState(true)
  const [sources, setSources] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Preview>(`/api/courses/${courseId}/publish`).then(setPreview, (e: Error) => setError(e.message))
  }, [courseId])

  async function publish() {
    setBusy(true)
    setError('')
    try {
      await api(`/api/courses/${courseId}/versions`, { notes, licence, forkable, sources })
      setNotes('')
      setPreview(await api<Preview>(`/api/courses/${courseId}/publish`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!preview) return <main className="home">{error && <div className="error">{error}</div>}</main>
  const blocked = preview.forked_from !== null && !preview.forked_from.forkable

  return (
    <main className="home publish-page">
      <a className="link" href={`#/course/${courseId}`}>
        {t('publish.back')}
      </a>
      <h1>{t('publish.heading')}</h1>
      <div className="muted">{t('publish.intro')}</div>
      {error && <div className="error">{error}</div>}
      {preview.forked_from && (
        <div className="small">{t(blocked ? 'publish.locked' : 'publish.forkOf', { topic: preview.forked_from.topic, number: preview.forked_from.number })}</div>
      )}

      {!blocked && (
        <section className="block stack">
          <div className="label">{t('publish.written', { written: preview.written, units: preview.units })}</div>
          <div className="small">{t('publish.writtenHelp')}</div>

          {preview.sources.length > 0 && (
            <fieldset className="stack">
              <legend className="label">{t('publish.sources')}</legend>
              <div className="small">{t('publish.sourcesHelp')}</div>
              {preview.sources.map((s) => (
                <label key={s.id} className="row">
                  <input
                    type="checkbox"
                    checked={sources.includes(s.id)}
                    onChange={(e) => setSources((all) => (e.target.checked ? [...all, s.id] : all.filter((x) => x !== s.id)))}
                  />
                  <span dir="auto">{s.name}</span>
                  <span className="small">{fileSize(s.size)}</span>
                </label>
              ))}
            </fieldset>
          )}

          {preview.from_workspace.length > 0 && (
            <div className="stack">
              <div className="label">{t('publish.fromWorkspace')}</div>
              <div className="small">{t('publish.fromWorkspaceHelp')}</div>
              <ul className="small">
                {preview.from_workspace.map((x) => (
                  <li key={x.block}>
                    <span dir="auto">{x.lesson}</span>: <code>{x.files.join(', ')}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview.setup.length > 0 && (
            <div className="stack">
              <div className="label">{t('publish.setup')}</div>
              <div className="small">{t('publish.setupHelp')}</div>
              <pre dir="ltr">{preview.setup.join('\n')}</pre>
            </div>
          )}

          <label className="label" htmlFor="publish-notes">
            {t('publish.notes')}
          </label>
          <textarea id="publish-notes" className="field" dir="auto" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <label className="label" htmlFor="publish-licence">
            {t('publish.licence')}
          </label>
          <select id="publish-licence" className="field" value={licence} onChange={(e) => setLicence(e.target.value as Licence)}>
            {preview.licences.map((l) => (
              <option key={l} value={l}>
                {t(`publish.licences.${l}`)}
              </option>
            ))}
          </select>
          <label className="row">
            <input type="checkbox" checked={forkable} onChange={(e) => setForkable(e.target.checked)} />
            <span>{t('publish.forkable')}</span>
          </label>
          <div className="row">
            <button type="button" className="btn primary" disabled={busy || preview.written === 0} onClick={publish}>
              {busy ? t('publish.publishing') : t('publish.publish', { number: (preview.versions[0]?.number ?? 0) + 1 })}
            </button>
          </div>
        </section>
      )}

      <section className="stack">
        <h2>{t('publish.versions')}</h2>
        {preview.versions.length === 0 && <div className="muted">{t('publish.none')}</div>}
        {preview.versions.map((v) => (
          <div key={v.hash} className="block entry">
            <div className="label">
              {t('publish.version', { number: v.number, date: day(v.published.slice(0, 10)) })}
              <span className="chip">{t('publish.writtenShort', { written: v.written, units: v.units })}</span>
            </div>
            {v.notes && (
              <div className="small" dir="auto">
                {v.notes}
              </div>
            )}
            <div className="small">
              {t(`publish.licences.${v.licence}`)}
              {v.forkable ? '' : `, ${t('publish.noForks')}`}
            </div>
            <div className="row">
              <a className="btn as-link" href={`/api/versions/${v.hash}/bundle`} download>
                {t('publish.download')}
              </a>
              <code className="small" dir="ltr" title={v.hash}>
                {v.hash.slice(0, 12)}
              </code>
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}
