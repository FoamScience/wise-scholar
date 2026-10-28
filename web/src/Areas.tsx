import { useTranslation } from 'react-i18next'
import type { Area } from './course'

/** What the placement check found in each area: what the learner has, and where it ends. */
export function PlacementAreas({ areas }: { areas?: Area[] }) {
  const { t } = useTranslation()
  if (!areas?.length) return null
  return (
    <dl className="areas">
      {areas.map((a) => (
        <div key={a.title}>
          <dt dir="auto">{a.title}</dt>
          <dd dir="auto">
            <span className="small">{t('areas.holds')}</span> {a.holds || t('areas.nothingYet')}
          </dd>
          <dd dir="auto">
            <span className="small">{t('areas.lacks')}</span> {a.lacks || t('areas.nothingLeft')}
          </dd>
        </div>
      ))}
    </dl>
  )
}
