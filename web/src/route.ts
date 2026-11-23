export type CourseRoute =
  | { page: 'workspace'; courseId: number; concept: number | null; start: 'episode' | 'writing' | 'roleplay' | null; found: { lesson: number; at: string } | null }
  | { page: 'search'; courseId: number; query: string; kind: string }
  | { page: 'recap'; courseId: number; preview: boolean }
  | { page: 'book'; courseId: number }
  | { page: 'handout'; lessonId: number; version: 'student' | 'teacher' }
  | { page: 'publish'; courseId: number }

export type ProfileRoute =
  | { page: 'review'; then: string | null }
  | { page: 'graph'; course: number | null }
  | { page: 'explore' | 'errors' | 'sitting' | 'commands' | 'usage' | 'settings' }

const PROFILE_PAGES = ['explore', 'errors', 'sitting', 'commands', 'usage', 'settings'] as const

/** The page of one course or lesson a hash names; a search hit opens the workspace at its card or chat message. */
export function courseRoute(hash: string): CourseRoute | null {
  const match = hash.match(/^#\/course\/(\d+)(?:\?concept=(\d+)|\?start=(episode|writing|roleplay)|\?lesson=(\d+)&(card|chat)=(\d+))?$/)
  if (match)
    return {
      page: 'workspace',
      courseId: Number(match[1]),
      concept: match[2] ? Number(match[2]) : null,
      start: (match[3] as 'episode' | 'writing' | 'roleplay' | undefined) ?? null,
      found: match[4] ? { lesson: Number(match[4]), at: `${match[5] === 'chat' ? 'msg' : 'block'}-${match[6]}` } : null,
    }
  const found = hash.match(/^#\/course\/(\d+)\/search\?(.*)$/)
  if (found) {
    const params = new URLSearchParams(found[2])
    return { page: 'search', courseId: Number(found[1]), query: params.get('q') ?? '', kind: params.get('kind') ?? '' }
  }
  const recapped = hash.match(/^#\/course\/(\d+)\/recap(\?preview)?$/)
  if (recapped) return { page: 'recap', courseId: Number(recapped[1]), preview: Boolean(recapped[2]) }
  const book = hash.match(/^#\/course\/(\d+)\/book$/)
  if (book) return { page: 'book', courseId: Number(book[1]) }
  const handout = hash.match(/^#\/lesson\/(\d+)\/handout\/(student|teacher)$/)
  if (handout) return { page: 'handout', lessonId: Number(handout[1]), version: handout[2] as 'student' | 'teacher' }
  const publishing = hash.match(/^#\/course\/(\d+)\/publish$/)
  if (publishing) return { page: 'publish', courseId: Number(publishing[1]) }
  return null
}

/** The page across the profile's courses a hash names. */
export function profileRoute(hash: string): ProfileRoute | null {
  const review = hash.match(/^#\/review(?:\?then=(.*))?$/)
  if (review) return { page: 'review', then: review[1] ? decodeURIComponent(review[1]) : null }
  const graph = hash.match(/^#\/graph(?:\?course=(\d+))?$/)
  if (graph) return { page: 'graph', course: graph[1] ? Number(graph[1]) : null }
  const page = PROFILE_PAGES.find((p) => hash === `#/${p}`)
  return page ? { page } : null
}
