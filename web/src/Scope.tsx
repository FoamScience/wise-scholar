import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { CourseDetail } from './course'
import { textDirection } from './text'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

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
    <form className="block space-y-2 border-t border-border pt-6" onSubmit={submit}>
      <div className="text-sm leading-snug font-medium text-ink-2">{t('scope.label')}</div>
      <Label htmlFor="scope-details" className="text-base leading-normal font-normal">{t('scope.details')}</Label>
      <Textarea
        id="scope-details"
        className="min-h-24 py-3"
        dir="auto"
        rows={3}
        maxLength={2000}
        value={details}
        placeholder={t('scope.detailsHint')}
        onChange={(e) => setDetails(e.target.value)}
      />
      <Label htmlFor="scope-hours" className="text-base leading-normal font-normal">{t('scope.hours')}</Label>
      <Input id="scope-hours" className="max-w-40" type="number" min={1} max={5000} step={1} value={hours} onChange={(e) => setHours(e.target.value)} />
      <div className="text-sm text-muted-foreground">{t('scope.help')}</div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={props.disabled || starting}>
          {t('scope.start')}
        </Button>
      </div>
    </form>
  )
}

/** The scope a course was started with, above its interview. Nothing when the learner gave none. */
export function ScopeCard({ course }: { course: Pick<CourseDetail, 'details' | 'hours'> }) {
  const { t } = useTranslation()
  if (!course.details && !course.hours) return null
  return (
    <section className="block space-y-2 border-t border-border pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">{t('scope.summary')}</div>
      {course.details && <div dir={textDirection(course.details)}>{course.details}</div>}
      {!!course.hours && <div className="text-muted-foreground">{t('scope.planned', { count: course.hours })}</div>}
    </section>
  )
}
