import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api, failure } from './api'
import type { Lesson } from './course'
import { useTheme } from './theme'
import { pageStyle } from './print'

type Version = 'student' | 'teacher'
type Head = Pick<Lesson, 'id' | 'title' | 'phase' | 'concept_id'> & { course_id: number; topic: string }

/** A unit's lesson plan as a printable page: the teacher's copy or the students' copy; the server prints it to PDF. */
export function Handout({ lessonId, version, pdf }: { lessonId: number; version: Version; pdf: boolean }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const [head, setHead] = useState<Head | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [preparing, setPreparing] = useState(false)

  useEffect(() => {
    // The route carries the version: a new key remounts the page, so the old text never shows under a new title.
    api<Head>(`/api/lessons/${lessonId}`).then(setHead, (e: Error) => setError(e.message))
    fetch(`/api/lessons/${lessonId}/handout.md?version=${version}`)
      .then(async (res) => (res.ok ? res.text() : Promise.reject(await failure(res))))
      .then(setText, (e: Error) => setError(e.message))
  }, [lessonId, version])

  async function download() {
    setPreparing(true)
    setError('')
    try {
      const res = await fetch(`/api/lessons/${lessonId}/handout.pdf?version=${version}&theme=${theme === 'dark' ? 'dark' : 'light'}`)
      if (!res.ok) throw await failure(res)
      const link = document.createElement('a')
      link.href = URL.createObjectURL(await res.blob())
      link.download = `${head?.title ?? 'handout'} (${version}).pdf`
      link.click()
      setTimeout(() => URL.revokeObjectURL(link.href), 60_000)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPreparing(false)
    }
  }

  // The cover shows even when a request failed, so the printer sees the page settle and the error is printed on it.
  if (!error && (!head || text === null)) return <main className="home" />
  const other: Version = version === 'student' ? 'teacher' : 'student'

  return (
    <main className="book">
      <style key={theme}>{pageStyle(head?.topic ?? '')}</style>
      <div className="book-bar">
        <a href={head ? `#/course/${head.course_id}?concept=${head.concept_id}` : '#/'}>{t('handout.back')}</a>
        <a className="small" href={`#/lesson/${lessonId}/handout/${other}`}>
          {t(`handout.${other}`)}
        </a>
        <a className="small grow" href={`/api/lessons/${lessonId}/handout.md?version=${version}`} download>
          {t('handout.markdown')}
        </a>
        {pdf ? (
          <button type="button" className="btn primary" disabled={preparing} onClick={download}>
            {preparing ? t('book.preparing') : t('book.download')}
          </button>
        ) : (
          <button type="button" className="btn primary" onClick={() => window.print()}>
            {t('book.save')}
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      <header className="book-cover handout-cover">
        <span className="book-number">{t(`handout.${version}`)}</span>
        <h1 dir="auto">{head?.title ?? ''}</h1>
        <div className="book-subtitle" dir="auto">
          {head?.topic ?? ''}
        </div>
      </header>
      {text !== null && (
        <section className="chapter">
          <Markdown>{text}</Markdown>
        </section>
      )}
    </main>
  )
}
