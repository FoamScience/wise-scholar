import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { CourseDetail } from './course'
import { textDirection } from './text'

export type Scope = { details: string; hours: number | null }

/** Shown on a new course before its interview: what the course should cover and how much teaching time it gets. Both optional. */
export function ScopeForm(props: { disabled: boolean; onStart: (scope: Scope) => Promise<void> }) {
  const { t } = useTranslation()
  const [details, setDetails] = useState('')
  const [hours, setHours] = useState('')
  const [starting, setStarting] = useState(false)

  function submit(e: FormEvent) {
    e.preventDefault()
    setStarting(true)
    props.onStart({ details: details.trim(), hours: hours ? Number(hours) : null }).finally(() => setStarting(false))
  }

  return (
    <form className="block scope" onSubmit={submit}>
      <div className="label">{t('scope.label')}</div>
      <label htmlFor="scope-details">{t('scope.details')}</label>
      <textarea
        id="scope-details"
        className="field"
        dir="auto"
        rows={3}
        maxLength={2000}
        value={details}
        placeholder={t('scope.detailsHint')}
        onChange={(e) => setDetails(e.target.value)}
      />
      <label htmlFor="scope-hours">{t('scope.hours')}</label>
      <input id="scope-hours" className="field" type="number" min={1} max={5000} step={1} value={hours} onChange={(e) => setHours(e.target.value)} />
      <div className="small">{t('scope.help')}</div>
      <div className="row">
        <button className="btn primary" disabled={props.disabled || starting}>
          {t('scope.start')}
        </button>
      </div>
    </form>
  )
}

/** The scope a course was started with, above its interview. Nothing when the learner gave none. */
export function ScopeCard({ course }: { course: Pick<CourseDetail, 'details' | 'hours'> }) {
  const { t } = useTranslation()
  if (!course.details && !course.hours) return null
  return (
    <section className="block scope">
      <div className="label">{t('scope.summary')}</div>
      {course.details && <div dir={textDirection(course.details)}>{course.details}</div>}
      {!!course.hours && <div className="muted">{t('scope.planned', { count: course.hours })}</div>}
    </section>
  )
}
