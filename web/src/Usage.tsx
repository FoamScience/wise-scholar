import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import i18n, { moment, number } from './i18n'

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

  if (!courses) return <main className="home">{error && <div className="error">{error}</div>}</main>

  const total = courses.reduce((sum, c) => sum + (c.cost ?? 0), 0)

  function cells(s: Sums) {
    return (
      <>
        <td>{dollars(s.cost)}</td>
        <td>{number(s.turns)}</td>
        <td>{tokens(s.input + s.cache_read + s.cache_write)}</td>
        <td>{tokens(s.output)}</td>
      </>
    )
  }

  function head(first: string) {
    return (
      <thead>
        <tr>
          <th>{first}</th>
          <th>{t('usage.cost')}</th>
          <th>{t('usage.turns')}</th>
          <th>{t('usage.input')}</th>
          <th>{t('usage.output')}</th>
        </tr>
      </thead>
    )
  }

  return (
    <main className="home usage-page">
      <h1>{t('usage.heading')}</h1>
      <div className="muted">{t('usage.intro')}</div>
      {courses.length === 0 && <div className="muted">{t('usage.empty')}</div>}
      {courses.length > 0 && <div className="label">{t('usage.total', { cost: dollars(total) })}</div>}
      {courses.map((c) => (
        <section key={c.id} className="block entry">
          <div className="label">
            <span dir="auto">{c.topic}</span>
            {c.archived ? <span className="chip">{t('usage.archived')}</span> : null}
          </div>
          <div className="small">
            {t('usage.summary', {
              cost: dollars(c.cost),
              input: tokens(c.input + c.cache_read + c.cache_write),
              cached: tokens(c.cache_read),
              output: tokens(c.output),
              last: moment(c.last.replace(' ', 'T') + 'Z'),
            })}
          </div>
          <div className="table-scroll">
            <table>
              {head(t('usage.lesson'))}
              <tbody>
                {c.lessons.map((l) => (
                  <tr key={l.id ?? 'none'}>
                    <td dir="auto">{l.title ?? t('usage.noLesson')}</td>
                    {cells(l)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary className="small">{t('usage.byKind')}</summary>
            <div className="table-scroll">
              <table>
                {head(t('usage.kind'))}
                <tbody>
                  {c.kinds.map((k) => (
                    <tr key={k.kind}>
                      <td>{t(`usage.kinds.${k.kind}`, { defaultValue: k.kind })}</td>
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
