import { useTranslation } from 'react-i18next'
import type { OutlineData } from './course'
import { InlineMarkdown } from './Md'

function OutlineStep({ step, done, current }: { step: string; done: boolean; current: boolean }) {
  const { t } = useTranslation()
  return (
    <li className={done ? 'done' : current ? 'current' : undefined} aria-current={current ? 'step' : undefined}>
      <InlineMarkdown>{step}</InlineMarkdown>
      {done && <span className="small"> ({t('common.done')})</span>}
    </li>
  )
}

function TestOut({ onTestOut }: { onTestOut: (scope: 'step' | 'unit') => void }) {
  const { t } = useTranslation()
  return (
    <div className="row">
      <button type="button" className="btn" onClick={() => onTestOut('step')}>
        {t('outline.testStep')}
      </button>
      <button type="button" className="btn" onClick={() => onTestOut('unit')}>
        {t('outline.testUnit')}
      </button>
    </div>
  )
}

/** The unit's plan: steps done, the current one, and the one step the tutor added with its reason. */
export function OutlineCard({ data, onTestOut }: { data: OutlineData; onTestOut?: (scope: 'step' | 'unit') => void }) {
  const { t } = useTranslation()
  return (
    <section className="block outline">
      <div className="label">
        {t('outline.label')}: {data.at >= data.steps.length ? t('outline.allDone') : t('outline.step', { n: data.at + 1, total: data.steps.length })}
      </div>
      <ol>
        {data.steps.map((step, i) => (
          <OutlineStep key={step} step={step} done={i < data.at} current={i === data.at} />
        ))}
      </ol>
      {data.added && <p className="small">{t('outline.added', { step: data.added.step, reason: data.added.reason })}</p>}
      {onTestOut && data.at < data.steps.length && <TestOut onTestOut={onTestOut} />}
    </section>
  )
}
