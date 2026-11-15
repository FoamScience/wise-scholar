import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { InlineMarkdown } from './Md'

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

  if (!state) return error ? <div className="error">{error}</div> : null
  return (
    <div className="recap-contribute">
      <h2>{t('recap.contribute.heading')}</h2>
      <p className="small muted">{t('recap.contribute.intro')}</p>
      {error && <div className="error">{error}</div>}
      <ContributeStatus state={state} onAgain={() => act(api<State>(`/api/courses/${courseId}/contributions/find${query}`, {}))} />
      {state.contributions.length > 0 && (
        <ul>
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
  if (state.running) return <p className="muted" role="status">{t('recap.contribute.finding')}</p>
  if (state.contributions.length > 0) return null
  return (
    <p className="muted" role="status">
      {t(state.failed ? 'recap.contribute.failed' : 'recap.contribute.none')}{' '}
      <button type="button" className="btn" onClick={onAgain}>
        {t('recap.contribute.again')}
      </button>
    </p>
  )
}

function ContributionCard({ contribution: c, onStart, onDismiss }: { contribution: Contribution; onStart: () => void; onDismiss: () => void }) {
  const { t } = useTranslation()
  return (
    <li className="contribution">
      <div className="label">
        <span className="chip">{t(`recap.contribute.${c.size}`)}</span>{' '}
        <a href={`https://github.com/${c.repo}`} target="_blank" rel="noreferrer" dir="ltr">
          {c.repo}
        </a>
      </div>
      <strong dir="auto">
        <InlineMarkdown>{c.title}</InlineMarkdown>
      </strong>
      <dl className="small">
        <dt>{t('recap.contribute.gap')}</dt>
        <dd dir="auto">
          <InlineMarkdown>{c.gap}</InlineMarkdown>
        </dd>
        <dt>{t('recap.contribute.uses')}</dt>
        <dd dir="auto">
          <InlineMarkdown>{c.uses}</InlineMarkdown>
        </dd>
        <dt>{t('recap.contribute.firstStep')}</dt>
        <dd dir="auto">
          <InlineMarkdown>{c.first_step}</InlineMarkdown>
        </dd>
      </dl>
      <div className="row">
        <button type="button" className="btn primary" onClick={onStart}>
          {t(c.lesson_id ? 'recap.contribute.continue' : 'recap.contribute.start')}
        </button>
        {c.issue && (
          <a className="btn as-link" href={c.issue} target="_blank" rel="noreferrer">
            {t('recap.contribute.issue')}
          </a>
        )}
        {c.status === 'open' && (
          <button type="button" className="link" onClick={onDismiss}>
            {t('recap.contribute.dismiss')}
          </button>
        )}
      </div>
    </li>
  )
}
