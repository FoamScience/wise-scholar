import type { TFunction } from 'i18next'

export type Course = {
  id: number
  topic: string
  slug: string
  mechanism: string | null
  level: string | null
  archived: number
  mode: 'learner' | 'teacher' | 'replay'
  cover: number
  cover_alt: string | null
  finished?: string | null
}
export type Message = { id: number; lesson_id: number; role: 'learner' | 'tutor'; text: string; created: string }
export type QuestionData = { options: string[]; answer: string | null; multiple?: boolean; non_goals?: string[] }
export type ChallengeData = {
  attempts: string[]
  hints: string[]
  gave_up: boolean
  solved: boolean
  solution: string | null
  reveal_after: number
  max_hints: number
  writing?: boolean
  fluency?: boolean
  marks?: string[]
  spoken?: boolean
  teachback?: boolean
  pretest?: boolean
  milestone?: boolean
  transfer?: boolean
  comparison?: { left: string; right: string; question: string }
  helper?: string
  lang?: string
  words?: [number, number] | null
  structure?: string
  photos?: Photo[]
  transcripts?: Record<string, { text: string; by: 'tutor' | 'learner' }>
}
export type Photo = { name: string; attempt: number | null }

/** What the learner answered in an attempt: what they typed, and how the photos of their paper work were read. */
export function saidIn(data: ChallengeData, attempt: number): string {
  return [data.attempts[attempt], data.transcripts?.[attempt]?.text].filter(Boolean).join('\n\n')
}

export function pendingPhotos(data: ChallengeData): Photo[] {
  return (data.photos ?? []).filter((p) => p.attempt === null)
}
export type Scored = { word: string; score: number }
export type SpeakingData = ChallengeData & { speaking: 'read' | 'shadow'; lang: string; scores: { words: Scored[]; heard: string | null; score: number }[] }
/** The locale key under `block` that heads a block's card; a role-play's last card is no covered unit. */
export function blockKey(block: Block): string {
  return block.kind === 'done' && 'mistakes' in ((block.data ?? {}) as object) ? 'roleplayDone' : block.kind
}

export type Block = { id: number; lesson_id: number; kind: string; markdown: string; data: unknown; created: string; position: number }
export type Area = { title: string; holds: string; lacks: string }
export type Concept = { id: number; module: string; title: string; known: number; mastery: number | null; kind: 'concept' | 'practice'; due: number; needs: number[]; unwritten?: number }
export type Lesson = {
  id: number
  title: string
  phase: string
  concept_id: number | null
  messages: Message[]
  blocks: Block[]
  running: boolean
  batch?: number
  replay?: boolean
  cards?: number | null
}
export type Ranked = {
  mechanism: string
  rationale: string
  title: string
  summary: string
  evidence: { source: string; finding: string; url: string }[]
}
export type Capstone = {
  id: number
  module: string
  title: string
  brief: string
  folder: string
  done: number
  milestones: { id: number; concept_id: number; concept: string; deliverable: string; done: number }[]
}
export type CourseDetail = Course & {
  mode: 'learner' | 'teacher' | 'replay'
  pace: 'momentum' | 'speed'
  cleaned: string | null
  details: string
  hours: number | null
  started: number
  placement: string | null
  areas: Area[]
  prerequisites: number
  lang: string | null
  capstones: Capstone[]
  ranking: Ranked[]
  concepts: Concept[]
  lessons: Lesson[]
  strands: { input: number; output: number; language: number; fluency: number } | null
  vocabulary: { total: number; due: number; tier?: number; tier_size?: number; tier_known?: number; tier_words?: number }
  setup: SetupStep[]
  resources: Resource[]
  upgrade: UpgradeOffer | null
  recap: { finished: string | null; seen: boolean } | null
}
export type UpgradeOffer = { hash: string; number: number; notes: string; published: string; kept: string[]; restarted: string[]; added: string[]; removed: string[] }
export type Resource = {
  kind: 'lexicon' | 'sentences' | 'morphology'
  lang: string
  size: number | null
  status: 'asked' | 'refused' | 'downloading' | 'ready' | 'failed'
  done: number
  error: string | null
  prepares: boolean
}
export type SetupStep = { command: string; status: 'asked' | 'running' | 'done' | 'failed' | 'refused'; exit_code?: number | null }

/** The server names its own lessons in English; a concept's lesson carries the tutor's title. */
export type TodayPlan = {
  due: number
  warmup: number
  review_minutes: number
  units: { course_id: number; topic: string; concept_id: number | null; title: string; started?: boolean }[]
  cast: { id: number; lesson_id: number; title: string; course_id: number } | null
  errors: number
  extras: { course_id: number; topic: string; kind: 'episode' | 'writing' }[]
}

export function unitTitle(u: TodayPlan['units'][number], t: TFunction): string {
  if (u.concept_id !== null) return u.title
  return u.started ? t('today.finishInterview') : t('scope.start')
}

export function practiceTitle(title: string, t: TFunction): string {
  return t('lesson.practice', { n: title.match(/\d+$/)?.[0] })
}

