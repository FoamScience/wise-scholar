import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { InlineMarkdown } from './Md'
import { api } from './api'
import type { Course } from './course'

type Suggestion = { id: number; title: string; pitch: string; kind: 'deeper' | 'adjacent'; builds_on: string }
type Suggestions = { suggestions: Suggestion[]; running: boolean; failed: boolean }

const POLL_MS = 4000

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
    <article className="suggestion">
      <span className={`chip ${suggestion.kind}`}>{t(`explore.kinds.${suggestion.kind}`)}</span>
      <h2 dir="auto">{suggestion.title}</h2>
      <p dir="auto">
        <InlineMarkdown>{suggestion.pitch}</InlineMarkdown>
      </p>
      <div className="muted small" dir="auto">
        {t('explore.buildsOn', { course: suggestion.builds_on })}
      </div>
      <div className="row">
        <button type="button" className="btn" disabled={starting} onClick={start}>
          {starting ? t('home.starting') : t('explore.start')}
        </button>
        <button type="button" className="link" disabled={starting} onClick={onDismiss}>
          {t('explore.dismiss')}
        </button>
      </div>
    </article>
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
    <main className="home explore">
      <header className="stack">
        <h1>{t('explore.heading')}</h1>
        <p className="muted">{t('explore.help')}</p>
      </header>
      {error && <div className="error">{error}</div>}
      {state?.failed && !state.running && <div className="error">{t('explore.failed')}</div>}
      {cards.length > 0 && (
        <div className="suggestions">
          {cards.map((s) => (
            <SuggestionCard key={s.id} suggestion={s} onDismiss={() => dismiss(s.id)} onError={setError} />
          ))}
        </div>
      )}
      {state?.running && cards.length === 0 && (
        <div className="suggestions" role="status" aria-label={t('explore.writing')}>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="suggestion skeleton">
              <span style={{ width: '30%' }} />
              <span style={{ width: '82%' }} />
              <span style={{ width: '96%' }} />
              <span style={{ width: '64%' }} />
            </div>
          ))}
        </div>
      )}
      {state && !state.running && !state.failed && cards.length === 0 && (
        <p>
          {t('explore.empty')} <a href="#/">{t('explore.emptyLink')}</a>
        </p>
      )}
      {state && (cards.length > 0 || state.failed) && (
        <div className="row">
          <button type="button" className="btn" disabled={state.running} aria-busy={state.running} onClick={others}>
            {state.running ? t('explore.writing') : t('explore.others')}
          </button>
        </div>
      )}
    </main>
  )
}
