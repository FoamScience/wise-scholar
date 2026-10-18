import { useTranslation } from 'react-i18next'
import type { OutlineData } from './course'

/** The unit's plan: steps done, the current one, and the one step the tutor added with its reason. */
export function OutlineCard({ data }: { data: OutlineData }) {
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
    </section>
  )
}
