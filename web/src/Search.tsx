import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { SEARCH_KINDS, type SearchKind, searchHref } from './course'
import Markdown from './Md'

type Hit = {
  kind: SearchKind
  ref: string
  lesson_id: number | null
  concept_id: number | null
  title: string
  text: string
  snippet: [string, boolean][]
  by: 'words' | 'meaning' | 'both'
}

/** The course's sources, lesson cards, chats and code found by their words or their meaning. */
export function SearchPage({ courseId, query, kind: asked }: { courseId: number; query: string; kind: string }) {
  const { t } = useTranslation()
  const kind = SEARCH_KINDS.find((k) => k === asked) ?? ''
  const [draft, setDraft] = useState(query)
  const [hits, setHits] = useState<Hit[] | null>(null)
  const [error, setError] = useState('')

  // the page is keyed by its address, so a new search starts from empty state
  useEffect(() => {
    if (!query.trim()) return
    api<Hit[]>(`/api/courses/${courseId}/search?${new URLSearchParams({ q: query, kind })}`).then(setHits, (e: Error) => setError(e.message))
  }, [courseId, query, kind])

  return (
    <main className="home search-page">
      <a className="btn as-link" href={`#/course/${courseId}`}>{t('book.back')}</a>
      <form
        className="search-form"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          location.hash = searchHref(courseId, draft, kind)
        }}
      >
        <input type="search" className="field" dir="auto" aria-label={t('search.label')} placeholder={t('search.placeholder')} value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button type="submit" className="btn primary">
          {t('search.go')}
        </button>
      </form>
      <div className="cats" role="group" aria-label={t('search.kinds')}>
        {(['', ...SEARCH_KINDS] as const).map((k) => (
          <a key={k} className={k === kind ? 'cat picked' : 'cat'} aria-current={k === kind} href={searchHref(courseId, query, k)}>
            {t(`search.kind.${k || 'all'}`)}
          </a>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      {hits === null && query.trim() && !error && <div className="muted">{t('search.searching')}</div>}
      {hits?.length === 0 && query.trim() && <div className="muted">{t('search.none')}</div>}
      {hits?.map((h) => (
        <section key={`${h.kind}-${h.ref}`} className="block hit">
          <div className="label">
            <span className="chip">{t(`search.kind.${h.kind}`)}</span> <span dir="auto">{h.kind === 'code' ? h.ref : h.title}</span>
            {h.by !== 'words' && <span className={`chip by-${h.by}`}>{t(`search.by.${h.by}`)}</span>}
          </div>
          <p dir="auto" className="snippet">
            {h.snippet.map(([piece, matched], i) => (matched ? <mark key={i}>{piece}</mark> : piece))}
          </p>
          {h.lesson_id !== null ? (
            <a className="btn as-link" href={h.concept_id === null ? `#/course/${courseId}` : `#/course/${courseId}?concept=${h.concept_id}`}>{t('search.openLesson')}</a>
          ) : (
            <details>
              <summary>{t('search.showPassage')}</summary>
              {h.kind === 'code' ? (
                <pre>
                  <code>{h.text}</code>
                </pre>
              ) : (
                <div dir="auto">
                  <Markdown>{h.text}</Markdown>
                </div>
              )}
            </details>
          )}
        </section>
      ))}
    </main>
  )
}
