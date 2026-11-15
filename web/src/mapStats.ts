import type { TFunction } from 'i18next'
import { type ChallengeData, type Concept, type Lesson, outlineOf, unitDone } from './course'

/** A unit's line on the map: where it stands, its challenges, and its reviews due. */
export function conceptStats(concept: Concept, lesson: Lesson | undefined, t: TFunction, prepared = false): string {
  if (prepared) return preparedStats(lesson, t)
  const due = concept.due ? t('map.reviewDue', { count: concept.due }) : ''
  if (!lesson) return [concept.known ? t('map.placedOut') : t('map.notStarted'), due].filter(Boolean).join(', ')
  if (concept.kind === 'practice') return lesson.blocks.some((b) => b.kind === 'done') ? t('common.done') : t('map.started')
  const where = unitWhere(concept, lesson, t)
  const cs = lesson.blocks
    .filter((b) => b.kind === 'challenge' || b.kind === 'exercise' || b.kind === 'speaking')
    .map((b) => b.data as ChallengeData)
  if (cs.length === 0) return [where || t('map.started'), due].filter(Boolean).join(', ')
  return [where, ...challengeStats(cs, t), due].filter(Boolean).join(', ')
}

function preparedStats(lesson: Lesson | undefined, t: TFunction): string {
  if (!lesson) return t('map.notPlanned')
  return lesson.blocks.some((b) => b.kind === 'done') ? t('map.planned') : t('map.drafting')
}

/** Done, or the outline step the unit is at. */
function unitWhere(concept: Concept, lesson: Lesson, t: TFunction): string {
  if (unitDone(concept, lesson)) return t('common.done')
  const outline = outlineOf(lesson)
  return outline && outline.at < outline.steps.length ? t('outline.step', { n: outline.at + 1, total: outline.steps.length }) : ''
}

function challengeStats(cs: ChallengeData[], t: TFunction): (string | false)[] {
  const hints = cs.reduce((n, c) => n + c.hints.length, 0)
  const gaveUp = cs.filter((c) => c.gave_up).length
  return [
    t('map.solved', { solved: cs.filter((c) => c.solved).length, total: cs.length }),
    hints > 0 && t('map.hints', { count: hints }),
    gaveUp > 0 && t('map.gaveUp', { n: gaveUp }),
  ]
}
