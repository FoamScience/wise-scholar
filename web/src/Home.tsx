import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, failure } from './api'
import { day, lookup } from './i18n'
import { ReviewPanels } from './Quiz'
import { type TodayPlan, unitTitle } from './course'
import type { Course } from './course'
import { SOURCE_TYPES } from './Sources'
import { useSuggestedPlaceholder } from './suggestedPlaceholder'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from 'cn'

const alert = 'rounded-md bg-warm-tint px-4 py-2 text-warm-ink'
const courseGrid = 'grid grid-cols-[repeat(auto-fill,minmax(min(100%,15rem),1fr))] gap-3'
const step = 'grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2 py-2 [counter-increment:step] before:row-span-2 before:text-muted-foreground before:tabular-nums before:content-[counter(step)]'
const now = cn(step, 'text-lg leading-snug font-medium before:text-primary')
const later = cn('later text-sm', step, 'text-muted-foreground')
const aside = 'col-start-2 text-sm font-normal text-muted-foreground'

function unitHash(u: TodayPlan['units'][number]): string {
  return u.concept_id === null ? `#/course/${u.course_id}` : `#/course/${u.course_id}?concept=${u.concept_id}`
}

/** The sitting as one plan: reviews first, then the next unit. Start walks through both. */
function Today({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState<TodayPlan | null>(null)
  useEffect(() => {
    api<TodayPlan>(`/api/today?profile=${profile}`).then(setPlan, () => {})
  }, [profile])
  if (!plan || (plan.due === 0 && plan.units.length === 0)) return null
  const unit = plan.units[0]
  // a review with somewhere to go next is the sitting's warm-up, capped; the review page holds the rest
  const start = plan.warmup > 0 ? `#/review?then=${encodeURIComponent(unit ? unitHash(unit) : '#/')}` : unit ? unitHash(unit) : '#/review'
  return (
    <section className="today flex flex-col gap-4 rounded-lg bg-muted p-6">
      <h2 className="m-0">{t('today.heading')}</h2>
      <ol className="plan-steps m-0 flex list-none flex-col p-0 [counter-reset:step]">
        {plan.due > 0 && (
          <li className={now}>
            {t('today.reviews', { count: plan.warmup })} <span className={aside}>{t('today.reviewMinutes', { minutes: Math.max(1, plan.review_minutes) })}</span>
          </li>
        )}
        {unit && (
          <li className={now}>
            {t('today.unit', { topic: unit.topic, title: unitTitle(unit, t) })} <span className={aside}>{t('today.restOfSitting')}</span>
          </li>
        )}
        {plan.units.slice(1, 4).map((u) => (
          <li key={u.course_id} className={later}>
            {t('today.later', { title: unitTitle(u, t) })} <span className={aside}>{u.topic}</span>
          </li>
        ))}
        {plan.cast && (
          <li className={later}>
            {t('today.castReady')} <a href={`#/course/${plan.cast.course_id}`}>{plan.cast.title}</a>
          </li>
        )}
        {plan.extras.map((x) => (
          <li key={`${x.course_id}-${x.kind}`} className={later}>
            <a href={`#/course/${x.course_id}?start=${x.kind}`}>
              {x.kind === 'episode' ? t('today.nextEpisode', { topic: x.topic }) : t('today.writingSession', { topic: x.topic })}
            </a>{' '}
            {t('today.strandBehind')}
          </li>
        ))}
        {plan.errors > 0 && (
          <li className={later}>
            <a href="#/errors">{t('today.errors', { count: plan.errors })}</a>
          </li>
        )}
      </ol>
      <div className="flex">
        <a className={cn(buttonVariants(), 'px-10')} href={start}>
          {t('common.start')}
        </a>
      </div>
    </section>
  )
}

export function Home({ profile, teacher }: { profile: number; teacher: boolean }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState<Course[]>([])
  const [topic, setTopic] = useState('')
  const [materials, setMaterials] = useState<File[]>([])
  const [url, setUrl] = useState('')
  const [starting, setStarting] = useState('')
  const picker = useRef<HTMLInputElement | null>(null)
  const bundlePicker = useRef<HTMLInputElement | null>(null)
  const [error, setError] = useState('')
  const placeholder = useSuggestedPlaceholder(profile, !teacher, topic !== '', t('home.topicPlaceholder'))

  useEffect(() => {
    api<Course[]>(`/api/courses?profile=${profile}`).then((all) => {
      setCourses(all)
      // a course without a cover gets one drawn out of sight; the server starts nothing for one without a map
      for (const c of all) if (!c.cover) api(`/api/courses/${c.id}/cover`, {}).catch(() => {})
    }, (e) => setError(e.message))
  }, [profile])

  async function start(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const course = await api<Course>('/api/courses', { topic, profile_id: profile })
      // Materials go in before the interview, so its first turn already knows them.
      for (const file of materials) {
        setStarting(t('home.adding', { name: file.name }))
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(`/api/courses/${course.id}/sources`, { method: 'POST', body: form })
        if (!res.ok) throw await failure(res)
      }
      if (url.trim()) {
        setStarting(t('home.adding', { name: url.trim() }))
        await api(`/api/courses/${course.id}/sources/url`, { url: url.trim() })
      }
      location.hash = `#/course/${course.id}`
    } catch (err) {
      setError((err as Error).message)
      // The course may exist by now: show it in the list rather than inviting a second Start.
      api<Course[]>(`/api/courses?profile=${profile}`).then(setCourses, () => {})
      setTopic('')
      setMaterials([])
      setUrl('')
    } finally {
      setStarting('')
    }
  }

  async function importBundle(file: File) {
    setError('')
    setStarting(t('home.importing', { name: file.name }))
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`/api/import?profile=${profile}`, { method: 'POST', body: form })
      if (!res.ok) throw await failure(res)
      const course = (await res.json()) as Course
      location.hash = `#/course/${course.id}`
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting('')
    }
  }

  function archive(course: Course, archived: boolean) {
    api(`/api/courses/${course.id}/archive`, { archived }).then(
      () => setCourses((all) => all.map((c) => (c.id === course.id ? { ...c, archived: Number(archived) } : c))),
      (err: Error) => setError(err.message),
    )
  }

  function remove(course: Course) {
    api(`/api/courses/${course.id}/delete`, {}).then(
      () => setCourses((all) => all.filter((c) => c.id !== course.id)),
      (err: Error) => setError(err.message),
    )
  }

  function rename(course: Course, topic: string) {
    return api<Course>(`/api/courses/${course.id}/rename`, { topic }).then(
      (renamed) => setCourses((all) => all.map((c) => (c.id === course.id ? { ...c, topic: renamed.topic } : c))),
      (err: Error) => setError(err.message),
    )
  }

  function duplicate(course: Course) {
    api<Course>(`/api/courses/${course.id}/duplicate`, {}).then(
      (copy) => setCourses((all) => [copy, ...all]),
      (err: Error) => setError(err.message),
    )
  }

  const active = courses.filter((c) => !c.archived)
  const archived = courses.filter((c) => c.archived)

  const form = (
      <form className={cn('flex max-w-(--measure) flex-col gap-3', !teacher && 'rounded-lg border border-border p-6')} onSubmit={start}>
        <Label htmlFor="topic" className="text-lg leading-snug">{t('home.topicLabel')}</Label>
        <div className="flex gap-2">
          <Input
            id="topic"
            className="h-12 min-w-0 grow placeholder-shown:text-ellipsis" dir="auto"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={placeholder}
          />
          <Button type="submit" className="h-12" disabled={!topic.trim() || starting !== ''}>
            {starting ? t('home.starting') : t('common.start')}
          </Button>
        </div>
        <div className="text-sm text-muted-foreground">{t('home.topicHelp')}</div>
        <div className="flex flex-wrap items-center gap-x-4 border-t border-border pt-2">
          <Button type="button" variant="ghost" className="-ms-3 text-ink-2" disabled={starting !== ''} title={t('home.importHelp')} onClick={() => bundlePicker.current?.click()}>
            {t('home.import')}
          </Button>
          <input
            ref={bundlePicker}
            type="file"
            hidden
            accept=".zip,application/zip"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) importBundle(file)
            }}
          />
          <details className="open:basis-full">
            <summary className="-ms-3 flex h-11 w-fit cursor-pointer list-none items-center rounded-md px-3 font-medium text-ink-2 hover:bg-muted hover:text-foreground [&::-webkit-details-marker]:hidden">{t('home.materials')}</summary>
            <div className="flex flex-col gap-3">
              <div className="text-sm text-muted-foreground">{t('home.materialsHelp')}</div>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="outline" onClick={() => picker.current?.click()}>
                  {t('sources.add')}
                </Button>
                <span className="grow text-sm text-muted-foreground">{materials.map((f) => f.name).join(', ')}</span>
              </div>
              <input
                ref={picker}
                type="file"
                multiple
                hidden
                accept={SOURCE_TYPES}
                onChange={(e) => setMaterials(Array.from(e.target.files ?? []))}
              />
              <Input
                type="text"
                inputMode="url"
                dir="ltr"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={t('home.urlPlaceholder')}
              />
            </div>
          </details>
        </div>
        {starting && <div className="text-sm text-muted-foreground">{starting}</div>}
      </form>
  )

  return (
    <main className={cn('mx-auto w-full gap-10 px-6 pt-10 pb-16', teacher ? 'flex max-w-(--measure) flex-col' : 'grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-x-16')}>
      <div className="flex min-w-0 flex-col gap-10">
        {error && <div className={alert}>{error}</div>}
        {teacher ? (
          form
        ) : (
          <div className="grid grid-cols-1 items-start gap-6 md:has-[>.today]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Today profile={profile} />
            {form}
          </div>
        )}
        {active.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="m-0">{t('home.courses')}</h2>
            <div className={courseGrid}>
              {active.map((c) => (
                <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} onRename={rename} />
              ))}
            </div>
          </section>
        )}
        {archived.length > 0 && (
          <details className="group/archived">
            <summary className="flex min-h-11 cursor-pointer items-center text-sm leading-snug font-medium text-ink-2">{t('home.archived', { n: archived.length })}</summary>
            <div className={courseGrid}>
              {archived.map((c) => (
                <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} onRename={rename} />
              ))}
            </div>
          </details>
        )}
      </div>
      {!teacher && (
        <aside className="flex min-w-0 flex-col gap-6 lg:sticky lg:top-6">
          <ReviewPanels profile={profile} />
        </aside>
      )}
    </main>
  )
}

