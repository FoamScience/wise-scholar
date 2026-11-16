import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, failure } from './api'
import { fileSize } from './i18n'
import { Swap } from './Swap'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from 'cn'

export const SOURCE_TYPES =
  '.pdf,.epub,.html,.htm,.md,.markdown,.txt,.rst,.py,.rs,.js,.ts,.tsx,.c,.cpp,.h,.hs,.go,.java,.kt,.rb,.sh,.toml,.yaml,.yml,.json,.csv,.tex'

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
    <div className="flex flex-col gap-2 border-t py-3">
      <div className="text-sm leading-snug font-medium text-ink-2">{t('sources.label')}</div>
      {props.sources.map((s) => (
        <div key={s.id} className="flex items-center gap-2 text-sm break-words" title={s.error ?? undefined}>
          <span className="grow">
            {s.name} <span className="text-muted-foreground">({fileSize(s.size)})</span>
          </span>
          <Badge className={cn('h-auto rounded-sm px-2 py-0.5 text-sm', s.status === 'failed' ? 'bg-warm-tint text-warm' : 'bg-accent text-accent-foreground')}>
            {s.status === 'ready' ? t('sources.sections', { count: s.sections }) : s.status === 'failed' ? t('sources.failed') : t('sources.processing')}
          </Badge>
          <Button type="button" variant="ghost" className="text-ink-2" aria-label={t('sources.remove', { name: s.name })} onClick={() => remove(s)}>
            ×
          </Button>
        </div>
      ))}
      <input
        ref={input}
        type="file"
        accept={SOURCE_TYPES}
        hidden
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
      />
      <Button type="button" variant="outline" className="justify-start" disabled={busy} onClick={() => input.current?.click()}>
        <Swap labels={[t('sources.add'), t('sources.uploading')]} at={busy ? 1 : 0} />
      </Button>
      <div className="text-sm text-muted-foreground">{t('sources.help')}</div>
    </div>
  )
}
