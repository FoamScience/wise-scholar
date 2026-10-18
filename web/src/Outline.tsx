import { useTranslation } from 'react-i18next'
import type { OutlineData } from './course'

/** The unit's plan: steps done, the current one, and the one step the tutor added with its reason. */
export function OutlineCard({ data, onTestOut }: { data: OutlineData; onTestOut?: (scope: 'step' | 'unit') => void }) {
  const { t } = useTranslation()
  return (
    <section className="block outline">
      <div className="label">
        {t('outline.label')} · {data.at >= data.steps.length ? t('outline.allDone') : t('outline.step', { n: data.at + 1, total: data.steps.length })}
      </div>
      <ol>
        {data.steps.map((step, i) => (
          <li key={step} className={i < data.at ? 'done' : i === data.at ? 'current' : undefined} aria-current={i === data.at ? 'step' : undefined}>
            {step}
            {i < data.at && <span className="small"> · {t('common.done')}</span>}
          </li>
        ))}
      </ol>
      {data.added && <p className="small">{t('outline.added', { step: data.added.step, reason: data.added.reason })}</p>}
      {onTestOut && data.at < data.steps.length && (
        <div className="row">
          <button type="button" className="btn" onClick={() => onTestOut('step')}>
            {t('outline.testStep')}
          </button>
          <button type="button" className="btn" onClick={() => onTestOut('unit')}>
            {t('outline.testUnit')}
          </button>
        </div>
      )}
    </section>
  )
}
