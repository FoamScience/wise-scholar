import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { type Concept, type CourseDetail, type Lesson, practiceTitle, unitDone } from './course'
import { conceptStats } from './mapStats'
import { day } from './i18n'
import { type Source, SourcesPanel } from './Sources'
import { Button, buttonVariants } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Toggle } from '@/components/ui/toggle'
import { cn } from 'cn'

const SMALL = 'text-sm text-muted-foreground'
const MENU_ITEM = 'w-full justify-start'
/** A lesson or unit in the map's list. */
export const MAP_ROW =
  'min-h-11 rounded-md bg-transparent px-3 text-start leading-[1.35] hover:enabled:bg-paper-3 aria-[current=true]:bg-card aria-[current=true]:font-semibold aria-[current=true]:text-accent-foreground aria-[current=true]:ring-1 aria-[current=true]:ring-border'
const MENU_LINK = cn(buttonVariants({ variant: 'outline' }), MENU_ITEM)
const DISCLOSURE = "list-none [&::-webkit-details-marker]:hidden after:content-['▾'_/_'']"

const DONE_MARK = 'inline-flex size-4.5 items-center justify-center rounded-full bg-primary text-xs leading-none font-semibold text-primary-foreground'
const HELD = 'mt-1 mb-2 rounded-md bg-warm-tint p-3 text-sm text-muted-foreground'

