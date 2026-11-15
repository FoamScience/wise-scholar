import type { Area, Block, Capstone, Concept, CourseDetail, Lesson, Message, Ranked, SetupStep } from './course'
import type { Source } from './Sources'

export type TutorEvent =
  | { type: 'turn.started'; lesson_id: number }
  | { type: 'chat.delta'; lesson_id: number; text: string }
  | { type: 'activity'; lesson_id: number; tool: string }
  | { type: 'block.added' | 'block.updated'; lesson_id: number; block: Block }
  | { type: 'block.removed'; lesson_id: number; id: number }
  | { type: 'lesson.ordered'; lesson_id: number; blocks: Block[] }
  | { type: 'plan.ranked'; ranking: Ranked[]; mechanism: string }
  | { type: 'plan.chosen'; mechanism: string }
  | { type: 'course.pace'; pace: 'momentum' | 'speed' }
  | { type: 'placement.set'; level: string; placement: string; areas: Area[] }
  | { type: 'map.set'; concepts: Concept[]; capstones?: Capstone[] }
  | { type: 'capstone.set'; capstone: Capstone }
  | { type: 'source.updated'; source: Source }
  | { type: 'source.removed'; id: number }
  | { type: 'lesson.created'; lesson: Lesson }
  | { type: 'setup.updated'; setup: SetupStep[] }
  | { type: 'turn.done'; lesson_id: number; ok: boolean; error: string | null; message: Message | null }

/** The lesson an event changes the cards of, and how; null when it changes none. */
export function lessonChange(ev: TutorEvent): [number, (l: Lesson) => Lesson] | null {
  switch (ev.type) {
    case 'block.added':
      return [ev.lesson_id, (l) => ({ ...l, blocks: [...l.blocks, ev.block] })]
    case 'block.updated':
      return [ev.lesson_id, (l) => ({ ...l, blocks: l.blocks.map((b) => (b.id === ev.block.id ? ev.block : b)) })]
    case 'block.removed':
      return [ev.lesson_id, (l) => ({ ...l, blocks: l.blocks.filter((b) => b.id !== ev.id) })]
    case 'lesson.ordered':
      return [ev.lesson_id, (l) => ({ ...l, blocks: ev.blocks })]
    default:
      return null
  }
}

/** What an event changes in the course's plan, map, pace or setup, or null when it changes none of them. */
export function courseChange(ev: TutorEvent): ((c: CourseDetail) => CourseDetail) | null {
  switch (ev.type) {
    case 'plan.ranked':
      return (c) => ({ ...c, ranking: ev.ranking, mechanism: ev.mechanism })
    case 'plan.chosen':
      return (c) => ({ ...c, mechanism: ev.mechanism })
    case 'course.pace':
      return (c) => ({ ...c, pace: ev.pace })
    case 'placement.set':
      return (c) => ({ ...c, level: ev.level, placement: ev.placement, areas: ev.areas })
    case 'capstone.set':
      return (c) => ({
        ...c,
        capstones: c.capstones.some((k) => k.id === ev.capstone.id)
          ? c.capstones.map((k) => (k.id === ev.capstone.id ? ev.capstone : k))
          : [...c.capstones, ev.capstone],
      })
    case 'map.set':
      return (c) => ({ ...c, concepts: ev.concepts, capstones: ev.capstones ?? c.capstones })
    case 'setup.updated':
      return (c) => ({ ...c, setup: ev.setup })
    default:
      return null
  }
}

/** What an event changes in the course's materials, or null when it changes none. */
export function sourcesChange(ev: TutorEvent): ((all: Source[]) => Source[]) | null {
  switch (ev.type) {
    case 'source.updated':
      return (all) => (all.some((s) => s.id === ev.source.id) ? all.map((s) => (s.id === ev.source.id ? ev.source : s)) : [...all, ev.source])
    case 'source.removed':
      return (all) => all.filter((s) => s.id !== ev.id)
    default:
      return null
  }
}
