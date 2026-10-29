import { useTranslation } from 'react-i18next'
import type { ChallengeData } from './course'
import { Correction } from './Diff'
import { AttemptPhotos } from './Handwork'
import Markdown from './Md'
import { splitBy, textDirection } from './text'

export function Ladder({ data: d, blockId }: { data: ChallengeData; blockId?: number }) {
  const { t } = useTranslation()
  return (
    <>
      {d.attempts.map((a, i) => (
        <div key={i} className="attempt">
          <span className="label">{t('common.attempt', { n: i + 1 })}</span>
          <span dir={textDirection(a)}>
            {splitBy(a, i === d.attempts.length - 1 ? (d.marks ?? []) : []).map((piece, j) =>
              piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text,
            )}
          </span>
          {blockId !== undefined && <AttemptPhotos blockId={blockId} data={d} attempt={i} />}
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
        <div key={i} className="hint">
          <div className="label">
            {t(d.writing ? 'challenge.promptOf' : 'challenge.hintOf', { n: i + 1, max: d.max_hints })}
            {d.writing && ` ${t('challenge.notCorrection')}`}
          </div>
          <Markdown>{h}</Markdown>
        </div>
      ))}
      {d.solution !== null && (
        <div className="solution">
          <div className="label">{d.writing ? t('common.correctedText') : t('common.solution')}</div>
          {d.writing && d.attempts.length > 0 ? (
            <Correction attempt={d.attempts[d.attempts.length - 1]} corrected={d.solution} />
          ) : (
            <Markdown>{d.solution}</Markdown>
          )}
        </div>
      )}
    </>
  )
}

export function Comparison({ data }: { data: ChallengeData }) {
  const { t } = useTranslation()
  const c = data.comparison
  if (!c) return null
  return (
    <>
      <div className="compare">
        {([c.left, c.right] as const).map((solution, i) => (
          <div key={i} className="side">
            <div className="label">{t('challenge.solution', { n: i + 1 })}</div>
            <Markdown>{solution}</Markdown>
          </div>
        ))}
      </div>
      <Markdown>{c.question}</Markdown>
    </>
  )
}
