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
    <section className="today">
      <h2>{t('today.heading')}</h2>
      <ol className="plan-steps">
        {plan.due > 0 && (
          <li>
            {t('today.reviews', { count: plan.warmup })} <span className="muted">{t('today.reviewMinutes', { minutes: Math.max(1, plan.review_minutes) })}</span>
          </li>
        )}
        {unit && (
          <li>
            {t('today.unit', { topic: unit.topic, title: unitTitle(unit, t) })} <span className="muted">{t('today.restOfSitting')}</span>
          </li>
        )}
        {plan.units.slice(1, 4).map((u) => (
          <li key={u.course_id} className="muted">
            {t('today.later', { title: unitTitle(u, t) })} <span className="muted">{u.topic}</span>
          </li>
        ))}
        {plan.cast && (
          <li className="muted">
            {t('today.castReady')} <a href={`#/course/${plan.cast.course_id}`}>{plan.cast.title}</a>
          </li>
        )}
        {plan.extras.map((x) => (
          <li key={`${x.course_id}-${x.kind}`} className="muted">
            <a href={`#/course/${x.course_id}?start=${x.kind}`}>
              {x.kind === 'episode' ? t('today.nextEpisode', { topic: x.topic }) : t('today.writingSession', { topic: x.topic })}
            </a>{' '}
            {t('today.strandBehind')}
          </li>
        ))}
        {plan.errors > 0 && (
          <li className="muted">
            <a href="#/errors">{t('today.errors', { count: plan.errors })}</a>
          </li>
        )}
      </ol>
      <div className="row">
        <a className="btn primary as-link" href={start}>
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
      <form className="topic-form" onSubmit={start}>
        <label htmlFor="topic">{t('home.topicLabel')}</label>
        <div className="row">
          <input
            id="topic"
            className="field" dir="auto"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={placeholder}
          />
          <button className="btn primary" disabled={!topic.trim() || starting !== ''}>
            {starting ? t('home.starting') : t('common.start')}
          </button>
        </div>
        <div className="muted">{t('home.topicHelp')}</div>
        <div className="topic-more">
          <button type="button" className="link" disabled={starting !== ''} title={t('home.importHelp')} onClick={() => bundlePicker.current?.click()}>
            {t('home.import')}
          </button>
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
          <details className="materials">
            <summary className="link">{t('home.materials')}</summary>
            <div className="stack">
              <div className="muted">{t('home.materialsHelp')}</div>
              <div className="row">
                <button type="button" className="btn" onClick={() => picker.current?.click()}>
                  {t('sources.add')}
                </button>
                <span className="small grow">{materials.map((f) => f.name).join(', ')}</span>
              </div>
              <input
                ref={picker}
                type="file"
                multiple
                hidden
                accept={SOURCE_TYPES}
                onChange={(e) => setMaterials(Array.from(e.target.files ?? []))}
              />
              <input
                className="field"
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
        {starting && <div className="small">{starting}</div>}
      </form>
  )

  return (
    <main className={teacher ? 'home' : 'home desk'}>
      <div className="desk-main">
        {error && <div className="error">{error}</div>}
        {teacher ? (
          form
        ) : (
          <div className="desk-top">
            <Today profile={profile} />
            {form}
          </div>
        )}
        {active.length > 0 && (
          <section className="stack">
            <h2>{t('home.courses')}</h2>
            <div className="courses">
              {active.map((c) => (
                <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} onRename={rename} />
              ))}
            </div>
          </section>
        )}
        {archived.length > 0 && (
          <details className="archived">
            <summary className="label">{t('home.archived', { n: archived.length })}</summary>
            <div className="courses">
              {archived.map((c) => (
                <CourseCard key={c.id} course={c} onArchive={archive} onDelete={remove} onDuplicate={duplicate} onRename={rename} />
              ))}
            </div>
          </details>
        )}
      </div>
      {!teacher && (
        <aside className="desk-side">
          <ReviewPanels profile={profile} />
        </aside>
      )}
    </main>
  )
}

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
    <div className="course-card">
      <a href={`#/course/${course.id}`}>
        {course.cover ? <img className="cover" src={`/api/courses/${course.id}/cover`} alt={course.cover_alt ?? ''} /> : <span className="cover" aria-hidden="true" />}
        <strong dir="auto">
          {course.topic}
          {course.mode === 'teacher' && <span className="chip">{t('home.prepared')}</span>}
        </strong>
        <span className="muted">{course.mechanism ? lookup(`playbooks.${course.mechanism}.title`, course.mechanism) : t('home.interviewOpen')}</span>
      </a>
      {course.finished && (
        <div className="card-recap small">
          <a href={`#/course/${course.id}/recap`}>{t('recap.cardLine', { date: day(course.finished) })}</a>
        </div>
      )}
      <details ref={menu} className="menu" name="course-menu" onToggle={() => setNaming(null)}>
        <summary aria-label={t('home.options', { topic: course.topic })}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="12" cy="5" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="12" cy="19" r="2" />
          </svg>
        </summary>
        <div className="menu-panel">
          {naming !== null ? (
            <form className="name-form" onSubmit={rename}>
              <label htmlFor={`rename-${course.id}`}>{t('home.renameLabel', { topic: course.topic })}</label>
              <input id={`rename-${course.id}`} className="field" dir="auto" maxLength={200} value={naming} onChange={(e) => setNaming(e.target.value)} autoFocus />
              <div className="row">
                <button className="btn primary" disabled={!naming.trim() || naming.trim() === course.topic}>
                  {t('home.save')}
                </button>
                <button type="button" className="btn" onClick={close}>
                  {t('common.cancel')}
                </button>
              </div>
            </form>
          ) : (
            <>
              <button type="button" className="btn" onClick={() => setNaming(course.topic)}>
                {t('home.rename')}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  close()
                  props.onArchive(course, !course.archived)
                }}
              >
                {course.archived ? t('home.unarchive') : t('home.archive')}
              </button>
              {course.mode === 'teacher' && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    close()
                    props.onDuplicate(course)
                  }}
                >
                  {t('home.duplicate')}
                </button>
              )}
              <button
                type="button"
                className="btn"
                onClick={() => {
                  close()
                  setConfirming(true)
                }}
              >
                {t('home.delete')}
              </button>
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
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  return (
    <dialog ref={dialog} className="confirm" onClose={props.onClose}>
      <p dir="auto">{t('home.deleteConfirm', { topic: props.topic })}</p>
      <form method="dialog" className="row">
        <button className="btn" autoFocus>
          {t('common.cancel')}
        </button>
        <button
          type="button"
          className="btn danger"
          onClick={() => {
            props.onDelete()
            dialog.current?.close()
          }}
        >
          {t('home.deleteCourse')}
        </button>
      </form>
    </dialog>
  )
}
