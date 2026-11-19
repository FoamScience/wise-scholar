import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { Badge } from '@/components/ui/badge'
import i18n, { moment, number } from './i18n'

const MAIN = 'mx-auto flex w-full max-w-160 flex-col gap-10 px-6 pt-10 pb-16'
const CELL = 'min-w-40 border px-3 py-2 text-start'
const NUM = 'border px-3 py-2 text-end whitespace-nowrap tabular-nums'

type Sums = { turns: number; input: number; output: number; cache_read: number; cache_write: number; cost: number | null; last: string }
type CourseUsage = Sums & {
  id: number
  topic: string
  archived: number
  lessons: (Sums & { id: number | null; title: string | null; phase: string | null })[]
  kinds: (Sums & { kind: string })[]
}

const tokens = (n: number) => new Intl.NumberFormat(i18n.language, { notation: 'compact', maximumFractionDigits: 1, numberingSystem: 'latn' }).format(n)
const dollars = (n: number | null) =>
  n === null ? '–' : new Intl.NumberFormat(i18n.language, { style: 'currency', currency: 'USD', maximumFractionDigits: n < 1 ? 3 : 2, numberingSystem: 'latn' }).format(n)

/** Tokens and API-equivalent cost of every agent turn, per course and lesson. */
export function UsagePage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState<CourseUsage[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<CourseUsage[]>(`/api/usage?profile=${profile}`).then(setCourses, (e: Error) => setError(e.message))
  }, [profile])

  if (!courses) return <main className={MAIN}>{error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div>}</main>

  const total = courses.reduce((sum, c) => sum + (c.cost ?? 0), 0)

  function cells(s: Sums) {
    return (
      <>
        <td className={NUM}>{dollars(s.cost)}</td>
        <td className={NUM}>{number(s.turns)}</td>
        <td className={NUM}>{tokens(s.input + s.cache_read + s.cache_write)}</td>
        <td className={NUM}>{tokens(s.output)}</td>
      </>
    )
  }

  function head(first: string) {
    return (
      <thead>
        <tr>
          <th className={CELL}>{first}</th>
          <th className={NUM}>{t('usage.cost')}</th>
          <th className={NUM}>{t('usage.turns')}</th>
          <th className={NUM}>{t('usage.input')}</th>
          <th className={NUM}>{t('usage.output')}</th>
        </tr>
      </thead>
    )
  }

  return (
    <main className={MAIN}>
      <h1 className="m-0 max-w-none font-heading text-2xl font-semibold">{t('usage.heading')}</h1>
      <div className="text-muted-foreground">{t('usage.intro')}</div>
      {courses.length === 0 && <div className="text-muted-foreground">{t('usage.empty')}</div>}
      {courses.length > 0 && <div className="text-sm leading-snug font-medium text-ink-2">{t('usage.total', { cost: dollars(total) })}</div>}
      {courses.map((c) => (
        <section key={c.id} className="flex flex-col gap-3 border-t pt-6">
          <div className="text-sm leading-snug font-medium text-ink-2">
            <span dir="auto">{c.topic}</span>
            {c.archived ? <Badge className="ms-2 h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t('usage.archived')}</Badge> : null}
          </div>
          <div className="text-sm text-muted-foreground">
            {t('usage.summary', {
              cost: dollars(c.cost),
              input: tokens(c.input + c.cache_read + c.cache_write),
              cached: tokens(c.cache_read),
              output: tokens(c.output),
              last: moment(c.last.replace(' ', 'T') + 'Z'),
            })}
          </div>
          <div className="overflow-x-auto">
            <table className="m-0 w-full border-collapse text-sm">
              {head(t('usage.lesson'))}
              <tbody>
                {c.lessons.map((l) => (
                  <tr key={l.id ?? 'none'}>
                    <td dir="auto" className={CELL}>{l.title ?? t('usage.noLesson')}</td>
                    {cells(l)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">{t('usage.byKind')}</summary>
            <div className="overflow-x-auto">
              <table className="m-0 w-full border-collapse text-sm">
                {head(t('usage.kind'))}
                <tbody>
                  {c.kinds.map((k) => (
                    <tr key={k.kind}>
                      <td className={CELL}>{t(`usage.kinds.${k.kind}`, { defaultValue: k.kind })}</td>
                      {cells(k)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      ))}
    </main>
  )
}
