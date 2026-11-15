import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { QuizData } from './Quiz'
import type { Block, ChallengeData, ExerciseData } from './course'

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
        className="edit-form"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <label className="small">{t('edit.text')}</label>
        <textarea className="field" dir="auto" rows={4} value={draft.markdown} onChange={set('markdown')} />
        {task && (
          <>
            <label className="small">{t('edit.hints')}</label>
            <textarea className="field" dir="auto" rows={3} value={draft.hints} onChange={set('hints')} />
            <label className="small">{t('edit.solution')}</label>
            <textarea className="field" dir="auto" rows={4} value={draft.solution} onChange={set('solution')} />
            {kind === 'exercise' && (
              <>
                <label className="small">{t('edit.run')}</label>
                <input className="field" dir="ltr" value={draft.run} onChange={set('run')} />
              </>
            )}
          </>
        )}
        {quiz && (
          <>
            {draft.options !== '' || (block.data as QuizData).kind === 'choice' ? (
              <>
                <label className="small">{t('edit.options')}</label>
                <textarea className="field" dir="auto" rows={4} value={draft.options} onChange={set('options')} />
              </>
            ) : null}
            <label className="small">{t('edit.key')}</label>
            <input className="field" dir="auto" value={draft.answer_key} onChange={set('answer_key')} />
            <label className="small">{t('edit.explanation')}</label>
            <textarea className="field" dir="auto" rows={3} value={draft.explanation} onChange={set('explanation')} />
          </>
        )}
        <div className="row">
          <button className="btn primary" disabled={!draft.markdown.trim()}>
            {t('edit.save')}
          </button>
          <button type="button" className="btn" onClick={() => setDraft(null)}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="edit-bar row">
      <button type="button" className="link" disabled={props.disabled} onClick={() => setDraft(draftOf(block))}>
        {t('edit.edit')}
      </button>
      <button type="button" className="link" disabled={props.disabled || props.first} onClick={() => act('move', { direction: 'up' })}>
        {t('edit.up')}
      </button>
      <button type="button" className="link" disabled={props.disabled || props.last} onClick={() => act('move', { direction: 'down' })}>
        {t('edit.down')}
      </button>
      {confirming ? (
        <>
          <button type="button" className="btn danger" disabled={props.disabled} onClick={() => act('remove')}>
            {t('edit.removeConfirm')}
          </button>
          <button type="button" className="link" onClick={() => setConfirming(false)}>
            {t('common.cancel')}
          </button>
        </>
      ) : (
        <button type="button" className="link" disabled={props.disabled} onClick={() => setConfirming(true)}>
          {t('edit.remove')}
        </button>
      )}
    </div>
  )
}
