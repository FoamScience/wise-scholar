import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { api } from './api'
import { type ChallengeData, type Concept, type CourseDetail, type Lesson, outlineOf, practiceTitle, unitDone } from './course'
import { day } from './i18n'
import { type Source, SourcesPanel } from './Sources'

function squares(concept: Concept): number {
  return Math.round((concept.mastery ?? 0) * 3)
}

function conceptStats(concept: Concept, lesson: Lesson | undefined, t: TFunction, prepared = false): string {
  if (prepared) return !lesson ? t('map.notPlanned') : lesson.blocks.some((b) => b.kind === 'done') ? t('map.planned') : t('map.drafting')
  const due = concept.due ? t('map.reviewDue', { count: concept.due }) : ''
  if (!lesson) return [concept.known ? t('map.placedOut') : t('map.notStarted'), due].filter(Boolean).join(', ')
  if (concept.kind === 'practice') return lesson.blocks.some((b) => b.kind === 'done') ? t('common.done') : t('map.started')
  const outline = outlineOf(lesson)
  const where = unitDone(concept, lesson)
    ? t('common.done')
    : outline && outline.at < outline.steps.length
      ? t('outline.step', { n: outline.at + 1, total: outline.steps.length })
      : ''
  const cs = lesson.blocks
    .filter((b) => b.kind === 'challenge' || b.kind === 'exercise' || b.kind === 'speaking')
    .map((b) => b.data as ChallengeData)
  if (cs.length === 0) return [where || t('map.started'), due].filter(Boolean).join(', ')
  const hints = cs.reduce((n, c) => n + c.hints.length, 0)
  const gaveUp = cs.filter((c) => c.gave_up).length
  return [
    where,
    t('map.solved', { solved: cs.filter((c) => c.solved).length, total: cs.length }),
    hints > 0 && t('map.hints', { count: hints }),
    gaveUp > 0 && t('map.gaveUp', { n: gaveUp }),
    due,
  ]
    .filter(Boolean)
    .join(', ')
}

/** The course's menu: exports, placement, changing the map, pace and the learner's materials. */
export function SideMenu(props: {
  course: CourseDetail
  running: boolean
  sources: Source[]
  onSources: (sources: Source[]) => void
  onError: (message: string) => void
  onLesson: (created: Lesson) => void
  onChangeMap: () => void
  onPace: (pace: 'momentum' | 'speed') => void
}) {
  const { t } = useTranslation()
  const { course } = props
  const menu = useRef<HTMLDetailsElement>(null)
  const close = () => {
    menu.current!.open = false
  }
  return (
    <details ref={menu} className="side-menu">
      <summary className="btn">{t('map.menu')}</summary>
      <div className="side-menu-panel">
        <a className="btn as-link" href={`#/course/${course.id}/book`}>
          {t('book.export')}
        </a>
        <a className="btn as-link" href={`/api/courses/${course.id}/obsidian.zip`} download>
          {t('book.obsidian')}
        </a>
        <a className="btn as-link" href={`#/course/${course.id}/publish`}>
          {t('publish.link')}
        </a>
        {course.mode === 'learner' && (
          <a className="btn as-link" href={`#/graph?course=${course.id}`}>
            {t('graph.courseLink')}
          </a>
        )}
        {course.concepts.length > 0 && (
          <button
            type="button"
            className="btn"
            disabled={props.running}
            onClick={() =>
              api<Lesson>(`/api/courses/${course.id}/placement/${course.mode === 'replay' ? 'cards' : 'retake'}`, {}).then(
                (created) => {
                  props.onLesson(created)
                  close()
                },
                (err: Error) => props.onError(err.message),
              )
            }
          >
            {course.mode === 'replay' ? t('replay.place') : course.level ? t('map.retake') : t('map.take')}
          </button>
        )}
        {course.concepts.length > 0 && (
          <button
            type="button"
            className="btn"
            disabled={props.running}
            onClick={() => {
              close()
              props.onChangeMap()
            }}
          >
            {t('map.change')}
          </button>
        )}
        {course.mode !== 'teacher' && (
          <>
            <div className="pace" role="group" aria-label={t('pace.label')}>
              {(['momentum', 'speed'] as const).map((pace) => (
                <button
                  key={pace}
                  type="button"
                  className={course.pace === pace ? 'cat picked' : 'cat'}
                  aria-pressed={course.pace === pace}
                  onClick={() => props.onPace(pace)}
                >
                  {t(`pace.${pace}`)}
                </button>
              ))}
            </div>
            <div className="small">{t(`pace.${course.pace}Hint`)}</div>
          </>
        )}
        {course.cleaned && <div className="small muted">{t('map.cleaned', { date: day(course.cleaned) })}</div>}
        {course.concepts.length > 0 && <SourcesPanel courseId={course.id} sources={props.sources} onChange={props.onSources} onError={props.onError} />}
      </div>
    </details>
  )
}

