import { useTranslation } from 'react-i18next'
import type { Area } from './course'

/** What the placement check found in each area: what the learner has, and where it ends. */
export function PlacementAreas({ areas }: { areas?: Area[] }) {
  const { t } = useTranslation()
  if (!areas?.length) return null
  return (
    <dl className="mt-3 mb-0 grid gap-2">
      {areas.map((a) => (
        <div key={a.title}>
          <dt dir="auto" className="font-medium">{a.title}</dt>
          <dd dir="auto" className="m-0">
            <span className="text-sm text-muted-foreground">{t('areas.holds')}</span> {a.holds || t('areas.nothingYet')}
          </dd>
          <dd dir="auto" className="m-0">
            <span className="text-sm text-muted-foreground">{t('areas.lacks')}</span> {a.lacks || t('areas.nothingLeft')}
          </dd>
        </div>
      ))}
    </dl>
  )
}
