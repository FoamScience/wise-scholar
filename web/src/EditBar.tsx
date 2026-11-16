import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { QuizData } from './Quiz'
import type { Block, ChallengeData, ExerciseData } from './course'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const LABEL = 'text-sm text-muted-foreground'
const LINK = 'text-ink-2'

type Draft = { markdown: string; solution: string; hints: string; run: string; options: string; answer_key: string; explanation: string }

function draftOf(block: Block): Draft {
  const d = (block.data ?? {}) as Partial<ChallengeData & ExerciseData & QuizData>
  return {
    markdown: block.markdown,
    solution: d.solution ?? '',
    hints: (d.hints ?? []).join('\n'),
    run: d.run ?? '',
    options: d.kind === 'choice' ? (d.options as string[]).join('\n') : '',
    answer_key: d.answer_key ?? '',
    explanation: d.explanation ?? '',
  }
}

/** A teacher's hand on a card of a prepared course: edit its text and answers, move it, remove it. */
export function EditBar(props: { block: Block; first: boolean; last: boolean; disabled: boolean; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const { block } = props
  const [draft, setDraft] = useState<Draft | null>(null)
  const [confirming, setConfirming] = useState(false)
  const kind = block.kind
  const task = kind === 'challenge' || kind === 'exercise' || kind === 'speaking'
  const quiz = kind === 'quiz'

  function act(path: string, body: unknown = {}) {
    return api(`/api/blocks/${block.id}/${path}`, body).catch((err: Error) => props.onError(err.message))
  }

  function save() {
    if (!draft) return
    const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)
    const body: Record<string, unknown> = { markdown: draft.markdown }
    if (task) Object.assign(body, { solution: draft.solution, hints: lines(draft.hints), run: draft.run })
    if (quiz) Object.assign(body, { options: lines(draft.options), answer_key: draft.answer_key, explanation: draft.explanation })
    act('edit', body).then(() => setDraft(null))
  }

  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setDraft((d) => d && { ...d, [key]: e.target.value })

  if (draft) {
    return (
      <form
        className="flex flex-col gap-2 rounded-lg border border-dashed px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <label className={LABEL}>{t('edit.text')}</label>
        <Textarea dir="auto" rows={4} value={draft.markdown} onChange={set('markdown')} />
        {task && (
          <>
            <label className={LABEL}>{t('edit.hints')}</label>
            <Textarea dir="auto" rows={3} value={draft.hints} onChange={set('hints')} />
            <label className={LABEL}>{t('edit.solution')}</label>
            <Textarea dir="auto" rows={4} value={draft.solution} onChange={set('solution')} />
            {kind === 'exercise' && (
              <>
                <label className={LABEL}>{t('edit.run')}</label>
                <Input dir="ltr" value={draft.run} onChange={set('run')} />
              </>
            )}
          </>
        )}
        {quiz && (
          <>
            {draft.options !== '' || (block.data as QuizData).kind === 'choice' ? (
              <>
                <label className={LABEL}>{t('edit.options')}</label>
                <Textarea dir="auto" rows={4} value={draft.options} onChange={set('options')} />
              </>
            ) : null}
            <label className={LABEL}>{t('edit.key')}</label>
            <Input dir="auto" value={draft.answer_key} onChange={set('answer_key')} />
            <label className={LABEL}>{t('edit.explanation')}</label>
            <Textarea dir="auto" rows={3} value={draft.explanation} onChange={set('explanation')} />
          </>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!draft.markdown.trim()}>
            {t('edit.save')}
          </Button>
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>
            {t('common.cancel')}
          </Button>
        </div>
      </form>
    )
  }

  return (
    <div className="-mt-3 flex flex-wrap items-center gap-4 text-sm">
      <Button type="button" variant="ghost" className={LINK} disabled={props.disabled} onClick={() => setDraft(draftOf(block))}>
        {t('edit.edit')}
      </Button>
      <Button type="button" variant="ghost" className={LINK} disabled={props.disabled || props.first} onClick={() => act('move', { direction: 'up' })}>
        {t('edit.up')}
      </Button>
      <Button type="button" variant="ghost" className={LINK} disabled={props.disabled || props.last} onClick={() => act('move', { direction: 'down' })}>
        {t('edit.down')}
      </Button>
      {confirming ? (
        <>
          <Button type="button" variant="destructive" disabled={props.disabled} onClick={() => act('remove')}>
            {t('edit.removeConfirm')}
          </Button>
          <Button type="button" variant="ghost" className={LINK} onClick={() => setConfirming(false)}>
            {t('common.cancel')}
          </Button>
        </>
      ) : (
        <Button type="button" variant="ghost" className={LINK} disabled={props.disabled} onClick={() => setConfirming(true)}>
          {t('edit.remove')}
        </Button>
      )}
    </div>
  )
}