function squares(concept: Concept): number {
  return Math.round((concept.mastery ?? 0) * 3)
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
    <details ref={menu} className="side-menu group/menu">
      <summary className={cn(buttonVariants({ variant: 'outline' }), 'w-full justify-between', DISCLOSURE, "group-open/menu:after:content-['▴'_/_'']")}>
        {t('map.menu')}
      </summary>
      <div className="flex flex-col gap-2 pt-3 pb-1">
        <a className={MENU_LINK} href={`#/course/${course.id}/book`}>
          {t('book.export')}
        </a>
        <a className={MENU_LINK} href={`/api/courses/${course.id}/obsidian.zip`} download>
          {t('book.obsidian')}
        </a>
        <a className={MENU_LINK} href={`#/course/${course.id}/publish`}>
          {t('publish.link')}
        </a>
        {course.mode === 'learner' && (
          <a className={MENU_LINK} href={`#/graph?course=${course.id}`}>
            {t('graph.courseLink')}
          </a>
        )}
        {course.concepts.length > 0 && (
          <Button
            type="button"
            variant="outline"
            className={MENU_ITEM}
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
          </Button>
        )}
        {course.concepts.length > 0 && (
          <Button
            type="button"
            variant="outline"
            className={MENU_ITEM}
            disabled={props.running}
            onClick={() => {
              close()
              props.onChangeMap()
            }}
          >
            {t('map.change')}
          </Button>
        )}
        {course.mode !== 'teacher' && (
          <>
            <div className="flex gap-2" role="group" aria-label={t('pace.label')}>
              {(['momentum', 'speed'] as const).map((pace) => (
                <Toggle
                  key={pace}
                  variant="outline"
                  className="h-11 border-border px-3 text-base font-normal aria-pressed:border-primary aria-pressed:bg-accent"
                  pressed={course.pace === pace}
                  onClick={() => props.onPace(pace)}
                >
                  {t(`pace.${pace}`)}
                </Toggle>
              ))}
            </div>
            <div className={SMALL}>{t(`pace.${course.pace}Hint`)}</div>
          </>
        )}
        {course.cleaned && <div className={SMALL}>{t('map.cleaned', { date: day(course.cleaned) })}</div>}
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
      className="group/module flex flex-col gap-2"
      open={open}
      onToggle={(e) => {
        const now = e.currentTarget.open
        if (now !== open) props.onToggle(now)
      }}
    >
      <summary
        className={cn(
          'mt-2 grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 rounded-md px-3 py-1 hover:bg-card',
          DISCLOSURE,
          "after:col-start-2 after:row-start-1 after:text-muted-foreground group-open/module:after:content-['▴'_/_'']",
        )}
      >
        <strong dir="auto">{module}</strong>
        {projects.map((k) => (
          <div key={k.id} className="col-span-full mt-0.5 mb-2 flex flex-col gap-0.5" title={k.brief}>
            <span className={SMALL}>{t('map.project', { title: k.title })}</span>
            <Progress
              value={k.done}
              max={k.milestones.length}
              className={cn('*:data-[slot=progress-track]:h-1.5 *:data-[slot=progress-track]:bg-paper-3', k.done === k.milestones.length ? '**:data-[slot=progress-indicator]:bg-success' : '**:data-[slot=progress-indicator]:bg-spark')}
            />
            <span className={SMALL}>{t('map.milestones', { done: k.done, total: k.milestones.length })}</span>
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
    <div className="flex flex-col gap-1">
      <button className={cn(MAP_ROW, 'flex flex-col justify-center gap-0.5 py-2')} aria-current={conceptLesson?.id === props.current} onClick={() => props.onOpen(c)}>
        <span className="flex items-start justify-between gap-3">
          <span className="min-w-0 wrap-anywhere" dir="auto">{c.kind === 'practice' ? practiceTitle(c.title, t) : c.title}</span>
          {course.mode !== 'teacher' && <UnitMarks concept={c} lesson={conceptLesson} />}
        </span>
        <span className="text-xs font-normal text-muted-foreground">{c.unwritten && !conceptLesson ? t('replay.laterShort') : conceptStats(c, conceptLesson, t, course.mode === 'teacher')}</span>
        {c.needs.length > 0 && !unitDone(c, conceptLesson) && <UnitNeeds {...props} />}
      </button>
      {props.held === c.id && <HeldNote {...props} />}
    </div>
  )
}

function UnitMarks({ concept: c, lesson }: { concept: Concept; lesson: Lesson | undefined }) {
  const { t } = useTranslation()
  return (
    <span className="flex h-lh shrink-0 items-center gap-1">
      {/* the slot stays when empty, so every unit's squares sit in the same place */}
      {unitDone(c, lesson) ? (
        <span className={cn(DONE_MARK, 'transition-[opacity,scale] duration-(--motion) ease-(--ease)')} role="img" aria-label={t('common.done')}>
          ✓
        </span>
      ) : (
        <span className={cn(DONE_MARK, 'invisible scale-60 opacity-0')} />
      )}
      {c.kind !== 'practice' && (
        <span className="flex shrink-0 gap-1" aria-label={t('map.mastery', { n: squares(c) })} title={t('map.masteryHint')}>
          {[1, 2, 3].map((n) => (
            <i key={n} className={cn('size-2.5 transition-colors duration-(--motion) ease-(--ease)', n <= squares(c) ? 'bg-primary' : 'bg-off')} />
          ))}
        </span>
      )}
    </span>
  )
}

/** The units this one builds on; on a learner's map, each marked open or done. */
function UnitNeeds(props: UnitProps & { concept: Concept }) {
  const { t } = useTranslation()
  const { course, concept: c } = props
  return (
    <span className="text-xs font-normal text-muted-foreground" dir="auto">
      {t('map.needs')}{' '}
      {c.needs
        .map((id) => course.concepts.find((u) => u.id === id))
        .filter((u): u is Concept => u !== undefined)
        .map((u) => (course.mode === 'teacher' ? u.title : `${u.title} ${props.unmetNeeds(c).includes(u) ? '✗' : '✓'}`))
        .join(', ')}
    </span>
  )
}

/** Why a unit asked for did not start: it is not written yet, or units it needs are still open. */
function HeldNote(props: UnitProps & { concept: Concept; lesson: Lesson | undefined }) {
  const { t } = useTranslation()
  const { concept: c } = props
  if (c.unwritten && !props.lesson)
    return (
      <div className={HELD} role="status">
        <span>{t('replay.later')}</span>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button type="button" onClick={() => props.onOpen(c, true)}>
            {t('replay.teachNow')}
          </Button>
        </div>
      </div>
    )
  return (
    <div className={HELD} role="status">
      <span dir="auto">{t('map.needsFirst', { titles: props.unmetNeeds(c).map((u) => u.title).join(', ') })}</span>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => props.onOpen(props.unmetNeeds(c)[0])}>
          {t('map.openFirst')}
        </Button>
        <Button type="button" variant="outline" onClick={() => props.onOpen(c, true)}>
          {t('map.startAnyway')}
        </Button>
      </div>
    </div>
  )
}
