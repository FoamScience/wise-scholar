import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { SEARCH_KINDS, type SearchKind, searchHref } from './course'
import Markdown from './Md'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from 'cn'

type Hit = {
  kind: SearchKind
  ref: string
  lesson_id: number | null
  concept_id: number | null
  title: string
  text: string
  snippet: [string, boolean][]
  by: 'words' | 'meaning' | 'both'
}

/** The course's sources, lesson cards, chats and code found by their words or their meaning. */
export function SearchPage({ courseId, query, kind: asked }: { courseId: number; query: string; kind: string }) {
  const { t } = useTranslation()
  const kind = SEARCH_KINDS.find((k) => k === asked) ?? ''
  const [draft, setDraft] = useState(query)
  const [hits, setHits] = useState<Hit[] | null>(null)
  const [error, setError] = useState('')

  // the page is keyed by its address, so a new search starts from empty state
  useEffect(() => {
    if (!query.trim()) return
    api<Hit[]>(`/api/courses/${courseId}/search?${new URLSearchParams({ q: query, kind })}`).then(setHits, (e: Error) => setError(e.message))
  }, [courseId, query, kind])

  return (
    <main className="mx-auto flex w-full max-w-(--measure) flex-col gap-10 px-6 pt-10 pb-16">
      <a className={cn(buttonVariants({ variant: 'outline' }), 'w-fit')} href={`#/course/${courseId}`}>{t('book.back')}</a>
      <form
        className="flex gap-2"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          location.hash = searchHref(courseId, draft, kind)
        }}
      >
        <Input type="search" className="grow" dir="auto" aria-label={t('search.label')} placeholder={t('search.placeholder')} value={draft} onChange={(e) => setDraft(e.target.value)} />
        <Button type="submit">
          {t('search.go')}
        </Button>
      </form>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('search.kinds')}>
        {(['', ...SEARCH_KINDS] as const).map((k) => (
          <a key={k} className={cn('min-h-9 rounded-md border px-3 py-1 text-foreground no-underline', k === kind ? 'border-primary bg-accent' : 'border-border')} aria-current={k === kind} href={searchHref(courseId, query, k)}>
            {t(`search.kind.${k || 'all'}`)}
          </a>
        ))}
      </div>
      {error && <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{error}</div>}
      {hits === null && query.trim() && !error && <div className="text-muted-foreground">{t('search.searching')}</div>}
      {hits?.length === 0 && query.trim() && <div className="text-muted-foreground">{t('search.none')}</div>}
      {hits?.map((h) => <HitCard key={`${h.kind}-${h.ref}`} hit={h} courseId={courseId} />)}
    </main>
  )
}

function HitCard(props: { hit: Hit; courseId: number }) {
  const { t } = useTranslation()
  const h = props.hit
  return (
    <section className="block min-w-0 space-y-2 border-t border-border pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">
        <Badge variant="secondary" className="h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t(`search.kind.${h.kind}`)}</Badge> <span dir="auto">{h.kind === 'code' ? h.ref : h.title}</span>
        {h.by !== 'words' && <Badge variant="secondary" className="ms-2 h-auto rounded-sm bg-warm-tint px-2 py-0.5 text-sm text-warm">{t(`search.by.${h.by}`)}</Badge>}
      </div>
      <p dir="auto" className="m-0 break-words">
        {h.snippet.map(([piece, matched], i) => (matched ? <mark key={i}>{piece}</mark> : piece))}
      </p>
      {h.lesson_id !== null ? (
        <a className={cn(buttonVariants({ variant: 'outline' }), 'w-fit')} href={`#/course/${props.courseId}?lesson=${h.lesson_id}&${h.kind}=${h.ref}`}>{t(h.kind === 'chat' ? 'search.openMessage' : 'search.openCard')}</a>
      ) : (
        <details>
          <summary>{t('search.showPassage')}</summary>
          {h.kind === 'code' ? (
            <pre className="overflow-x-auto">
              <code>{h.text}</code>
            </pre>
          ) : (
            <div dir="auto">
              <Markdown>{h.text}</Markdown>
            </div>
          )}
        </details>
      )}
    </section>
  )
}