const cover = 'mb-2 block aspect-video w-full rounded-t-lg border-b border-border bg-accent object-cover'

function CourseCard(props: {
  course: Course
  onArchive: (course: Course, archived: boolean) => void
  onDelete: (course: Course) => void
  onDuplicate: (course: Course) => void
  onRename: (course: Course, topic: string) => Promise<void>
}) {
  const { course } = props
  const { t } = useTranslation()
  const [confirming, setConfirming] = useState(false)
  const [naming, setNaming] = useState<string | null>(null)
  const menu = useRef<HTMLDetailsElement>(null)

  function close() {
    setNaming(null)
    if (menu.current) menu.current.open = false
  }

  function rename(e: FormEvent) {
    e.preventDefault()
    if (naming?.trim()) props.onRename(course, naming.trim()).then(close)
  }

  return (
    <div className="relative flex flex-col rounded-lg border border-border bg-card transition-colors duration-[var(--dur-micro)] focus-within:border-input hover:border-input group-open/archived:bg-transparent">
      <a href={`#/course/${course.id}`} className="flex flex-1 flex-col gap-1 rounded-lg pb-4 text-foreground no-underline">
        {course.cover ? <img className={cover} src={`/api/courses/${course.id}/cover`} alt={course.cover_alt ?? ''} /> : <span className={cover} aria-hidden="true" />}
        <strong dir="auto" className="px-4 text-base leading-snug font-medium">
          {course.topic}
          {course.mode === 'teacher' && <Badge variant="secondary" className="ms-2 h-auto rounded-sm bg-accent px-2 py-0.5 text-sm align-[1px] text-accent-foreground">{t('home.prepared')}</Badge>}
        </strong>
        <span className="px-4 text-sm text-muted-foreground">{course.mechanism ? lookup(`playbooks.${course.mechanism}.title`, course.mechanism) : t('home.interviewOpen')}</span>
      </a>
      {course.finished && (
        <div className="-mt-2 px-4 pb-4 text-sm text-muted-foreground">
          <a href={`#/course/${course.id}/recap`}>{t('recap.cardLine', { date: day(course.finished) })}</a>
        </div>
      )}
      <details ref={menu} className="group/menu absolute end-2 top-2" name="course-menu" onToggle={() => setNaming(null)}>
        <summary className="flex size-11 cursor-pointer list-none items-center justify-center rounded-md bg-card text-muted-foreground shadow-[0_1px_2px_var(--color-shadow)] group-open/menu:bg-muted group-open/menu:text-foreground hover:bg-muted hover:text-foreground [&::-webkit-details-marker]:hidden" aria-label={t('home.options', { topic: course.topic })}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="12" cy="5" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="12" cy="19" r="2" />
          </svg>
        </summary>
        <div className="absolute end-0 top-12 z-(--z-dropdown) flex w-60 flex-col gap-2 rounded-lg bg-card p-3 shadow-float">
          {naming !== null ? (
            <form className="flex flex-col gap-2" onSubmit={rename}>
              <Label htmlFor={`rename-${course.id}`}>{t('home.renameLabel', { topic: course.topic })}</Label>
              <Input id={`rename-${course.id}`} dir="auto" maxLength={200} value={naming} onChange={(e) => setNaming(e.target.value)} autoFocus />
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={!naming.trim() || naming.trim() === course.topic}>
                  {t('home.save')}
                </Button>
                <Button type="button" variant="outline" onClick={close}>
                  {t('common.cancel')}
                </Button>
              </div>
            </form>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={() => setNaming(course.topic)}>
                {t('home.rename')}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  close()
                  props.onArchive(course, !course.archived)
                }}
              >
                {course.archived ? t('home.unarchive') : t('home.archive')}
              </Button>
              {course.mode === 'teacher' && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    close()
                    props.onDuplicate(course)
                  }}
                >
                  {t('home.duplicate')}
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  close()
                  setConfirming(true)
                }}
              >
                {t('home.delete')}
              </Button>
            </>
          )}
        </div>
      </details>
      {confirming && <ConfirmDelete topic={course.topic} onDelete={() => props.onDelete(course)} onClose={() => setConfirming(false)} />}
    </div>
  )
}

function ConfirmDelete(props: { topic: string; onDelete: () => void; onClose: () => void }) {
  const { t } = useTranslation()

  return (
    <Dialog open onOpenChange={(open) => !open && props.onClose()}>
      <DialogContent showCloseButton={false} className="p-6 sm:max-w-96">
        <DialogTitle dir="auto" className="text-base leading-normal font-normal">
          {t('home.deleteConfirm', { topic: props.topic })}
        </DialogTitle>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <DialogClose render={<Button variant="outline" autoFocus />}>{t('common.cancel')}</DialogClose>
          <Button
            type="button"
            className="h-11 bg-destructive px-4 text-base text-primary-foreground hover:bg-destructive/90"
            onClick={() => {
              props.onDelete()
              props.onClose()
            }}
          >
            {t('home.deleteCourse')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
