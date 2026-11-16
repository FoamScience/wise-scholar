import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { day } from './i18n'
import { Correction } from './Diff'
import Markdown, { AnswerText, InlineMarkdown } from './Md'
import { textDirection } from './text'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Textarea } from '@/components/ui/textarea'
import { cn } from 'cn'

export type Entry = {
  id: number
  topic: string
  kind: 'quiz' | 'writing' | 'practice'
  prompt: string
  said: string
  correct: string
  explanation: string
  misconception: string
  note: string
  pinned: number
  resolved: number
  created: string
}

const page = 'mx-auto flex w-full max-w-(--page) flex-col gap-10 px-6 pt-10 pb-16'
const alert = 'rounded-md bg-warm-tint px-4 py-2 text-warm-ink'

type Patch = { note?: string; pinned?: boolean; resolved?: boolean }

function kindLabel(kind: Entry['kind']) {
  return kind === 'writing' ? 'common.correctedText' : kind === 'practice' ? 'notebook.practiceMiss' : 'notebook.confidentMiss'
}

function EntryCard({ entry: e, onPatch }: { entry: Entry; onPatch: (body: Patch) => void }) {
  const { t } = useTranslation()
  const writing = e.kind === 'writing'
  return (
    <section className={cn('block min-w-0 space-y-3 rounded-lg border border-border bg-card p-6 [&_.katex-display]:max-w-full [&_pre]:max-w-full', e.resolved && 'opacity-60')}>
      <div className="text-sm leading-snug text-muted-foreground">
        {t(kindLabel(e.kind))}, {e.topic}, {day(e.created)}
        {e.pinned ? <Badge variant="secondary" className="ms-2 h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t('notebook.pinned')}</Badge> : null}
      </div>
      {!writing && <Markdown>{e.prompt}</Markdown>}
      <EntryAnswer entry={e} />
      <label className="text-sm text-muted-foreground" htmlFor={`note-${e.id}`}>
        {t('notebook.note')}
      </label>
      <Textarea
        id={`note-${e.id}`}
        dir="auto"
        rows={2}
        defaultValue={e.note}
        onBlur={(ev) => ev.target.value !== e.note && onPatch({ note: ev.target.value })}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" onClick={() => onPatch({ pinned: !e.pinned })}>
          {e.pinned ? t('notebook.unpin') : t('notebook.pin')}
        </Button>
        <Button type="button" variant="outline" onClick={() => onPatch({ resolved: !e.resolved })}>
          {e.resolved ? t('notebook.reopen') : t('notebook.resolve')}
        </Button>
      </div>
    </section>
  )
}

/** What the learner said or wrote, and the right answer or the corrected text. */
function EntryAnswer({ entry: e }: { entry: Entry }) {
  const { t } = useTranslation()
  const writing = e.kind === 'writing'
  return (
    <>
      <div className="attempt flex flex-col gap-0.5 rounded-md bg-muted px-4 py-3 whitespace-pre-wrap">
        <span className="text-sm leading-snug font-medium text-ink-2">{writing ? t('notebook.youWrote') : t('notebook.youSaid')}</span>
        <span className="decoration-warm decoration-2 line-through" dir={textDirection(e.said)}>
          {writing ? e.said : <AnswerText text={e.said} />}
        </span>
      </div>
      <div className="solution space-y-3 rounded-md bg-accent px-4 py-3 [&>:last-child]:mb-0">
        <div className="text-sm leading-snug font-medium text-ink-2">{writing ? t('notebook.corrected') : t('notebook.rightAnswer')}</div>
        {writing ? <Correction attempt={e.said} corrected={e.correct} /> : <Markdown>{e.correct}</Markdown>}
        {e.explanation && <Markdown>{e.explanation}</Markdown>}
        {e.misconception && <p><InlineMarkdown>{t('quiz.belief', { belief: e.misconception })}</InlineMarkdown></p>}
      </div>
    </>
  )
}

/** The learner's own confident misses and corrected texts, with a note in their words; open ones lead the reviews. */
export function ErrorsPage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<Entry[] | null>(null)
  const [showResolved, setShowResolved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Entry[]>(`/api/errors?profile=${profile}`).then(setEntries, (e: Error) => setError(e.message))
  }, [profile])

  function patch(id: number, body: Patch) {
    api<Entry>(`/api/errors/${id}`, body).then(
      (updated) => setEntries((all) => all && all.map((e) => (e.id === id ? updated : e))),
      (e: Error) => setError(e.message),
    )
  }

  if (!entries) return <main className={page}>{error && <div className={alert}>{error}</div>}</main>
  const shown = entries.filter((e) => showResolved || !e.resolved)
  const open = entries.filter((e) => !e.resolved).length

  return (
    <main className={page}>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="m-0 max-w-none grow">{t('notebook.heading', { n: open })}</h1>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Checkbox checked={showResolved} onCheckedChange={setShowResolved} /> {t('notebook.showResolved')}
        </label>
      </div>
      {error && <div className={alert}>{error}</div>}
      {shown.length === 0 && <div className="text-muted-foreground">{t('notebook.empty')}</div>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,26rem),1fr))] items-start gap-4">
        {shown.map((e) => (
          <EntryCard key={e.id} entry={e} onPatch={(body) => patch(e.id, body)} />
        ))}
      </div>
    </main>
  )
}
