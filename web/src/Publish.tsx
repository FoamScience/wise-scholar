import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
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
type Link = { id: string; url: string; hash: string; created: string; revoked: string | null }
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
  const [stale, setStale] = useState(0)

  useEffect(() => {
    api<Preview>(`/api/courses/${courseId}/publish`).then(setPreview, (e: Error) => setError(e.message))
  }, [courseId])
  const { check, startCheck, decide } = useCourseCheck(courseId, setError)
  const shared = useSharedLinks(setError)

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

          <Carried preview={preview} sources={sources} onSources={setSources} />

          {check && <CourseCheck check={check} written={preview.written} onStart={startCheck} onDecide={decide} />}

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

      <Versions versions={preview.versions} shared={shared} />
      {shared.enabled && <SharedLinks shared={shared} versions={preview.versions} />}
    </main>
  )
}

/** The course's check runs on the server; while it runs the page asks again every 2 s. */
function useCourseCheck(courseId: number, setError: (message: string) => void) {
  const [check, setCheck] = useState<Check | null>(null)

  useEffect(() => {
    api<Check>(`/api/courses/${courseId}/check`).then(setCheck, (e: Error) => setError(e.message))
  }, [courseId, setError])

  useEffect(() => {
    if (!check?.running) return
    const timer = setTimeout(() => api<Check>(`/api/courses/${courseId}/check`).then(setCheck, (e: Error) => setError(e.message)), 2000)
    return () => clearTimeout(timer)
  }, [courseId, check, setError])

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

  return { check, startCheck, decide }
}