export function lessonTitle(lesson: Lesson, t: TFunction): string {
  const n = lesson.title.match(/\d+$/)?.[0]
  if (lesson.phase === 'practice') return practiceTitle(lesson.title, t)
  if (lesson.concept_id !== null) return lesson.title
  if (lesson.phase === 'interview') return t('lesson.interview')
  if (lesson.phase === 'placement') return n ? t('lesson.placementRetake', { n }) : t('lesson.placement')
  if (lesson.phase === 'story') return t('lesson.episode', { n })
  if (lesson.phase === 'writing') return t('lesson.writingSession', { n })
  if (lesson.phase === 'roleplay') return t('lesson.roleplay', { n })
  if (lesson.phase === 'revisit') return t('lesson.revisit', { n })
  return lesson.title
}

export function challengeLabel(d: ChallengeData, speech: boolean, t: TFunction): string {
  if (d.comparison) return t('challenge.compare')
  if (d.transfer) return t('challenge.transfer')
  if (d.milestone) return t('challenge.milestone')
  if (d.pretest) return t('challenge.pretest')
  if (d.teachback) return speech ? t('challenge.teachbackAloud') : t('challenge.teachback')
  if (d.spoken) return t('challenge.spoken')
  if (d.writing) return d.fluency ? t('challenge.writeFast') : t('challenge.write')
  return t('challenge.workItOut')
}

export type Completion = { label: string; signature: string; doc: string }
export type ExerciseData = ChallengeData & {
  files: string[]
  run: string
  last_run: { exit_code: number | null; output: string } | null
  completions?: Completion[]
}
export type ExerciseFile = { path: string; location: string; content: string | null; kept: boolean; editable: boolean; online: boolean }

export type SortItem = { text: string; category?: string }

export type OutlineData = { steps: string[]; at: number; added: { step: string; reason: string } | null; cards?: number }

export function outlineOf(lesson: Lesson): OutlineData | null {
  return (lesson.blocks.find((b) => b.kind === 'outline')?.data as OutlineData | undefined) ?? null
}

export function sortItems(options: string[] | SortItem[]): SortItem[] {
  return options.filter((o): o is SortItem => typeof o !== 'string')
}

export const SEARCH_KINDS = ['source', 'card', 'chat', 'code'] as const
export type SearchKind = (typeof SEARCH_KINDS)[number]

export function searchHref(courseId: number, query: string, kind: SearchKind | '' = '') {
  const params = new URLSearchParams({ q: query })
  if (kind) params.set('kind', kind)
  return `#/course/${courseId}/search?${params}`
}

const CHECKS = ['challenge', 'exercise', 'speaking']

/** How many blocks of a replayed unit are shown: everything up to and including the first check not yet behind the
 * learner. A try-first task is behind them once tried, any other task once solved, and either once given up or its
 * solution shown; a quiz once graded. */
export function replayShown(blocks: Block[]): number {
  const open = blocks.findIndex((b) => {
    const d = (b.data ?? {}) as { correct?: boolean | null; attempts?: string[]; pretest?: boolean; solved?: boolean; gave_up?: boolean; solution?: string | null }
    if (b.kind === 'quiz') return d.correct === undefined || d.correct === null
    if (CHECKS.includes(b.kind)) return !(d.gave_up || typeof d.solution === 'string' || (d.pretest ? d.attempts?.length : d.solved))
    return false
  })
  return open === -1 ? blocks.length : open + 1
}

export function moduleRuns(concepts: Concept[]): Concept[][] {
  const runs: Concept[][] = []
  for (const c of concepts) {
    if (runs.at(-1)?.[0].module === c.module) runs.at(-1)!.push(c)
    else runs.push([c])
  }
  return runs
}

/** A unit is done once its lesson is finished, or placed out with no lesson begun. */
export function unitDone(concept: Concept, lesson: Lesson | undefined): boolean {
  return lesson ? lesson.blocks.some((b) => b.kind === 'done') : Boolean(concept.known)
}

/** What the lesson pane shows around the cards: the plan in an interview, the card count, the next unit once this
 * one is finished, the working placeholder for an empty lesson, and whether it can be taken offline. */
export function lessonView(course: Pick<CourseDetail, 'ranking' | 'concepts' | 'mode'>, lesson: Lesson) {
  const done = lesson.blocks.some((b) => b.kind === 'done')
  const showPlan = lesson.phase === 'interview' && course.ranking.length > 0
  const finished = lesson.concept_id !== null && done
  const nextUnit = finished
    ? course.concepts.slice(course.concepts.findIndex((c) => c.id === lesson.concept_id) + 1).find((c) => !c.known && (c.mastery ?? 0) < 2 / 3)
    : undefined
  const cards = lesson.blocks.filter((b) => b.kind !== 'outline').length
  // the summary card still to come keeps the total above the cards already shown
  const estimate = outlineOf(lesson)?.cards ?? lesson.cards
  const cardTotal = estimate && (done ? cards : Math.max(estimate, cards + 1))
  const empty = lesson.blocks.length === 0 && !showPlan
  const canPrepare = lesson.phase === 'lesson' && lesson.concept_id !== null && course.mode !== 'teacher' && !lesson.batch && !lesson.replay && !finished
  return { showPlan, finished, nextUnit, cardTotal, empty, canPrepare }
}
