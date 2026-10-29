import type { TFunction } from 'i18next'

export type Course = {
  id: number
  topic: string
  slug: string
  mechanism: string | null
  level: string | null
  archived: number
  mode: 'learner' | 'teacher'
  cover: number
  cover_alt: string | null
}
export type Message = { id: number; lesson_id: number; role: 'learner' | 'tutor'; text: string; created: string }
export type QuestionData = { options: string[]; answer: string | null; multiple?: boolean }
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
  lang?: string
  words?: [number, number] | null
  structure?: string
  photos?: Photo[]
}
export type Photo = { name: string; attempt: number | null }

export function pendingPhotos(data: ChallengeData): Photo[] {
  return (data.photos ?? []).filter((p) => p.attempt === null)
}
export type Scored = { word: string; score: number }
export type SpeakingData = ChallengeData & { speaking: 'read' | 'shadow'; lang: string; scores: { words: Scored[]; heard: string | null; score: number }[] }
export type Block = { id: number; lesson_id: number; kind: string; markdown: string; data: unknown; created: string; position: number }
export type Area = { title: string; holds: string; lacks: string }
export type Concept = { id: number; module: string; title: string; known: number; mastery: number | null; kind: 'concept' | 'practice'; due: number; needs: number[] }
export type Lesson = {
  id: number
  title: string
  phase: string
  concept_id: number | null
  messages: Message[]
  blocks: Block[]
  running: boolean
  batch?: number
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
  mode: 'learner' | 'teacher'
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
}

/** The server names its own lessons in English; a concept's lesson carries the tutor's title. */
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

export type ExerciseData = ChallengeData & {
  files: string[]
  run: string
  last_run: { exit_code: number | null; output: string } | null
}
export type ExerciseFile = { path: string; location: string; content: string | null; kept: boolean }

export type SortItem = { text: string; category?: string }

export type OutlineData = { steps: string[]; at: number; added: { step: string; reason: string } | null }

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
