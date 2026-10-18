import { sortItems } from './course'
import type { Graded, QuizData } from './Quiz'

/** An answer given in a lesson prepared for offline, kept on the device until it is sent. */
export type Given = { answer: string; confidence: number; self_correct?: boolean }

// The server's review.CONFIDENT: a miss at or above it is a confident miss.
const CONFIDENT = 0.75

export function placements(answer: string): Record<string, string> {
  try {
    const placed: unknown = JSON.parse(answer)
    const ok = placed !== null && typeof placed === 'object' && !Array.isArray(placed) && Object.values(placed).every((v) => typeof v === 'string')
    return ok ? (placed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

/** The device's grade of an answer, from the key the prepared card carries; an open answer has none until the
 * learner grades it against the model answer. The server grades every answer again when it is sent. */
export function gradeOffline(d: QuizData, given: Given): Graded | null {
  let correct: boolean
  let misplaced: string[] | undefined
  if (d.kind === 'choice') correct = given.answer === d.answer_key
  else if (d.kind === 'sort') {
    const placed = placements(given.answer)
    misplaced = sortItems(d.options).filter((i) => placed[i.text] !== i.category).map((i) => i.text)
    correct = misplaced.length === 0
  } else if (given.self_correct === undefined) return null
  else correct = given.self_correct
  return { correct, confident_miss: !correct && given.confidence >= CONFIDENT, answer_key: d.answer_key ?? '', explanation: d.explanation ?? '', misplaced }
}

const key = (lesson: number) => `batch-${lesson}`

// shortcut: localStorage, so answers survive a reload but not cleared site data; IndexedDB comes with the offline app.
export function loadGiven(lesson: number): Record<number, Given> {
  try {
    return JSON.parse(localStorage.getItem(key(lesson)) ?? '{}') as Record<number, Given>
  } catch {
    return {}
  }
}

export function saveGiven(lesson: number, given: Record<number, Given>) {
  try {
    if (Object.keys(given).length) localStorage.setItem(key(lesson), JSON.stringify(given))
    else localStorage.removeItem(key(lesson))
  } catch {
    // storage blocked: the answers live until the page closes
  }
}
