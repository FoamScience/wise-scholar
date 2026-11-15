import { Fragment, useRef, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { useArrivals } from './arrive'
import { day, lookup } from './i18n'
import { useOnline } from './offline'
import type { Given } from './offline'
import type { QuizData } from './Quiz'
import { LevelPanel } from './Language'
import { lessonTitle, lessonView, moduleRuns, outlineOf, replayShown, unitDone, searchHref } from './course'
import { OutlineCard } from './Outline'
import type { Block, Concept, CourseDetail, Lesson, Ranked, Resource, SetupStep } from './course'
import { ScopeCard, ScopeForm } from './Scope'
import type { Source } from './Sources'
import { ModuleGroup, SideMenu } from './CourseMap'
import { AskButton, ChatPanel, PaneSwitcher } from './Chat'
import { EditBar } from './EditBar'
import { LessonCard, PlacementResult } from './LessonCard'
import { useAnsweredToday, useChatDraft, useCourseStream, useFollow, useLessonVisits, useOfflineAnswers, useUnread, useUpgrade } from './workspaceState'

function Skeleton() {
  const { t } = useTranslation()
  return (
    <section className="block skeleton" role="status" aria-label={t('block.tutorWorking')}>
      <span style={{ width: '22%' }} />
      <span style={{ width: '92%' }} />
      <span style={{ width: '78%' }} />
      <span style={{ width: '54%' }} />
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
    <section className="plan">
      <div className="label">{t('plan.heading')}</div>
      {props.ranking.map((r, i) => (
        <label key={r.mechanism} className={r.mechanism === props.mechanism ? 'plan-card chosen' : 'plan-card'}>
          <input
            type="radio"
            name="mechanism"
            checked={r.mechanism === props.mechanism}
            disabled={props.accepted}
            onChange={() => props.onChoose(r.mechanism)}
          />
          <span>
            <strong>
              {i + 1}. {lookup(`playbooks.${r.mechanism}.title`, r.title)}
            </strong>
            <span dir="auto">{r.rationale}</span>
            <span className="muted">{lookup(`playbooks.${r.mechanism}.summary`, r.summary)}</span>
            <span className="evidence">
              {t('plan.evidence')}{' '}
              {r.evidence.map((e, n) => (
                <span key={e.url}>
                  {n > 0 && '; '}
                  <a href={e.url} target="_blank" rel="noreferrer" title={e.finding}>
                    {e.source}
                  </a>
                </span>
              ))}
            </span>
          </span>
        </label>
      ))}
      <div className="muted">{t('plan.always')}</div>
      {!props.accepted && (
        <div className="block next-step">
          <div className="label">{props.prepared ? t('plan.nextPrepared') : t('plan.next')}</div>
          <div>{props.prepared ? t('plan.preparedInfo') : t('plan.placementInfo')}</div>
          <div className="row">
            {!props.prepared && (
              <button className="btn primary" disabled={props.disabled} onClick={props.onPlacement}>
                {t('plan.startPlacement')}
              </button>
            )}
            <button className={props.prepared ? 'btn primary' : 'btn'} disabled={props.disabled} onClick={props.onAccept}>
              {props.prepared ? t('plan.accept') : t('plan.skip')}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

/** The map's head: progress, level, the language panel and the search. */
function MapHead(props: { course: CourseDetail; running: boolean; onStart: (kind: 'episode' | 'writing') => void }) {
  const { t } = useTranslation()
  const { course } = props
  const units = course.concepts.filter((c) => c.kind === 'concept')
  const unitsDone = units.filter((c) => unitDone(c, course.lessons.find((l) => l.concept_id === c.id))).length
  const reviewDue = units.filter((c) => c.due).length
  return (
    <>
      <div className="label">{t('map.label')}</div>
      {course.mode !== 'teacher' && units.length > 0 && (
        <div className="small">
          {reviewDue ? t('map.summary', { done: unitsDone, total: units.length, count: reviewDue }) : t('map.summaryDone', { done: unitsDone, total: units.length })}
        </div>
      )}
      {course.level && (
        <div className="level-row">
          <span>
            {t('map.level')} <span className="chip">{course.level}</span>
          </span>
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
      <form
        className="map-search"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          const query = String(new FormData(e.currentTarget).get('q') ?? '')
          if (query.trim()) location.hash = searchHref(course.id, query)
        }}
      >
        <input type="search" name="q" className="field" dir="auto" aria-label={t('search.label')} placeholder={t('search.placeholder')} />
      </form>
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
      <div className="lesson-next batch">
        <span className="small">{t('offline.help')}</span>
        <button className="btn" disabled={!props.online} onClick={props.onPrepare}>
          {t('offline.prepare')}
        </button>
      </div>
    )
  }
  const batchCards = lesson.blocks.filter((b) => b.kind === 'quiz' && (b.data as QuizData).answer === null)
  const ready = batchCards.filter((b) => given[b.id] && ((b.data as QuizData).kind !== 'open' || given[b.id].self_correct !== undefined))
  return (
    <div className="lesson-next batch">
      <span className="small">{t('offline.answered', { n: ready.length, total: batchCards.length })}</span>
      {/* with nothing answered it leaves offline mode, the way out of a prepare that wrote no checks */}
      <button className={ready.length ? 'btn primary' : 'btn'} disabled={!props.online || props.sending} onClick={() => props.onSend(ready)}>
        {ready.length ? t('offline.send') : t('offline.leave')}
      </button>
    </div>
  )
}

function UpgradeCard(props: { upgrade: NonNullable<CourseDetail['upgrade']>; upgrading: boolean; onUpgrade: () => void; onStay: () => void }) {
  const { t } = useTranslation()
  const { upgrade } = props
  return (
    <section className="block upgrade">
      <div className="label">{t('replay.upgrade', { number: upgrade.number, date: day(upgrade.published.slice(0, 10)) })}</div>
      {upgrade.notes && (
        <div className="small" dir="auto">
          {upgrade.notes}
        </div>
      )}
      {(['kept', 'restarted', 'added', 'removed'] as const).map(
        (part) =>
          upgrade[part].length > 0 && (
            <div key={part} className="small" dir="auto">
              {t(`replay.${part}`, { count: upgrade[part].length, units: upgrade[part].join(', ') })}
            </div>
          ),
      )}
      <div className="row">
        <button type="button" className="btn primary" disabled={props.upgrading} onClick={props.onUpgrade}>
          {props.upgrading ? t('replay.upgrading') : t('replay.upgradeNow')}
        </button>
        <button type="button" className="btn" disabled={props.upgrading} onClick={props.onStay}>
          {t('replay.stay')}
        </button>
      </div>
    </section>
  )
}

/** The commands a replayed course asks to run once, each allowed or refused by the learner. */
function SetupCard(props: { steps: SetupStep[]; onDecide: (index: number, allow: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <section className="block setup">
      <div className="label">{t('replay.setup')}</div>
      <div className="small">{t('replay.setupHelp')}</div>
      {props.steps.map((step, i) => (
        <div key={i} className="setup-step">
          <pre dir="ltr">{step.command}</pre>
          <div className="row">
            {step.status === 'running' ? (
              <span className="small">{t('replay.running')}</span>
            ) : step.status === 'asked' || step.status === 'failed' ? (
              <>
                {step.status === 'failed' && <span className="small">{t('replay.failed', { code: step.exit_code ?? '–' })}</span>}
                <button type="button" className="btn primary" onClick={() => props.onDecide(i, true)}>
                  {t('network.allow')}
                </button>
                <button type="button" className="btn" onClick={() => props.onDecide(i, false)}>
                  {t('network.refuse')}
                </button>
              </>
            ) : (
              <span className="small">{t(`replay.${step.status}`)}</span>
            )}
          </div>
        </div>
      ))}
    </section>
  )
}

export function Workspace({ profile, courseId, speech, commands, crafted, sketched, concept, start, found }: { profile: number; courseId: number; speech: boolean; commands: boolean; crafted: boolean; sketched: boolean; concept: number | null; start: 'episode' | 'writing' | null; found: { lesson: number; at: string } | null }) {
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

  function post(path: string, body: unknown) {
    api(path, body).catch((err: Error) => setError(err.message))
  }

  // "Stop for today" after a finished unit, only once this sitting has answers to sum up
  const lessonDone = lesson?.blocks.some((b) => b.kind === 'done') ?? false
  const answeredToday = useAnsweredToday(lessonDone, profile)

  if (!course || !lesson) return <main className="home">{error && <div className="error">{error}</div>}</main>

  const { showPlan, finished, nextUnit, cardTotal, empty, canPrepare } = lessonView(course, lesson)
  const doing = activity ? lookup(`activity.${activity}`, t('activity.working')) : t('activity.working')

  return (
    <div className="workspace" data-pane={pane}>
      <MapNav
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

      <main ref={lessonBox} className="lesson">
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
        <h1 dir="auto">{lessonTitle(lesson, t)}</h1>
        <LessonIntro course={course} lesson={lesson} finished={finished} setCourse={setCourse} post={post} onError={setError} />
        <LessonCards
          course={course}
          lesson={lesson}
          total={cardTotal}
          given={given}
          onGive={give}
          features={{ speech, commands, crafted, sketched }}
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
        {error && <div className="error">{error}</div>}
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

/** The chat sidebar follows the lesson until the learner opens or closes it: open in the interview and in a guided
 * contribution, which are conversations, and for a search hit in the chat. */
function chatOpen(lesson: Lesson | null, asking: boolean | null, found: { lesson: number; at: string } | null): boolean {
  if (!lesson) return false
  return asking ?? (lesson.phase === 'interview' || lesson.phase === 'contribution' || (lesson.id === found?.lesson && found.at.startsWith('msg-')))
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
  // the chat sidebar; unset, it follows the lesson: open in the interview, which is a conversation
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
          onTestOut={course.pace === 'speed' && !props.finished && !lesson.running ? (scope) => props.post(`/api/lessons/${lesson.id}/testout`, { scope }) : undefined}
        />
      )}
      {course.mode === 'teacher' && lesson.concept_id !== null && (
        <div className="small handouts">
          {t('handout.label')}{' '}
          <a href={`#/lesson/${lesson.id}/handout/teacher`}>{t('handout.teacher')}</a>,{' '}
          <a href={`#/lesson/${lesson.id}/handout/student`}>{t('handout.student')}</a>
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
    <nav className="map" aria-label={t('map.label')}>
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
          <button key={l.id} aria-current={l.id === lesson.id} onClick={() => props.onShow(l.id)}>
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
        <a className="recap-entry" href={`#/course/${course.id}/recap`}>
          <span className="concept-name">{t('recap.mapEntry')}</span>
          <span className="done-mark" role="img" aria-label={t('common.done')}>
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
    <section className="block setup">
      <div className="label">{t('resources.heading')}</div>
      <div className="small">{t('resources.help')}</div>
      {props.resources.map((r) => (
        <div key={r.kind} className="setup-step">
          <div>
            <strong>{t(`resources.${r.kind}`)}</strong>
            {r.size !== null && <span className="small"> ({t('resources.size', { size: megabytes(r.size, i18n.language) })})</span>}
          </div>
          <div className="small">{t(`resources.${r.kind}Help`)}</div>
          <div className="row">
            {r.status === 'downloading' ? (
              <span className="small">{r.size ? t('resources.progress', { percent: Math.min(100, Math.floor((100 * r.done) / r.size)) }) : t('replay.running')}</span>
            ) : r.status === 'asked' || r.status === 'failed' ? (
              <>
                {r.status === 'failed' && <span className="small">{t('resources.failed', { error: r.error ?? '' })}</span>}
                <button type="button" className="btn primary" disabled={busy === r.kind} onClick={() => decide(r.kind, true)}>
                  {t('resources.download')}
                </button>
                <button type="button" className="btn" disabled={busy === r.kind} onClick={() => decide(r.kind, false)}>
                  {t('network.refuse')}
                </button>
              </>
            ) : (
              <span className="small">{t(`replay.${r.status === 'ready' ? 'done' : 'refused'}`)}</span>
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
  features: { speech: boolean; commands: boolean; crafted: boolean; sketched: boolean }
  post: (path: string, body: unknown) => void
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
        authored={course.mode === 'teacher'}
        given={props.given[b.id]}
        onGive={(answer) => props.onGive(b.id, answer)}
        features={props.features}
        post={props.post}
        onError={props.onError}
      />
    )
    const shown = n ? (
      <div key={b.id} className="numbered">
        <span className="card-n" aria-label={t('outline.card', n)}>
          {n.n} / {n.total}
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
    <div className="lesson-next">
      <button className="btn primary" onClick={props.onOpen}>
        {t('lesson.nextUnit', { title: props.unit.title })}
      </button>
      {props.stop && (
        <a className="btn as-link" href="#/sitting">
          {t('sitting.stop')}
        </a>
      )}
    </div>
  )
}
