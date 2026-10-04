import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, failure } from './api'
import { fileSize } from './i18n'

export type Source = { id: number; name: string; size: number; status: 'processing' | 'ready' | 'failed'; error: string | null; sections: number }

/** The learner's own files for a course; processed in the background, the tutor reads them a section at a time. */
export function SourcesPanel(props: { courseId: number; sources: Source[]; onChange: (s: Source[]) => void; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)

  async function upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    setBusy(true)
    try {
      const res = await fetch(`/api/courses/${props.courseId}/sources`, { method: 'POST', body: form })
      if (!res.ok) throw await failure(res)
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
      <div className="label">{t('sources.label')}</div>
      {props.sources.map((s) => (
        <div key={s.id} className="source-row" title={s.error ?? undefined}>
          <span className="grow">
            {s.name} <span className="muted">· {fileSize(s.size)}</span>
          </span>
          <span className={`chip${s.status === 'failed' ? ' warn' : ''}`}>
            {s.status === 'ready' ? t('sources.sections', { count: s.sections }) : s.status === 'failed' ? t('sources.failed') : t('sources.processing')}
          </span>
          <button type="button" className="link" aria-label={t('sources.remove', { name: s.name })} onClick={() => remove(s)}>
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
        {busy ? t('sources.uploading') : t('sources.add')}
      </button>
      <div className="small">{t('sources.help')}</div>
    </div>
  )
}
