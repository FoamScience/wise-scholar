import { Fragment, useEffect, useRef, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { useArrivals } from './arrive'
import { day, lookup } from './i18n'
import { useOnline } from './offline'
import type { Given } from './offline'
import type { QuizData } from './Quiz'
import { LevelPanel } from './Language'
import { lessonTitle, lessonView, moduleRuns, outlineOf, replayShown, unitDone } from './course'
import { OutlineCard } from './Outline'
import type { Block, Concept, CourseDetail, Lesson, Ranked, Resource, SetupStep } from './course'
import { ScopeCard, ScopeForm } from './Scope'
import type { Source } from './Sources'
import { MAP_ROW, ModuleGroup, SideMenu } from './CourseMap'
import { AskButton, ChatPanel, PaneSwitcher } from './Chat'
import { EditBar } from './EditBar'
import { LessonCard, PlacementResult } from './LessonCard'
import { useAnsweredToday, useChatDraft, useCourseStream, useFollow, useLessonVisits, useOfflineAnswers, useUnread, useUpgrade } from './workspaceState'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton as Bar } from '@/components/ui/skeleton'
import { cn } from 'cn'

// block stays for arrive.ts and the lesson pane's first-card rule; never pass it through cn, which drops it beside flex
const CARD = 'block border-t pt-6'
const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const ROW = 'flex flex-wrap items-center gap-2'
const LINK = 'text-primary underline decoration-current/45 hover:decoration-current'
const ERROR = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const NEXT = 'flex flex-wrap justify-center gap-2 pt-2 pb-6'
// on a phone one pane shows at a time; hidden, not display: none, so each keeps its scroll position
const PANE = 'max-md:absolute max-md:inset-x-0 max-md:top-0 max-md:bottom-13 max-md:w-auto max-md:border-0 max-md:transition-[opacity,visibility] max-md:duration-(--motion) max-md:ease-(--ease)'
const PANE_AWAY = 'max-md:pointer-events-none max-md:invisible max-md:opacity-0'

function Skeleton() {
  const { t } = useTranslation()
  return (
    <section className={`${CARD} skeleton flex flex-col gap-3`} role="status" aria-label={t('block.tutorWorking')}>
      <Bar className="h-2.5 rounded-sm bg-border" style={{ width: '22%' }} />
      <Bar className="h-3.5 rounded-sm bg-border" style={{ width: '92%' }} />
      <Bar className="h-3.5 rounded-sm bg-border" style={{ width: '78%' }} />
      <Bar className="h-3.5 rounded-sm bg-border" style={{ width: '54%' }} />
    </section>
  )
}

