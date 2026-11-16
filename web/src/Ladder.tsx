import { useTranslation } from 'react-i18next'
import { type ChallengeData, saidIn } from './course'
import { Correction } from './Diff'
import { AttemptWork } from './Handwork'
import Markdown from './Md'
import { splitBy, textDirection } from './text'

export function Ladder({ data: d, blockId, onError }: { data: ChallengeData; blockId?: number; onError?: (m: string) => void }) {
  const { t } = useTranslation()
  return (
    <>
      {d.attempts.map((a, i) => (
        <div key={i} className="attempt flex flex-col gap-0.5 rounded-md bg-muted px-4 py-3 whitespace-pre-wrap">
          <span className="text-sm leading-snug font-medium text-ink-2">{t('common.attempt', { n: i + 1 })}</span>
          <span dir={textDirection(a)}>
            {splitBy(a, i === d.attempts.length - 1 ? (d.marks ?? []) : []).map((piece, j) =>
              piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text,
            )}
          </span>
          {blockId !== undefined && (
            <AttemptWork blockId={blockId} data={d} attempt={i} marks={i === d.attempts.length - 1 ? (d.marks ?? []) : []} onError={onError} />
          )}
        </div>
      ))}
      <HintList data={d} />
    </>
  )
}

export function HintList({ data: d }: { data: ChallengeData }) {
  const { t } = useTranslation()
  return (
    <>
      {d.hints.map((h, i) => (
        <div key={i} className="hint rounded-md bg-warm-tint px-4 py-3 text-warm-ink [&>:last-child]:mb-0">
          <div className="text-sm leading-snug font-medium text-warm">
            {t(d.writing ? 'challenge.promptOf' : 'challenge.hintOf', { n: i + 1, max: d.max_hints })}
            {d.writing && ` ${t('challenge.notCorrection')}`}
          </div>
          <Markdown>{h}</Markdown>
        </div>
      ))}
      {d.solution !== null && (
        <div className="solution rounded-md bg-accent px-4 py-3 [&>:last-child]:mb-0">
          <div className="text-sm leading-snug font-medium text-ink-2">{d.writing ? t('common.correctedText') : t('common.solution')}</div>
          {d.writing && d.attempts.length > 0 ? (
            <Correction attempt={saidIn(d, d.attempts.length - 1)} corrected={d.solution} />
          ) : (
            <Markdown>{d.solution}</Markdown>
          )}
        </div>
      )}
    </>
  )
}

/** What the task needs that the learner has not met yet, folded away until they want it. */
export function Helper({ data, open = false }: { data: ChallengeData; open?: boolean }) {
  const { t } = useTranslation()
  if (!data.helper) return null
  return (
    <details open={open}>
      <summary className="cursor-pointer text-sm text-muted-foreground">{t('challenge.helper')}</summary>
      <Markdown>{data.helper}</Markdown>
    </details>
  )
}

export function Comparison({ data }: { data: ChallengeData }) {
  const { t } = useTranslation()
  const c = data.comparison
  if (!c) return null
  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-3">
        {([c.left, c.right] as const).map((solution, i) => (
          <div key={i} className="min-w-0 rounded-lg border border-border p-3">
            <div className="text-sm leading-snug font-medium text-ink-2">{t('challenge.solution', { n: i + 1 })}</div>
            <Markdown>{solution}</Markdown>
          </div>
        ))}
      </div>
      <Markdown>{c.question}</Markdown>
    </>
  )
}
