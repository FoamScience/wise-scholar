import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api } from './api'
import { type TodayPlan, unitTitle } from './course'
import { day, percent } from './i18n'
import { cn } from 'cn'
import { buttonVariants } from '@/components/ui/button'

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
    <section className="block space-y-2 border-t border-border pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">{summary.current ? t('sitting.this') : `${t('sitting.last')}, ${day(summary.ended!)}`}</div>
      <p>{t('sitting.line', { count: summary.answers, sure: percent(summary.sure!), right: percent(summary.right!) })}</p>
      {summary.misses!.length > 0 && (
        <>
          <div className="text-sm text-muted-foreground">{t('sitting.misses')}</div>
          <ul className="list-disc space-y-2 ps-6">
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

/** What the next sitting opens with: the reviews due by then and the next unit. */
function NextTime({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState<TodayPlan | null>(null)
  useEffect(() => {
    api<TodayPlan>(`/api/today?profile=${profile}`).then(setPlan, () => {})
  }, [profile])
  if (!plan || (plan.due === 0 && plan.units.length === 0)) return null
  const unit = plan.units[0]
  return (
    <section className="block space-y-2 border-t border-border pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">{t('sitting.next')}</div>
      <ul className="list-disc ps-6">
        {plan.due > 0 && <li>{t('today.reviews', { count: plan.warmup })}</li>}
        {unit && <li>{t('today.unit', { topic: unit.topic, title: unitTitle(unit, t) })}</li>}
      </ul>
    </section>
  )
}

/** The page "Stop for today" opens: the sitting's summary, what comes next time, then the way home. */
export function SittingPage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  return (
    <main className="mx-auto flex w-full max-w-(--measure) flex-col gap-10 px-6 pt-10 pb-16">
      <h1 className="m-0 max-w-none">{t('sitting.ended')}</h1>
      <SittingSummary profile={profile} />
      <NextTime profile={profile} />
      <a className={cn(buttonVariants({ variant: 'outline' }), 'w-fit')} href="#/">{t('review.back')}</a>
    </main>
  )
}