/** Whether a registry is set up, its links (null until loaded; `failed` when they could not be), and revoking one. */
function useSharedLinks(setError: (message: string) => void) {
  const [enabled, setEnabled] = useState(false)
  const [links, setLinks] = useState<Link[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [revoked, setRevoked] = useState<string[]>([])

  const reload = useCallback(
    () =>
      api<Link[]>('/api/registry/links').then(
        (found) => {
          setLinks(found)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    api<{ configured: boolean }>('/api/registry').then(
      (registry) => {
        setEnabled(registry.configured)
        if (registry.configured) reload()
      },
      (e: Error) => setError(e.message),
    )
  }, [reload, setError])

  async function revoke(link: Link) {
    try {
      await api(`/api/registry/links/${encodeURIComponent(link.id)}`, undefined, 'DELETE')
      setRevoked((urls) => [...urls, link.url])
      await reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return { enabled, links, failed, revoked, reload, revoke }
}
type Shared = ReturnType<typeof useSharedLinks>

/** What goes into the version besides the lessons: chosen sources, files from the workspace, setup commands. */
function Carried(props: { preview: Preview; sources: number[]; onSources: Dispatch<SetStateAction<number[]>> }) {
  const { t } = useTranslation()
  return (
    <>
      {props.preview.sources.length > 0 && (
        <fieldset className="stack">
          <legend className="label">{t('publish.sources')}</legend>
          <div className="small">{t('publish.sourcesHelp')}</div>
          {props.preview.sources.map((s) => (
            <label key={s.id} className="row">
              <input
                type="checkbox"
                checked={props.sources.includes(s.id)}
                onChange={(e) => props.onSources((all) => (e.target.checked ? [...all, s.id] : all.filter((x) => x !== s.id)))}
              />
              <span dir="auto">{s.name}</span>
              <span className="small">{fileSize(s.size)}</span>
            </label>
          ))}
        </fieldset>
      )}

      {props.preview.from_workspace.length > 0 && (
        <div className="stack">
          <div className="label">{t('publish.fromWorkspace')}</div>
          <div className="small">{t('publish.fromWorkspaceHelp')}</div>
          <ul className="small">
            {props.preview.from_workspace.map((x) => (
              <li key={x.block}>
                <span dir="auto">{x.lesson}</span>: <code>{x.files.join(', ')}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {props.preview.setup.length > 0 && (
        <div className="stack">
          <div className="label">{t('publish.setup')}</div>
          <div className="small">{t('publish.setupHelp')}</div>
          <pre dir="ltr">{props.preview.setup.join('\n')}</pre>
        </div>
      )}
    </>
  )
}

function CourseCheck(props: { check: Check; written: number; onStart: () => void; onDecide: (edit: Edit, status: EditStatus) => void }) {
  const { t } = useTranslation()
  return (
    <div className="stack publish-check">
      <div className="label">{t('publish.check')}</div>
      <div className="small">{t('publish.checkHelp')}</div>
      {props.check.running ? (
        <div className="muted">{t('publish.checking')}</div>
      ) : (
        <>
          {props.check.failed && <div className="error">{t('publish.checkFailed')}</div>}
          {props.check.checked && !props.check.failed && (
            <div className="small">
              {t('publish.checked', { date: day(props.check.checked.slice(0, 10)) })}{' '}
              {props.check.edits.length === 0 && t('publish.checkNone')}
            </div>
          )}
          <div className="row">
            <button type="button" className="btn" disabled={props.written === 0} onClick={props.onStart}>
              {props.check.checked ? t('publish.checkAgain') : t('publish.checkRun')}
            </button>
            {!props.check.checked && <span className="small">{t('publish.checkSkip')}</span>}
          </div>
        </>
      )}
      {props.check.edits.map((edit) => (
        <EditCard key={edit.id} edit={edit} onDecide={(status) => props.onDecide(edit, status)} />
      ))}
    </div>
  )
}

function EditCard(props: { edit: Edit; onDecide: (status: EditStatus) => void }) {
  const { t } = useTranslation()
  return (
    <div className={`block entry edit ${props.edit.status}`}>
      <div className="label">
        {t(`publish.targets.${props.edit.target}`)}
        {props.edit.lesson && (
          <span dir="auto">
            {': '}
            {props.edit.lesson}
          </span>
        )}
        {props.edit.target === 'file' && (
          <code className="small" dir="ltr">
            {' '}
            {props.edit.ref}
          </code>
        )}
        {props.edit.status !== 'proposed' && <span className="chip">{t(`publish.${props.edit.status}`)}</span>}
      </div>
      <div className="edit-change" dir="auto">
        <del>{props.edit.old}</del>
        <ins>{props.edit.new}</ins>
      </div>
      <div className="small" dir="auto">
        {props.edit.reason}
      </div>
      <div className="row">
        {props.edit.status === 'proposed' ? (
          <>
            <button type="button" className="btn primary" onClick={() => props.onDecide('accepted')}>
              {t('publish.accept')}
            </button>
            <button type="button" className="btn" onClick={() => props.onDecide('rejected')}>
              {t('publish.reject')}
            </button>
          </>
        ) : (
          <button type="button" className="btn" onClick={() => props.onDecide('proposed')}>
            {t('publish.undo')}
          </button>
        )}
      </div>
    </div>
  )
}

function Versions(props: { versions: Version[]; shared: Shared }) {
  const { t } = useTranslation()
  return (
    <section className="stack">
      <h2>{t('publish.versions')}</h2>
      {props.versions.length === 0 && <div className="muted">{t('publish.none')}</div>}
      {props.versions.map((v) => (
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
            {props.shared.enabled && <ShareButton hash={v.hash} shared={props.shared} />}
          </div>
        </div>
      ))}
    </section>
  )
}

/** Gets a version's link (pushing it to the registry when it has none), shown with a button to copy it. */
function ShareButton(props: { hash: string; shared: Shared }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [url, setUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const field = useRef<HTMLInputElement>(null)
  const shown = url && !props.shared.revoked.includes(url)

  async function share() {
    setBusy(true)
    setError('')
    try {
      setUrl((await api<{ url: string }>(`/api/versions/${props.hash}/share`, {})).url)
      setCopied(false)
      props.shared.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // navigator.clipboard is missing on pages served over plain http
  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setError('')
    } catch {
      field.current?.select()
      setError(t('publish.copyFailed'))
    }
  }

  return (
    <>
      <button type="button" className="btn" disabled={busy} title={t('publish.shareHelp')} onClick={share}>
        {busy ? t('publish.sharing') : t('publish.share')}
      </button>
      {shown && (
        <>
          <input ref={field} className="field" dir="ltr" readOnly value={url} aria-label={t('publish.share')} onFocus={(e) => e.target.select()} />
          <button type="button" className="btn" onClick={copy}>
            {copied ? t('publish.copied') : t('publish.copy')}
          </button>
        </>
      )}
      {error && <span className="error">{error}</span>}
    </>
  )
}

/** The links made for this course's versions that still work. */
function SharedLinks(props: { shared: Shared; versions: Version[] }) {
  const { t } = useTranslation()
  const numbers = new Map(props.versions.map((v) => [v.hash, v.number]))
  const mine = (props.shared.links ?? []).filter((l) => numbers.has(l.hash) && !l.revoked)
  if (props.shared.failed) {
    return (
      <div className="row">
        <span className="small error">{t('publish.linksFailed')}</span>
        <button type="button" className="btn" onClick={props.shared.reload}>
          {t('publish.linksRetry')}
        </button>
      </div>
    )
  }
  if (mine.length === 0) return null
  return (
    <section className="stack">
      <h2>{t('publish.links')}</h2>
      <div className="small">{t('publish.linksHelp')}</div>
      {mine.map((l) => (
        <div key={l.id} className="row">
          <span className="chip">{t('publish.linkOf', { number: numbers.get(l.hash) })}</span>
          <code dir="ltr">{l.url}</code>
          <span className="small">{day(l.created)}</span>
          <button type="button" className="btn" onClick={() => props.shared.revoke(l)}>
            {t('publish.revoke')}
          </button>
        </div>
      ))}
    </section>
  )
}