type UnitProps = {
  course: CourseDetail
  current: number
  held: number | null
  unmetNeeds: (concept: Concept) => Concept[]
  onOpen: (concept: Concept, anyway?: boolean) => void
}

/** A run of units of one module with its projects; it folds away once finished or while untouched. */
export function ModuleGroup(props: UnitProps & { units: Concept[]; toggled: boolean | undefined; onToggle: (open: boolean) => void }) {
  const { t } = useTranslation()
  const { course, units } = props
  const module = units[0].module
  const lessonOf = (c: Concept) => course.lessons.find((l) => l.concept_id === c.id)
  const projects = course.capstones.filter((k) => k.module === module)
  const finished = units.every((c) => unitDone(c, lessonOf(c))) || (projects.length > 0 && projects.every((k) => k.done === k.milestones.length))
  const started = units.some((c) => lessonOf(c) || unitDone(c, lessonOf(c)))
  // a finished or untouched module folds away; the one holding the open lesson stays open
  const open = props.toggled ?? (units.some((c) => lessonOf(c)?.id === props.current) || (started && !finished))
  return (
    <details
      className="module"
      open={open}
      onToggle={(e) => {
        const now = e.currentTarget.open
        if (now !== open) props.onToggle(now)
      }}
    >
      <summary>
        <strong dir="auto">{module}</strong>
        {projects.map((k) => (
          <div key={k.id} className={k.done === k.milestones.length ? 'capstone done' : 'capstone'} title={k.brief}>
            <span className="small">{t('map.project', { title: k.title })}</span>
            <progress value={k.done} max={k.milestones.length} />
            <span className="small">{t('map.milestones', { done: k.done, total: k.milestones.length })}</span>
          </div>
        ))}
      </summary>
      {units.map((c) => (
        <UnitRow key={c.id} {...props} concept={c} lesson={lessonOf(c)} />
      ))}
    </details>
  )
}

function UnitRow(props: UnitProps & { concept: Concept; lesson: Lesson | undefined }) {
  const { t } = useTranslation()
  const { course, concept: c, lesson: conceptLesson } = props
  return (
    <div className="concept">
      <button aria-current={conceptLesson?.id === props.current} onClick={() => props.onOpen(c)}>
        <span className="concept-title">
          <span className="concept-name" dir="auto">{c.kind === 'practice' ? practiceTitle(c.title, t) : c.title}</span>
          {course.mode !== 'teacher' && (
            <span className="marks">
              {/* the slot stays when empty, so every unit's squares sit on the same line */}
              {unitDone(c, conceptLesson) ? (
                <span className="done-mark" role="img" aria-label={t('common.done')}>
                  ✓
                </span>
              ) : (
                <span className="done-mark empty" />
              )}
              {c.kind !== 'practice' && (
                <span className="mastery" aria-label={t('map.mastery', { n: squares(c) })} title={t('map.masteryHint')}>
                  {[1, 2, 3].map((n) => (
                    <i key={n} className={n <= squares(c) ? 'on' : ''} />
                  ))}
                </span>
              )}
            </span>
          )}
        </span>
        <span className="stats">{c.unwritten && !conceptLesson ? t('replay.laterShort') : conceptStats(c, conceptLesson, t, course.mode === 'teacher')}</span>
        {c.needs.length > 0 && !unitDone(c, conceptLesson) && (
          <span className="stats needs" dir="auto">
            {t('map.needs')}{' '}
            {c.needs
              .map((id) => course.concepts.find((u) => u.id === id))
              .filter((u): u is Concept => u !== undefined)
              .map((u) => (course.mode === 'teacher' ? u.title : `${u.title} ${props.unmetNeeds(c).includes(u) ? '✗' : '✓'}`))
              .join(', ')}
          </span>
        )}
      </button>
      {props.held === c.id && c.unwritten && !conceptLesson ? (
        <div className="held small" role="status">
          <span>{t('replay.later')}</span>
          <div className="row">
            <button type="button" className="btn primary" onClick={() => props.onOpen(c, true)}>
              {t('replay.teachNow')}
            </button>
          </div>
        </div>
      ) : (
        props.held === c.id && (
          <div className="held small" role="status">
            <span dir="auto">{t('map.needsFirst', { titles: props.unmetNeeds(c).map((u) => u.title).join(', ') })}</span>
            <div className="row">
              <button type="button" className="btn primary" onClick={() => props.onOpen(props.unmetNeeds(c)[0])}>
                {t('map.openFirst')}
              </button>
              <button type="button" className="btn" onClick={() => props.onOpen(c, true)}>
                {t('map.startAnyway')}
              </button>
            </div>
          </div>
        )
      )}
    </div>
  )
}
