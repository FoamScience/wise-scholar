import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api } from './api'
import { day, percent } from './i18n'

type Summary = { answers: number; sure?: number; right?: number; misses?: string[]; ended?: string; current?: boolean }

/** How sure the learner said they were in their latest sitting, against how often they were right, and the
 * questions they were sure of and missed. */
export function SittingSummary({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [summary, setSummary] = useState<Summary | null>(null)
  useEffect(() => {
    api<Summary>(`/api/sitting?profile=${profile}`).then(setSummary, () => {})
  }, [profile])
  if (!summary) return null
  if (!summary.answers) return null
  return (
    <section className="block sitting">
      <div className="label">{summary.current ? t('sitting.this') : `${t('sitting.last')}, ${day(summary.ended!)}`}</div>
      <p>{t('sitting.line', { count: summary.answers, sure: percent(summary.sure!), right: percent(summary.right!) })}</p>
      {summary.misses!.length > 0 && (
        <>
          <div className="small">{t('sitting.misses')}</div>
          <ul>
            {summary.misses!.map((question, i) => (
              <li key={i}>
                <Markdown>{question}</Markdown>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/** The page "End sitting" opens: the sitting's summary, then the way home. */
export function SittingPage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  return (
    <main className="home">
      <h1>{t('sitting.ended')}</h1>
      <SittingSummary profile={profile} />
      <a className="btn as-link" href="#/">{t('review.back')}</a>
    </main>
  )
}
