import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { InlineMarkdown } from './Md'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'

type Contribution = {
  id: number
  repo: string
  title: string
  size: 'small' | 'project'
  gap: string
  uses: string
  first_step: string
  issue: string | null
  status: 'open' | 'started'
  lesson_id: number | null
}
type State = { contributions: Contribution[]; running: boolean; failed: boolean }

/** Optional open-source work that puts the finished course to use, looked for once by the tutor; one taken up opens a
 * lesson where the tutor guides it. written: bumped when the server says a search ended. */
export function ContributeSection({ courseId, preview, written }: { courseId: number; preview: boolean; written: number }) {
  const { t } = useTranslation()
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const query = preview ? '?preview=true' : ''

  useEffect(() => {
    api<State>(`/api/courses/${courseId}/contributions${query}`).then(setState, (e: Error) => setError(e.message))
  }, [courseId, query, written])

  function act(call: Promise<State>) {
    setError('')
    call.then(setState, (e: Error) => setError(e.message))
  }

  function start(c: Contribution) {
    api(`/api/contributions/${c.id}/start`, {}).then(
      () => (location.hash = `#/course/${courseId}`),
      (e: Error) => setError(e.message),
    )
  }

  if (!state) return error ? <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{error}</div> : null
  return (
    <div className="col-span-full">
      <h2 className="m-0">{t('recap.contribute.heading')}</h2>
      <p className="m-0 text-sm text-muted-foreground">{t('recap.contribute.intro')}</p>
      {error && <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{error}</div>}
      <ContributeStatus state={state} onAgain={() => act(api<State>(`/api/courses/${courseId}/contributions/find${query}`, {}))} />
      {state.contributions.length > 0 && (
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))] gap-4 p-0">
          {state.contributions.map((c) => (
            <ContributionCard key={c.id} contribution={c} onStart={() => start(c)} onDismiss={() => act(api<State>(`/api/contributions/${c.id}/dismiss`, {}))} />
          ))}
        </ul>
      )}
    </div>
  )
}

function ContributeStatus({ state, onAgain }: { state: State; onAgain: () => void }) {
  const { t } = useTranslation()
  if (state.running) return <p className="m-0 text-muted-foreground" role="status">{t('recap.contribute.finding')}</p>
  if (state.contributions.length > 0) return null
  return (
    <p className="m-0 text-muted-foreground" role="status">
      {t(state.failed ? 'recap.contribute.failed' : 'recap.contribute.none')}{' '}
      <Button type="button" variant="outline" onClick={onAgain}>
        {t('recap.contribute.again')}
      </Button>
    </p>
  )
}

function ContributionCard({ contribution: c, onStart, onDismiss }: { contribution: Contribution; onStart: () => void; onDismiss: () => void }) {
  const { t } = useTranslation()
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <div className="text-sm leading-snug font-medium text-ink-2">
        <Badge variant="secondary" className="h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t(`recap.contribute.${c.size}`)}</Badge>{' '}
        <a href={`https://github.com/${c.repo}`} target="_blank" rel="noreferrer" dir="ltr" className="text-accent-foreground">
          {c.repo}
        </a>
      </div>
      <strong dir="auto">
        <InlineMarkdown>{c.title}</InlineMarkdown>
      </strong>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm text-muted-foreground">
        <dt>{t('recap.contribute.gap')}</dt>
        <dd dir="auto" className="m-0 break-words">
          <InlineMarkdown>{c.gap}</InlineMarkdown>
        </dd>
        <dt>{t('recap.contribute.uses')}</dt>
        <dd dir="auto" className="m-0 break-words">
          <InlineMarkdown>{c.uses}</InlineMarkdown>
        </dd>
        <dt>{t('recap.contribute.firstStep')}</dt>
        <dd dir="auto" className="m-0 break-words">
          <InlineMarkdown>{c.first_step}</InlineMarkdown>
        </dd>
      </dl>
      <div className="mt-auto flex flex-wrap items-center gap-2">
        <Button type="button" onClick={onStart}>
          {t(c.lesson_id ? 'recap.contribute.continue' : 'recap.contribute.start')}
        </Button>
        {c.issue && (
          <a className={buttonVariants({ variant: 'outline' })} href={c.issue} target="_blank" rel="noreferrer">
            {t('recap.contribute.issue')}
          </a>
        )}
        {c.status === 'open' && (
          <Button type="button" variant="ghost" className="text-ink-2" onClick={onDismiss}>
            {t('recap.contribute.dismiss')}
          </Button>
        )}
      </div>
    </li>
  )
}
