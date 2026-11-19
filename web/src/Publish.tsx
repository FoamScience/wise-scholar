import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { day, fileSize } from './i18n'
import { Button, buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { cn } from 'cn'

const label = 'text-sm leading-snug font-medium text-ink-2'
const small = 'text-sm text-muted-foreground'
const errorBox = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const chip = 'inline-block rounded-sm bg-[var(--teal-tint)] px-2 py-0.5 leading-snug font-medium text-accent-foreground'
const stack = 'flex flex-col gap-3'
const row = 'flex flex-wrap items-center gap-2'
const card = 'flex flex-col gap-3 border-t border-border pt-6 [&>:last-child]:mb-0'
const select = 'h-auto min-h-11 w-full py-2 text-start whitespace-normal hover:border-foreground *:data-[slot=select-value]:line-clamp-none'

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

  if (!preview) return <main className="mx-auto flex w-full max-w-[var(--measure)] flex-col gap-10 px-6 pt-10 pb-16">{error && <div className={errorBox}>{error}</div>}</main>
  const blocked = preview.forked_from !== null && !preview.forked_from.forkable

  return (
    <main className="mx-auto flex w-full max-w-[var(--measure)] flex-col gap-10 px-6 pt-10 pb-16 [&_h1]:m-0 [&_h1]:font-semibold [&_h2]:font-semibold [&_h1]:text-[length:var(--text-display)] [&_h2]:m-0 [&_h2]:text-[length:var(--text-section)]">
      <a className={cn(buttonVariants({ variant: 'ghost' }), 'self-start text-ink-2')} href={`#/course/${courseId}`}>
        {t('publish.back')}
      </a>
      <h1>{t('publish.heading')}</h1>
      <div className="text-muted-foreground">{t('publish.intro')}</div>
      {error && <div className={errorBox}>{error}</div>}
      {stale > 0 && <div className={small}>{t('publish.stale', { count: stale })}</div>}
      {preview.forked_from && (
        <div className={small}>{t(blocked ? 'publish.locked' : 'publish.forkOf', { topic: preview.forked_from.topic, number: preview.forked_from.number })}</div>
      )}

      {!blocked && (
        <section className={card}>
          <div className={label}>{t('publish.written', { written: preview.written, units: preview.units })}</div>
          <div className={small}>{t('publish.writtenHelp')}</div>

          <Carried preview={preview} sources={sources} onSources={setSources} />

          {check && <CourseCheck check={check} written={preview.written} onStart={startCheck} onDecide={decide} />}

          <label className={label} htmlFor="publish-notes">
            {t('publish.notes')}
          </label>
          <Textarea id="publish-notes" dir="auto" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <label className={label} htmlFor="publish-licence">
            {t('publish.licence')}
          </label>
          <Select value={licence} items={Object.fromEntries(preview.licences.map((l) => [l, t(`publish.licences.${l}`)]))} onValueChange={(next) => setLicence(next as Licence)}>
            <SelectTrigger id="publish-licence" className={select}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              {preview.licences.map((l) => (
                <SelectItem key={l} value={l} className="*:first:shrink *:first:whitespace-normal">
                  {t(`publish.licences.${l}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <label className={row}>
            <Checkbox checked={forkable} onCheckedChange={setForkable} />
            <span>{t('publish.forkable')}</span>
          </label>
          <div className={row}>
            <Button type="button" disabled={busy || preview.written === 0 || check?.running} onClick={publish}>
              {busy ? t('publish.publishing') : t('publish.publish', { number: (preview.versions[0]?.number ?? 0) + 1 })}
            </Button>
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
        <fieldset className={cn(stack, 'm-0 min-w-0 border-0 p-0')}>
          <legend className={cn(label, 'mb-3 p-0')}>{t('publish.sources')}</legend>
          <div className={small}>{t('publish.sourcesHelp')}</div>
          {props.preview.sources.map((s) => (
            <label key={s.id} className={row}>
              <Checkbox
                checked={props.sources.includes(s.id)}
                onCheckedChange={(checked) => props.onSources((all) => (checked ? [...all, s.id] : all.filter((x) => x !== s.id)))}
              />
              <span dir="auto">{s.name}</span>
              <span className={small}>{fileSize(s.size)}</span>
            </label>
          ))}
        </fieldset>
      )}

      {props.preview.from_workspace.length > 0 && (
        <div className={stack}>
          <div className={label}>{t('publish.fromWorkspace')}</div>
          <div className={small}>{t('publish.fromWorkspaceHelp')}</div>
          <ul className={cn(small, 'm-0 list-disc ps-6')}>
            {props.preview.from_workspace.map((x) => (
              <li key={x.block}>
                <span dir="auto">{x.lesson}</span>: <code>{x.files.join(', ')}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {props.preview.setup.length > 0 && (
        <div className={stack}>
          <div className={label}>{t('publish.setup')}</div>
          <div className={small}>{t('publish.setupHelp')}</div>
          <pre dir="ltr" className="overflow-x-auto">{props.preview.setup.join('\n')}</pre>
        </div>
      )}
    </>
  )
}

function CourseCheck(props: { check: Check; written: number; onStart: () => void; onDecide: (edit: Edit, status: EditStatus) => void }) {
  const { t } = useTranslation()
  return (
    <div className={stack}>
      <div className={label}>{t('publish.check')}</div>
      <div className={small}>{t('publish.checkHelp')}</div>
      {props.check.running ? (
        <div className="text-muted-foreground">{t('publish.checking')}</div>
      ) : (
        <>
          {props.check.failed && <div className={errorBox}>{t('publish.checkFailed')}</div>}
          {props.check.checked && !props.check.failed && (
            <div className={small}>
              {t('publish.checked', { date: day(props.check.checked.slice(0, 10)) })}{' '}
              {props.check.edits.length === 0 && t('publish.checkNone')}
            </div>
          )}
          <div className={row}>
            <Button type="button" variant="outline" disabled={props.written === 0} onClick={props.onStart}>
              {props.check.checked ? t('publish.checkAgain') : t('publish.checkRun')}
            </Button>
            {!props.check.checked && <span className={small}>{t('publish.checkSkip')}</span>}
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
    <div className={cn(card, 'entry', props.edit.status === 'rejected' && 'opacity-60')}>
      <div className={label}>
        {t(`publish.targets.${props.edit.target}`)}
        {props.edit.lesson && (
          <span dir="auto">
            {': '}
            {props.edit.lesson}
          </span>
        )}
        {props.edit.target === 'file' && (
          <code className={small} dir="ltr">
            {' '}
            {props.edit.ref}
          </code>
        )}
        {props.edit.status !== 'proposed' && <span className={chip}>{t(`publish.${props.edit.status}`)}</span>}
      </div>
      <div className="flex flex-col gap-2 [overflow-wrap:anywhere] whitespace-pre-wrap" dir="auto">
        <del className="text-destructive">{props.edit.old}</del>
        <ins className="rounded-sm bg-[var(--teal-tint)] px-2 no-underline">{props.edit.new}</ins>
      </div>
      <div className={small} dir="auto">
        {props.edit.reason}
      </div>
      <div className={row}>
        {props.edit.status === 'proposed' ? (
          <>
            <Button type="button" onClick={() => props.onDecide('accepted')}>
              {t('publish.accept')}
            </Button>
            <Button type="button" variant="outline" onClick={() => props.onDecide('rejected')}>
              {t('publish.reject')}
            </Button>
          </>
        ) : (
          <Button type="button" variant="outline" onClick={() => props.onDecide('proposed')}>
            {t('publish.undo')}
          </Button>
        )}
      </div>
    </div>
  )
}

function Versions(props: { versions: Version[]; shared: Shared }) {
  const { t } = useTranslation()
  return (
    <section className={stack}>
      <h2>{t('publish.versions')}</h2>
      {props.versions.length === 0 && <div className="text-muted-foreground">{t('publish.none')}</div>}
      {props.versions.map((v) => (
        <div key={v.hash} className={cn(card, 'entry')}>
          <div className={label}>
            {t('publish.version', { number: v.number, date: day(v.published.slice(0, 10)) })}
            <span className={chip}>{t('publish.writtenShort', { written: v.written, units: v.units })}</span>
          </div>
          {v.notes && (
            <div className={small} dir="auto">
              {v.notes}
            </div>
          )}
          <div className={small}>
            {t(`publish.licences.${v.licence}`)}
            {v.forkable ? '' : `, ${t('publish.noForks')}`}
          </div>
          <div className={row}>
            <a className={buttonVariants({ variant: 'outline' })} href={`/api/versions/${v.hash}/bundle`} download>
              {t('publish.download')}
            </a>
            <code className={small} dir="ltr" title={v.hash}>
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
      <Button type="button" variant="outline" disabled={busy} title={t('publish.shareHelp')} onClick={share}>
        {busy ? t('publish.sharing') : t('publish.share')}
      </Button>
      {shown && (
        <>
          <Input ref={field} className="w-auto" dir="ltr" readOnly value={url} aria-label={t('publish.share')} onFocus={(e) => e.target.select()} />
          <Button type="button" variant="outline" onClick={copy}>
            {copied ? t('publish.copied') : t('publish.copy')}
          </Button>
        </>
      )}
      {error && <span className={errorBox}>{error}</span>}
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
      <div className={row}>
        <span className={cn(small, errorBox)}>{t('publish.linksFailed')}</span>
        <Button type="button" variant="outline" onClick={props.shared.reload}>
          {t('publish.linksRetry')}
        </Button>
      </div>
    )
  }
  if (mine.length === 0) return null
  return (
    <section className={stack}>
      <h2>{t('publish.links')}</h2>
      <div className={small}>{t('publish.linksHelp')}</div>
      {mine.map((l) => (
        <div key={l.id} className={row}>
          <span className={chip}>{t('publish.linkOf', { number: numbers.get(l.hash) })}</span>
          <code dir="ltr">{l.url}</code>
          <span className={small}>{day(l.created)}</span>
          <Button type="button" variant="outline" onClick={() => props.shared.revoke(l)}>
            {t('publish.revoke')}
          </Button>
        </div>
      ))}
    </section>
  )
}