function Plan(props: {
  ranking: Ranked[]
  mechanism: string | null
  accepted: boolean
  disabled: boolean
  onChoose: (mechanism: string) => void
  onAccept: () => void
  onPlacement: () => void
  prepared: boolean
}) {
  const { t } = useTranslation()
  return (
    <section className="flex flex-col gap-3">
      <div className={LABEL}>{t('plan.heading')}</div>
      <RadioGroup className="gap-3" name="mechanism" value={props.mechanism} disabled={props.accepted} onValueChange={(mechanism) => props.onChoose(mechanism as string)}>
        {props.ranking.map((r, i) => (
          <label
            key={r.mechanism}
            className={cn('flex cursor-pointer gap-4 rounded-lg border bg-card p-4', r.mechanism === props.mechanism && 'border-primary bg-accent')}
          >
            <RadioGroupItem value={r.mechanism} className="mt-1" />
            <span className="flex flex-col gap-1">
              <strong>
                {i + 1}. {lookup(`playbooks.${r.mechanism}.title`, r.title)}
              </strong>
              <span dir="auto">{r.rationale}</span>
              <span className="text-muted-foreground">{lookup(`playbooks.${r.mechanism}.summary`, r.summary)}</span>
              <span className={SMALL}>
                {t('plan.evidence')}{' '}
                {r.evidence.map((e, n) => (
                  <span key={e.url}>
                    {n > 0 && '; '}
                    <a className={LINK} href={e.url} target="_blank" rel="noreferrer" title={e.finding}>
                      {e.source}
                    </a>
                  </span>
                ))}
              </span>
            </span>
          </label>
        ))}
      </RadioGroup>
      <div className="text-muted-foreground">{t('plan.always')}</div>
      {!props.accepted && (
        <div className={`${CARD} flex flex-col gap-3`}>
          <div className={LABEL}>{props.prepared ? t('plan.nextPrepared') : t('plan.next')}</div>
          <div>{props.prepared ? t('plan.preparedInfo') : t('plan.placementInfo')}</div>
          <div className={cn(ROW, 'gap-3')}>
            {!props.prepared && (
              <Button disabled={props.disabled} onClick={props.onPlacement}>
                {t('plan.startPlacement')}
              </Button>
            )}
            <Button variant={props.prepared ? 'default' : 'outline'} disabled={props.disabled} onClick={props.onAccept}>
              {props.prepared ? t('plan.accept') : t('plan.skip')}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}

/** The map's head: the level and the language panel. */
function MapHead(props: { course: CourseDetail; running: boolean; onStart: (kind: 'episode' | 'writing' | 'roleplay') => void }) {
  const { t } = useTranslation()
  const { course } = props
  return (
    <>
      {course.level && (
        <div className="min-w-0">
          {t('map.level')} <Badge className="h-auto max-w-full shrink rounded-sm bg-accent px-2 py-0.5 text-start text-base break-words whitespace-normal text-accent-foreground">{course.level}</Badge>
        </div>
      )}
      {course.strands && course.concepts.length > 0 && (
        <LevelPanel
          level={course.level}
          strands={course.strands}
          vocabulary={course.vocabulary}
          units={course.concepts}
          disabled={props.running}
          onStart={props.onStart}
          story={course.lang !== null}
        />
      )}
    </>
  )
}

/** A lesson's checks taken offline: how many are answered and sending them, or preparing them in the first place. */
function OfflineRow(props: {
  lesson: Lesson
  given: Record<number, Given>
  online: boolean
  sending: boolean
  onSend: (ready: Block[]) => void
  onPrepare: () => void
}) {
  const { t } = useTranslation()
  const { lesson, given } = props
  if (!lesson.batch) {
    return (
      <div className={cn(NEXT, 'items-center justify-between gap-x-4 gap-y-3')}>
        <span className={SMALL}>{t('offline.help')}</span>
        <Button variant="outline" disabled={!props.online} onClick={props.onPrepare}>
          {t('offline.prepare')}
        </Button>
      </div>
    )
  }
  const batchCards = lesson.blocks.filter((b) => b.kind === 'quiz' && (b.data as QuizData).answer === null)
  const ready = batchCards.filter((b) => given[b.id] && ((b.data as QuizData).kind !== 'open' || given[b.id].self_correct !== undefined))
  return (
    <div className={cn(NEXT, 'items-center justify-between gap-x-4 gap-y-3')}>
      <span className={SMALL}>{t('offline.answered', { n: ready.length, total: batchCards.length })}</span>
      {/* with nothing answered it leaves offline mode, the way out of a prepare that wrote no checks */}
      <Button variant={ready.length ? 'default' : 'outline'} disabled={!props.online || props.sending} onClick={() => props.onSend(ready)}>
        {ready.length ? t('offline.send') : t('offline.leave')}
      </Button>
    </div>
  )
}

function UpgradeCard(props: { upgrade: NonNullable<CourseDetail['upgrade']>; upgrading: boolean; onUpgrade: () => void; onStay: () => void }) {
  const { t } = useTranslation()
  const { upgrade } = props
  return (
    <section className={CARD}>
      <div className={cn(LABEL, 'mb-2')}>{t('replay.upgrade', { number: upgrade.number, date: day(upgrade.published.slice(0, 10)) })}</div>
      {upgrade.notes && (
        <div className={SMALL} dir="auto">
          {upgrade.notes}
        </div>
      )}
      {(['kept', 'restarted', 'added', 'removed'] as const).map(
        (part) =>
          upgrade[part].length > 0 && (
            <div key={part} className={SMALL} dir="auto">
              {t(`replay.${part}`, { count: upgrade[part].length, units: upgrade[part].join(', ') })}
            </div>
          ),
      )}
      <div className={ROW}>
        <Button type="button" disabled={props.upgrading} onClick={props.onUpgrade}>
          {props.upgrading ? t('replay.upgrading') : t('replay.upgradeNow')}
        </Button>
        <Button type="button" variant="outline" disabled={props.upgrading} onClick={props.onStay}>
          {t('replay.stay')}
        </Button>
      </div>
    </section>
  )
}

/** The commands a replayed course asks to run once, each allowed or refused by the learner. */
function SetupCard(props: { steps: SetupStep[]; onDecide: (index: number, allow: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <section className={`${CARD} flex flex-col gap-3`}>
      <div className={cn(LABEL, 'mb-2')}>{t('replay.setup')}</div>
      <div className={SMALL}>{t('replay.setupHelp')}</div>
      {props.steps.map((step, i) => (
        <div key={i} className="flex flex-col gap-2">
          <pre dir="ltr" className="m-0">{step.command}</pre>
          <div className={ROW}>
            {step.status === 'running' ? (
              <span className={SMALL}>{t('replay.running')}</span>
            ) : step.status === 'asked' || step.status === 'failed' ? (
              <>
                {step.status === 'failed' && <span className={SMALL}>{t('replay.failed', { code: step.exit_code ?? '–' })}</span>}
                <Button type="button" onClick={() => props.onDecide(i, true)}>
                  {t('network.allow')}
                </Button>
                <Button type="button" variant="outline" onClick={() => props.onDecide(i, false)}>
                  {t('network.refuse')}
                </Button>
              </>
            ) : (
              <span className={SMALL}>{t(`replay.${step.status}`)}</span>
            )}
          </div>
        </div>
      ))}
    </section>
  )
}

export function Workspace({ profile, courseId, speech, commands, sketched, concept, start, found }: { profile: number; courseId: number; speech: boolean; commands: boolean; sketched: boolean; concept: number | null; start: 'episode' | 'writing' | 'roleplay' | null; found: { lesson: number; at: string } | null }) {
  const { t } = useTranslation()
  const foundLesson = found?.lesson ?? null
  const [openModules, setOpenModules] = useState<Record<string, boolean>>({})
  const online = useOnline()
  const { course, setCourse, sources, setSources, lessonId, setLessonId, streaming, activity, writing, error, setError, patchLesson, addLesson } = useCourseStream({
    courseId,
    concept,
    start,
    foundLesson,
  })
  const lessonBox = useRef<HTMLElement>(null)

  const lesson = course?.lessons.find((l) => l.id === lessonId) ?? null
  const { held, pane, setPane, asking, setAsking, showLesson, unmetNeeds, openConcept, opened, openLesson } = useUnitNav(course, setLessonId, addLesson, setError)
  // a start link creates its lesson outside useUnitNav: it is shown like any lesson opened there
  useEffect(() => {
    setPane('lesson')
    setAsking(null)
  }, [start, setPane, setAsking])
  const { upgrading, upgrade } = useUpgrade(courseId, setCourse, setLessonId, setError)
  const { draft, setDraft, changing, setChanging, send, onKey } = useChatDraft(lesson, patchLesson, setError)
  const open = chatOpen(lesson, asking, found)
  const unread = useUnread(lessonId, lesson, open)
  const { given, give, sending, prepareOffline, sendBatch } = useOfflineAnswers(lessonId, patchLesson, setError)
  const { lessonBottom, messagesBox } = useFollow({ lesson, ranked: course?.ranking.length, writing, open, streaming, found })
  useArrivals(lessonBox, lesson?.id)
  useArrivals(messagesBox, lesson?.id)

  function closeChat() {
    setAsking(false)
    // the sidebar hides with the focus in it: hand it back to the button that opens it
    requestAnimationFrame(() => document.getElementById('ask')?.focus())
  }

  useLessonVisits(course, courseId, lessonId)

  function post(path: string, body: unknown): Promise<void> {
    return api<void>(path, body).catch((err: Error) => setError(err.message))
  }

  // "Stop for today" after a finished unit, only once this sitting has answers to sum up
  const lessonDone = lesson?.blocks.some((b) => b.kind === 'done') ?? false
  const answeredToday = useAnsweredToday(lessonDone, profile)

  if (!course || !lesson) return <main className="mx-auto flex w-full max-w-160 flex-col gap-10 px-6 pt-10 pb-16">{error && <div className={ERROR}>{error}</div>}</main>

  const { showPlan, finished, nextUnit, cardTotal, empty, canPrepare } = lessonView(course, lesson)
  const doing = activity ? lookup(`activity.${activity}`, t('activity.working')) : t('activity.working')

  return (
    <div className="relative flex min-h-0 grow max-md:flex-col" data-pane={pane}>
      <MapNav
        className={cn(PANE, pane !== 'map' && PANE_AWAY)}
        course={course}
        lesson={lesson}
        sources={sources}
        onSources={setSources}
        onError={setError}
        held={held}
        unmetNeeds={unmetNeeds}
        onOpenConcept={openConcept}
        openModules={openModules}
        onToggleModule={(module, now) => setOpenModules((m) => ({ ...m, [module]: now }))}
        onShow={showLesson}
        onCreate={openLesson}
        onLesson={opened}
        onChangeMap={() => {
          // The planning conversation lives in the interview lesson; the tutor revises the map from any lesson.
          showLesson(course.lessons.find((l) => l.phase === 'interview')?.id ?? lesson.id)
          setAsking(true)
          setChanging(true)
          // after the click's render, once the chat is open
          requestAnimationFrame(() => document.getElementById('chat')?.focus())
        }}
        onPace={(pace) =>
          api(`/api/courses/${course.id}/pace`, { pace }).then(
            () => setCourse((c) => c && { ...c, pace }),
            (err: Error) => setError(err.message),
          )
        }
      />

      <main
        ref={lessonBox}
        className={cn(
          'flex min-w-0 grow flex-col gap-6 overflow-x-hidden overflow-y-auto px-6 pt-10 pb-16 max-md:p-4 min-[1101px]:pe-23',
          '[&_li]:max-w-[75ch] [&_p:not([class])]:max-w-[75ch] [&>.block:first-child]:border-t-0 [&>.block:first-child]:pt-0',
          PANE,
          pane !== 'lesson' && PANE_AWAY,
        )}
      >
        <CourseNotices
          course={course}
          upgrading={upgrading}
          onUpgrade={upgrade}
          onStay={(hash) => api<CourseDetail>(`/api/courses/${course.id}/upgrade/skip`, { hash }).then(setCourse, (e: Error) => setError(e.message))}
          onDecide={(i, allow) => api(`/api/courses/${course.id}/setup/${i}`, { allow }).catch((e: Error) => setError(e.message))}
          onDecideResource={(kind, allow) =>
            api<{ resources: Resource[] }>(`/api/courses/${course.id}/resources/${kind}`, { allow }).then(
              ({ resources }) => setCourse((c) => c && { ...c, resources }),
              (e: Error) => setError(e.message),
            )
          }
        />
        <h1 dir="auto" className="m-0 max-w-none">
          {lessonTitle(lesson, t)}
        </h1>
        <LessonIntro course={course} lesson={lesson} finished={finished} setCourse={setCourse} post={post} onError={setError} />
        <LessonCards
          course={course}
          lesson={lesson}
          total={cardTotal}
          given={given}
          onGive={give}
          features={{ speech, commands, sketched }}
          post={post}
          onError={setError}
        />
        {showPlan && <CoursePlan course={course} lesson={lesson} post={post} onPlacement={() => openLesson(`/api/courses/${course.id}/placement`)} />}
        <PlacementNote course={course} lesson={lesson} />
        <LessonFoot
          lesson={lesson}
          working={empty || writing}
          offline={canPrepare}
          nextUnit={nextUnit}
          stop={answeredToday}
          onOpenUnit={openConcept}
          row={<OfflineRow lesson={lesson} given={given} online={online} sending={sending} onSend={sendBatch} onPrepare={prepareOffline} />}
        />
        {error && <div className={ERROR}>{error}</div>}
        <div ref={lessonBottom} />
        {!open && (
          <AskButton
            unread={unread}
            working={lesson.running ? doing : null}
            onAsk={() => {
              setAsking(true)
              requestAnimationFrame(() => document.getElementById('chat')?.focus())
            }}
          />
        )}
      </main>

      <ChatPanel
        className={cn(pane === 'map' && 'max-md:hidden')}
        open={open}
        running={lesson.running}
        doing={doing}
        messages={lesson.messages}
        streaming={streaming}
        draft={draft}
        onDraft={setDraft}
        placeholder={changing ? t('chat.changeHint') : undefined}
        onKey={onKey}
        speech={speech}
        voice={lesson.phase === 'roleplay' ? course.lang : null}
        lessonId={lesson.id}
        courseId={course.id}
        canSend={online && !lesson.running && Boolean(course.started) && Boolean(draft.trim())}
        onSend={send}
        onStop={() => post(`/api/lessons/${lesson.id}/stop`, {})}
        onClose={closeChat}
        onError={setError}
        messagesRef={messagesBox}
      />

      <PaneSwitcher
        pane={pane}
        open={open}
        unread={unread}
        working={lesson.running && !open ? doing : null}
        onPane={(p) => {
          setPane(p)
          setAsking(false)
        }}
        onChat={() => {
          setPane('lesson')
          setAsking(true)
          requestAnimationFrame(() => document.getElementById('chat')?.focus())
        }}
      />
    </div>
  )
}

/** The chat sidebar follows the lesson until the learner opens or closes it: open in the interview, in a guided
 * contribution and in a role-play, which are conversations, and for a search hit in the chat. */
function chatOpen(lesson: Lesson | null, asking: boolean | null, found: { lesson: number; at: string } | null): boolean {
  if (!lesson) return false
  return asking ?? (lesson.phase === 'interview' || lesson.phase === 'contribution' || lesson.phase === 'roleplay' || (lesson.id === found?.lesson && found.at.startsWith('msg-')))
}

/** Below the cards: the placeholder while the tutor writes, the offline row, and the way on to the next unit. */
function LessonFoot(props: {
  lesson: Lesson
  working: boolean
  offline: boolean
  nextUnit: Concept | undefined
  stop: boolean
  onOpenUnit: (unit: Concept) => void
  row: ReactNode
}) {
  const { lesson, nextUnit } = props
  return (
    <>
      {lesson.running && props.working && <Skeleton />}
      {!lesson.running && (lesson.batch || props.offline) && props.row}
      {nextUnit && !lesson.running && <NextUnit unit={nextUnit} stop={props.stop} onOpen={() => props.onOpenUnit(nextUnit)} />}
    </>
  )
}

/** Moving between units: opening one shows the lesson pane; a unit whose needs are still open waits on the map. */
function useUnitNav(course: CourseDetail | null, setLessonId: (id: number) => void, addLesson: (lesson: Lesson) => void, setError: (message: string) => void) {
  // the unit asked for while units it needs are still open: the map says so before it starts
  const [held, setHeld] = useState<number | null>(null)
  // which column a phone shows; wider screens show all three
  const [pane, setPane] = useState<'map' | 'lesson'>('lesson')
  // the chat sidebar; unset, it follows the lesson: open in one that is a conversation
  const [asking, setAsking] = useState<boolean | null>(null)

  function showLesson(id: number) {
    setLessonId(id)
    setPane('lesson')
    setAsking(null)
  }

  function unmetNeeds(concept: Concept): Concept[] {
    if (!course) return []
    return concept.needs
      .map((id) => course.concepts.find((c) => c.id === id))
      .filter((c): c is Concept => c !== undefined && !c.known && !unitDone(c, course.lessons.find((l) => l.concept_id === c.id)))
  }

  function openConcept(concept: Concept, anyway = false) {
    const existing = course?.lessons.find((l) => l.concept_id === concept.id)
    if (existing) return showLesson(existing.id)
    if (!anyway && concept.unwritten) return setHeld(concept.id)
    if (!anyway && course?.mode !== 'teacher' && unmetNeeds(concept).length > 0) return setHeld(concept.id)
    setHeld(null)
    openLesson(`/api/concepts/${concept.id}/lesson`)
  }

  function opened(created: Lesson) {
    addLesson(created)
    showLesson(created.id)
  }

  /** Create a lesson (a unit's, an episode, a placement) and show it. */
  function openLesson(path: string) {
    api<Lesson>(path, {}).then(opened, (err: Error) => setError(err.message))
  }

  return { held, pane, setPane, asking, setAsking, showLesson, unmetNeeds, openConcept, opened, openLesson }
}

/** Under the title: the unit's outline, a prepared course's handouts, and the interview's scope. */
function LessonIntro(props: {
  course: CourseDetail
  lesson: Lesson
  finished: boolean
  setCourse: Dispatch<SetStateAction<CourseDetail | null>>
  post: (path: string, body: unknown) => void
  onError: (message: string) => void
}) {
  const { t } = useTranslation()
  const { course, lesson } = props
  const outline = outlineOf(lesson)
  return (
    <>
      {/* first, wherever the tutor posted it: the plan and the counter belong under the title */}
      {outline && (
        <OutlineCard
          key={lesson.id}
          data={outline}
          onTestOut={course.pace === 'speed' && lesson.phase === 'lesson' && !props.finished && !lesson.running ? (scope) => props.post(`/api/lessons/${lesson.id}/testout`, { scope }) : undefined}
        />
      )}
      {course.mode === 'teacher' && lesson.concept_id !== null && (
        <div className={cn(SMALL, '-mt-2')}>
          {t('handout.label')}{' '}
          <a className={LINK} href={`#/lesson/${lesson.id}/handout/teacher`}>{t('handout.teacher')}</a>,{' '}
          <a className={LINK} href={`#/lesson/${lesson.id}/handout/student`}>{t('handout.student')}</a>
        </div>
      )}
      {lesson.phase === 'interview' &&
        (course.started ? (
          <ScopeCard course={course} />
        ) : (
          <ScopeForm
            disabled={lesson.running}
            onStart={(scope) =>
              api<CourseDetail>(`/api/courses/${course.id}/start`, scope).then(
                ({ details, hours, started }) => {
                  props.setCourse((c) => c && { ...c, details, hours, started })
                },
                (err: Error) => props.onError(err.message),
              )
            }
          />
        ))}
    </>
  )
}

function CoursePlan(props: { course: CourseDetail; lesson: Lesson; post: (path: string, body: unknown) => void; onPlacement: () => void }) {
  const { course } = props
  return (
    <Plan
      ranking={course.ranking}
      mechanism={course.mechanism}
      accepted={course.concepts.length > 0 || course.lessons.some((l) => l.phase === 'placement')}
      prepared={course.mode === 'teacher'}
      disabled={props.lesson.running}
      onChoose={(mechanism) => props.post(`/api/courses/${course.id}/mechanism`, { mechanism })}
      onAccept={() => props.post(`/api/courses/${course.id}/plan/accept`, {})}
      onPlacement={props.onPlacement}
    />
  )
}

/** The placement's result, in the course's placement lesson until the tutor posts it as a card. */
function PlacementNote({ course, lesson }: { course: CourseDetail; lesson: Lesson }) {
  const shown = lesson.phase === 'placement' && course.placement && course.lessons.find((l) => l.phase === 'placement')?.id === lesson.id && !lesson.blocks.some((b) => b.kind === 'placement')
  return shown ? <PlacementResult level={course.level} text={course.placement!} areas={course.areas} /> : null
}

function MapNav(props: {
  className: string
  course: CourseDetail
  lesson: Lesson
  sources: Source[]
  onSources: (sources: Source[]) => void
  onError: (message: string) => void
  held: number | null
  unmetNeeds: (concept: Concept) => Concept[]
  onOpenConcept: (concept: Concept, anyway?: boolean) => void
  openModules: Record<string, boolean>
  onToggleModule: (module: string, now: boolean) => void
  onShow: (lessonId: number) => void
  onCreate: (path: string) => void
  onLesson: (created: Lesson) => void
  onChangeMap: () => void
  onPace: (pace: CourseDetail['pace']) => void
}) {
  const { t } = useTranslation()
  const { course, lesson } = props
  return (
    <nav className={cn('flex w-72 shrink-0 flex-col gap-2 overflow-y-auto bg-muted px-3 py-6', props.className)} aria-label={t('map.label')}>
      <MapHead course={course} running={lesson.running} onStart={(kind) => props.onCreate(`/api/courses/${course.id}/${kind}`)} />
      <SideMenu
        course={course}
        running={lesson.running}
        sources={props.sources}
        onSources={props.onSources}
        onError={props.onError}
        onLesson={props.onLesson}
        onChangeMap={props.onChangeMap}
        onPace={props.onPace}
      />
      {course.lessons
        .filter((l) => l.concept_id === null)
        .map((l) => (
          <button key={l.id} className={MAP_ROW} aria-current={l.id === lesson.id} onClick={() => props.onShow(l.id)}>
            {lessonTitle(l, t)}
          </button>
        ))}
      {moduleRuns(course.concepts).map((units) => (
        <ModuleGroup
          key={units[0].id}
          units={units}
          course={course}
          current={lesson.id}
          held={props.held}
          unmetNeeds={props.unmetNeeds}
          onOpen={props.onOpenConcept}
          toggled={props.openModules[units[0].module]}
          onToggle={(now) => props.onToggleModule(units[0].module, now)}
        />
      ))}
      {course.recap?.finished && (
        <a
          className="mt-2 flex min-h-11 items-center justify-between gap-3 border-t px-3 py-2 font-semibold text-accent-foreground no-underline hover:rounded-md hover:bg-paper-3"
          href={`#/course/${course.id}/recap`}
        >
          <span className="min-w-0 wrap-anywhere">{t('recap.mapEntry')}</span>
          <span className="inline-flex size-4.5 items-center justify-center rounded-full bg-primary text-xs leading-none font-semibold text-primary-foreground" role="img" aria-label={t('common.done')}>
            ✓
          </span>
        </a>
      )}
    </nav>
  )
}

function megabytes(bytes: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: 'unit', unit: 'megabyte', maximumFractionDigits: 0 }).format(Math.max(1, bytes / 1e6))
}

/** Open data for the course's language that the tutor offered, each allowed or refused by the learner. */
function ResourcesCard(props: { resources: Resource[]; onDecide: (kind: Resource['kind'], allow: boolean) => Promise<unknown> }) {
  const { t, i18n } = useTranslation()
  const [busy, setBusy] = useState<Resource['kind'] | null>(null)

  function decide(kind: Resource['kind'], allow: boolean) {
    setBusy(kind)
    props.onDecide(kind, allow).finally(() => setBusy(null))
  }

  return (
    <section className={`${CARD} flex flex-col gap-3`}>
      <div className={cn(LABEL, 'mb-2')}>{t('resources.heading')}</div>
      <div className={SMALL}>{t('resources.help')}</div>
      {props.resources.map((r) => (
        <div key={r.kind} className="flex flex-col gap-2">
          <div>
            <strong>{t(`resources.${r.kind}`)}</strong>
            {r.size !== null && <span className={SMALL}> ({t('resources.size', { size: megabytes(r.size, i18n.language) })})</span>}
          </div>
          <div className={SMALL}>{t(`resources.${r.kind}Help`)}</div>
          <div className={ROW}>
            {r.status === 'downloading' ? (
              <span className={SMALL}>{!r.size ? t('replay.running') : r.prepares && r.done >= r.size ? t('resources.preparing') : t('resources.progress', { percent: Math.min(100, Math.floor((100 * r.done) / r.size)) })}</span>
            ) : r.status === 'asked' || r.status === 'failed' ? (
              <>
                {r.status === 'failed' && <span className={SMALL}>{t('resources.failed', { error: r.error ?? '' })}</span>}
                <Button type="button" disabled={busy === r.kind} onClick={() => decide(r.kind, true)}>
                  {t('resources.download')}
                </Button>
                <Button type="button" variant="outline" disabled={busy === r.kind} onClick={() => decide(r.kind, false)}>
                  {t('network.refuse')}
                </Button>
              </>
            ) : (
              <span className={SMALL}>{t(`replay.${r.status === 'ready' ? 'done' : 'refused'}`)}</span>
            )}
          </div>
        </div>
      ))}
    </section>
  )
}

/** A newer version to move to, and setup steps still to decide, above the lesson. */
function CourseNotices(props: {
  course: CourseDetail
  upgrading: boolean
  onUpgrade: (hash: string) => void
  onStay: (hash: string) => void
  onDecide: (index: number, allow: boolean) => void
  onDecideResource: (kind: Resource['kind'], allow: boolean) => Promise<unknown>
}) {
  const { course } = props
  const upgrade = course.upgrade
  return (
    <>
      {upgrade && <UpgradeCard upgrade={upgrade} upgrading={props.upgrading} onUpgrade={() => props.onUpgrade(upgrade.hash)} onStay={() => props.onStay(upgrade.hash)} />}
      {course.setup.some((step) => step.status !== 'done' && step.status !== 'refused') && <SetupCard steps={course.setup} onDecide={props.onDecide} />}
      {course.resources.some((r) => r.status !== 'ready' && r.status !== 'refused') && <ResourcesCard resources={course.resources} onDecide={props.onDecideResource} />}
    </>
  )
}

/** The lesson's cards in order, numbered when the lesson has a card count, each with its edit bar in a teacher's course. */
function LessonCards(props: {
  course: CourseDetail
  lesson: Lesson
  total: number | null | undefined
  given: Record<number, Given>
  onGive: (blockId: number, answer: Given) => void
  features: { speech: boolean; commands: boolean; sketched: boolean }
  post: (path: string, body: unknown) => Promise<void>
  onError: (message: string) => void
}) {
  const { t } = useTranslation()
  const { course, lesson, total } = props
  const cardNumber = (i: number) => (total ? { n: lesson.blocks.slice(0, i + 1).filter((b) => b.kind !== 'outline').length, total } : null)
  return lesson.blocks.map((b, i) => {
    if (b.kind === 'outline' || (lesson.replay && i >= replayShown(lesson.blocks))) return null
    const n = cardNumber(i)
    const card = (
      <LessonCard
        key={b.id}
        block={b}
        lesson={lesson}
        course={course}
        authored={course.mode === 'teacher'}
        given={props.given[b.id]}
        onGive={(answer) => props.onGive(b.id, answer)}
        features={props.features}
        post={props.post}
        onError={props.onError}
      />
    )
    const shown = n ? (
      <div key={b.id} className="relative [&>.block>.label]:pe-[4.5em]">
        <span className="absolute end-0 top-6 text-sm leading-snug text-muted-foreground tabular-nums" aria-label={t('outline.card', n)}>
          <bdi dir="ltr">{n.n} / {n.total}</bdi>
        </span>
        {card}
      </div>
    ) : (
      card
    )
    if (course.mode !== 'teacher' || b.kind === 'question') return shown
    return (
      <Fragment key={b.id}>
        {shown}
        <EditBar block={b} first={i === 0} last={i === lesson.blocks.length - 1} disabled={lesson.running} onError={props.onError} />
      </Fragment>
    )
  })
}

function NextUnit(props: { unit: Concept; stop: boolean; onOpen: () => void }) {
  const { t } = useTranslation()
  return (
    <div className={NEXT}>
      <Button onClick={props.onOpen}>
        {t('lesson.nextUnit', { title: props.unit.title })}
      </Button>
      {props.stop && (
        <a className={buttonVariants({ variant: 'outline' })} href="#/sitting">
          {t('sitting.stop')}
        </a>
      )}
    </div>
  )
}
