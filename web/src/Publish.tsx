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
type EditTarget = 'block' | 'card' | 'file' | 'course' | 'summary'
type EditStatus = 'proposed' | 'accepted' | 'rejected'
type Edit = { id: number; target: EditTarget; ref: string; old: string; new: string; reason: string; status: EditStatus; lesson: string | null }
type Check = { running: boolean; failed: boolean; checked: string | null; edits: Edit[] }

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
  const [check, setCheck] = useState<Check | null>(null)
  const [stale, setStale] = useState(0)

  useEffect(() => {
    api<Preview>(`/api/courses/${courseId}/publish`).then(setPreview, (e: Error) => setError(e.message))
    api<Check>(`/api/courses/${courseId}/check`).then(setCheck, (e: Error) => setError(e.message))
  }, [courseId])

  useEffect(() => {
    if (!check?.running) return
    const timer = setTimeout(() => api<Check>(`/api/courses/${courseId}/check`).then(setCheck, (e: Error) => setError(e.message)), 2000)
    return () => clearTimeout(timer)
  }, [courseId, check])

  async function startCheck() {
    setError('')
    try {
      setCheck(await api<Check>(`/api/courses/${courseId}/check`, {}))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function decide(edit: Edit, status: EditStatus) {
    try {
      setCheck(await api<Check>(`/api/courses/${courseId}/check/${edit.id}`, { status }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function publish() {
    setBusy(true)
    setError('')
    try {
      const published = await api<{ stale: number }>(`/api/courses/${courseId}/versions`, { notes, licence, forkable, sources })
      setStale(published.stale)
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
      {stale > 0 && <div className="small">{t('publish.stale', { count: stale })}</div>}
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

          {check && (
            <div className="stack publish-check">
              <div className="label">{t('publish.check')}</div>
              <div className="small">{t('publish.checkHelp')}</div>
              {check.running ? (
                <div className="muted">{t('publish.checking')}</div>
              ) : (
                <>
                  {check.failed && <div className="error">{t('publish.checkFailed')}</div>}
                  {check.checked && !check.failed && (
                    <div className="small">
                      {t('publish.checked', { date: day(check.checked.slice(0, 10)) })}{' '}
                      {check.edits.length === 0 && t('publish.checkNone')}
                    </div>
                  )}
                  <div className="row">
                    <button type="button" className="btn" disabled={preview.written === 0} onClick={startCheck}>
                      {check.checked ? t('publish.checkAgain') : t('publish.checkRun')}
                    </button>
                    {!check.checked && <span className="small">{t('publish.checkSkip')}</span>}
                  </div>
                </>
              )}
              {check.edits.map((edit) => (
                <div key={edit.id} className={`block entry edit ${edit.status}`}>
                  <div className="label">
                    {t(`publish.targets.${edit.target}`)}
                    {edit.lesson && (
                      <span dir="auto">
                        {': '}
                        {edit.lesson}
                      </span>
                    )}
                    {edit.target === 'file' && (
                      <code className="small" dir="ltr">
                        {' '}
                        {edit.ref}
                      </code>
                    )}
                    {edit.status !== 'proposed' && <span className="chip">{t(`publish.${edit.status}`)}</span>}
                  </div>
                  <div className="edit-change" dir="auto">
                    <del>{edit.old}</del>
                    <ins>{edit.new}</ins>
                  </div>
                  <div className="small" dir="auto">
                    {edit.reason}
                  </div>
                  <div className="row">
                    {edit.status === 'proposed' ? (
                      <>
                        <button type="button" className="btn primary" onClick={() => decide(edit, 'accepted')}>
                          {t('publish.accept')}
                        </button>
                        <button type="button" className="btn" onClick={() => decide(edit, 'rejected')}>
                          {t('publish.reject')}
                        </button>
                      </>
                    ) : (
                      <button type="button" className="btn" onClick={() => decide(edit, 'proposed')}>
                        {t('publish.undo')}
                      </button>
                    )}
                  </div>
                </div>
              ))}
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
            <button type="button" className="btn primary" disabled={busy || preview.written === 0 || check?.running} onClick={publish}>
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
