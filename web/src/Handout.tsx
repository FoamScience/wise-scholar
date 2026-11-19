import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { api, failure } from './api'
import type { Lesson } from './course'
import { useTheme } from './theme'
import { pageStyle } from './print'
import { Swap } from './Swap'
import { Button, buttonVariants } from '@/components/ui/button'


type Version = 'student' | 'teacher'
type Head = Pick<Lesson, 'id' | 'title' | 'phase' | 'concept_id'> & { course_id: number; topic: string }

/** A unit's lesson plan as a printable page: the teacher's copy or the students' copy; the server prints it to PDF. */
export function Handout({ lessonId, version, pdf }: { lessonId: number; version: Version; pdf: boolean }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const [head, setHead] = useState<Head | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [preparing, setPreparing] = useState(false)

  useEffect(() => {
    // The route carries the version: a new key remounts the page, so the old text never shows under a new title.
    api<Head>(`/api/lessons/${lessonId}`).then(setHead, (e: Error) => setError(e.message))
    fetch(`/api/lessons/${lessonId}/handout.md?version=${version}`)
      .then(async (res) => {
        if (res.status === 409) return setUnavailable(true)
        return res.ok ? setText(await res.text()) : Promise.reject(await failure(res))
      })
      .catch((e: Error) => setError(e.message))
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
  if (!error && !unavailable && (!head || text === null)) return <main className="mx-auto w-full max-w-[var(--measure)] px-6 pt-10 pb-16" />
  const other: Version = version === 'student' ? 'teacher' : 'student'

  return (
    <main className="book mx-auto flex w-full max-w-[820px] flex-col gap-4 px-6 pt-6 pb-16 print:block print:max-w-none print:p-0 print:text-[10.5pt] print:[&>*+*]:mt-4">
      <style key={theme}>{pageStyle(head?.topic ?? '')}</style>
      <div className="flex items-center gap-4 print:hidden">
        <a className={buttonVariants({ variant: 'outline' })} href={head ? `#/course/${head.course_id}?concept=${head.concept_id}` : '#/'}>{t('handout.back')}</a>
        {!unavailable && (
          <>
            <a className={buttonVariants({ variant: 'outline' })} href={`#/lesson/${lessonId}/handout/${other}`}>
              {t(`handout.${other}`)}
            </a>
            <a className={buttonVariants({ variant: 'outline' })} href={`/api/lessons/${lessonId}/handout.md?version=${version}`} download>
              {t('handout.markdown')}
            </a>
            <span className="grow" />
            {pdf ? (
              <Button type="button" disabled={preparing} onClick={download}>
                <Swap labels={[t('book.download'), t('book.preparing')]} at={preparing ? 1 : 0} />
              </Button>
            ) : (
              <Button type="button" onClick={() => window.print()}>
                {t('book.save')}
              </Button>
            )}
          </>
        )}
      </div>
      {(unavailable || error) && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{unavailable ? t('handout.unavailable') : error}</div>}
      {!unavailable && (
        <header className="book-cover flex flex-col items-start gap-4 rounded-lg bg-primary px-16 pt-16 pb-10 text-primary-foreground print:box-border print:h-[296mm] print:rounded-none print:px-[24mm] print:pt-[40mm] print:pb-[24mm] print:break-after-page">
          <span className="text-sm font-semibold">{t(`handout.${version}`)}</span>
          <h1 className="m-0 text-[48px] leading-[1.1] font-semibold" dir="auto">{head?.title ?? ''}</h1>
          <div className="text-lg" dir="auto">
            {head?.topic ?? ''}
          </div>
        </header>
      )}
      {text !== null && (
        <section className="flex flex-col gap-4 print:block print:[&>*+*]:mt-4">
          <Markdown>{text}</Markdown>
        </section>
      )}
    </main>
  )
}
