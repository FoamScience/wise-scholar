import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { InlineMarkdown } from './Md'
import { api } from './api'
import { cn } from 'cn'
import type { Course } from './course'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

type Suggestion = { id: number; title: string; pitch: string; kind: 'deeper' | 'adjacent'; builds_on: string }
type Suggestions = { suggestions: Suggestion[]; running: boolean; failed: boolean }

const POLL_MS = 4000
const grid = 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3'

/** The learner's suggested next courses. Opening asks the server, which writes new ones only when they are due. */
export function useSuggestions(profile: number, enabled = true) {
  const [state, setState] = useState<Suggestions | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (enabled) api<Suggestions>('/api/suggestions', { profile_id: profile }).then(setState, (e: Error) => setError(e.message))
  }, [profile, enabled])
  useEffect(() => {
    if (!state?.running) return
    const timer = setTimeout(() => api<Suggestions>(`/api/suggestions?profile=${profile}`).then(setState, (e: Error) => setError(e.message)), POLL_MS)
    return () => clearTimeout(timer)
  }, [profile, state])
  return { state, setState, error, setError }
}

function SuggestionCard({ suggestion, onDismiss, onError }: { suggestion: Suggestion; onDismiss: () => void; onError: (message: string) => void }) {
  const { t } = useTranslation()
  const [starting, setStarting] = useState(false)

  function start() {
    setStarting(true)
    api<Course>(`/api/suggestions/${suggestion.id}/start`, {}).then(
      (course) => {
        location.hash = `#/course/${course.id}`
      },
      (e: Error) => {
        setStarting(false)
        onError(e.message)
      },
    )
  }

  return (
    <article className="flex flex-col items-start gap-2 rounded-lg border border-border bg-card p-4 transition-colors duration-[var(--dur-micro)] hover:border-input focus-within:border-input">
      <Badge variant="secondary" className={cn('h-auto rounded-sm px-2 py-0.5 text-sm', suggestion.kind === 'adjacent' ? 'bg-warm-tint text-warm-ink' : 'bg-accent text-accent-foreground')}>
        {t(`explore.kinds.${suggestion.kind}`)}
      </Badge>
      <h2 dir="auto" className="m-0 text-base leading-snug font-semibold">{suggestion.title}</h2>
      <p dir="auto" className="m-0 flex-1 text-sm">
        <InlineMarkdown>{suggestion.pitch}</InlineMarkdown>
      </p>
      <div className="text-sm text-muted-foreground" dir="auto">
        {t('explore.buildsOn', { course: suggestion.builds_on })}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" disabled={starting} onClick={start}>
          {starting ? t('home.starting') : t('explore.start')}
        </Button>
        <Button type="button" variant="ghost" className="text-ink-2" disabled={starting} onClick={onDismiss}>
          {t('explore.dismiss')}
        </Button>
      </div>
    </article>
  )
}

/** No cards yet: placeholders while the tutor writes them, or a way home when none came. */
function NoSuggestions({ state }: { state: Suggestions }) {
  const { t } = useTranslation()
  if (state.running)
    return (
      <div className={grid} role="status" aria-label={t('explore.writing')}>
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="flex min-h-48 flex-col items-stretch gap-2 rounded-lg border border-border bg-card p-4">
            <Skeleton className="h-4 w-[30%]" />
            <Skeleton className="h-4 w-[82%]" />
            <Skeleton className="h-4 w-[96%]" />
            <Skeleton className="h-4 w-[64%]" />
          </div>
        ))}
      </div>
    )
  if (state.failed) return null
  return (
    <p>
      {t('explore.empty')} <a href="#/">{t('explore.emptyLink')}</a>
    </p>
  )
}

/** Six courses the tutor suggests next: up a level in what the learner holds, or into a field next to it. */
export function ExplorePage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const { state, setState, error, setError } = useSuggestions(profile)

  function act(call: Promise<Suggestions>) {
    setError('')
    call.then(setState, (e: Error) => setError(e.message))
  }
  const others = () => act(api<Suggestions>('/api/suggestions', { profile_id: profile, others: true }))
  const dismiss = (id: number) => act(api<Suggestions>(`/api/suggestions/${id}/dismiss`, {}))

  const cards = state?.suggestions ?? []
  return (
    <main className="mx-auto flex w-full max-w-(--page) flex-col gap-10 px-6 pt-10 pb-16">
      <header className="flex flex-col gap-3">
        <h1 className="m-0 max-w-none">{t('explore.heading')}</h1>
        <p className="m-0 max-w-(--measure) text-muted-foreground">{t('explore.help')}</p>
      </header>
      {error && <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{error}</div>}
      {state?.failed && !state.running && <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{t('explore.failed')}</div>}
      {cards.length > 0 && (
        <div className={grid}>
          {cards.map((s) => (
            <SuggestionCard key={s.id} suggestion={s} onDismiss={() => dismiss(s.id)} onError={setError} />
          ))}
        </div>
      )}
      {state && cards.length === 0 && <NoSuggestions state={state} />}
      {state && (cards.length > 0 || state.failed) && (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" disabled={state.running} aria-busy={state.running} onClick={others}>
            {state.running ? t('explore.writing') : t('explore.others')}
          </Button>
        </div>
      )}
    </main>
  )
}
