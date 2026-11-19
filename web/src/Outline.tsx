import { useTranslation } from 'react-i18next'
import type { OutlineData } from './course'
import { InlineMarkdown } from './Md'
import { Button } from '@/components/ui/button'
import { cn } from 'cn'

function OutlineStep({ step, done, current }: { step: string; done: boolean; current: boolean }) {
  const { t } = useTranslation()
  return (
    <li className={cn('py-0.5 transition-colors duration-(--motion) ease-(--ease)', done && 'text-muted-foreground', current && 'font-semibold text-accent-foreground')} aria-current={current ? 'step' : undefined}>
      <InlineMarkdown>{step}</InlineMarkdown>
      {done && <span className="text-sm text-muted-foreground"> ({t('common.done')})</span>}
    </li>
  )
}

function TestOut({ onTestOut }: { onTestOut: (scope: 'step' | 'unit') => void }) {
  const { t } = useTranslation()
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" onClick={() => onTestOut('step')}>
        {t('outline.testStep')}
      </Button>
      <Button type="button" variant="outline" onClick={() => onTestOut('unit')}>
        {t('outline.testUnit')}
      </Button>
    </div>
  )
}

/** The unit's plan: steps done, the current one, and the one step the tutor added with its reason. */
export function OutlineCard({ data, onTestOut }: { data: OutlineData; onTestOut?: (scope: 'step' | 'unit') => void }) {
  const { t } = useTranslation()
  return (
    <section className="block border-t pt-6">
      <div className="mb-2 text-sm leading-snug font-medium text-ink-2">
        {t('outline.status', { progress: data.at >= data.steps.length ? t('outline.allDone') : t('outline.step', { n: data.at + 1, total: data.steps.length }) })}
      </div>
      <ol className="m-0 list-decimal ps-6">
        {data.steps.map((step, i) => (
          <OutlineStep key={step} step={step} done={i < data.at} current={i === data.at} />
        ))}
      </ol>
      {data.added && <p className="m-0 text-sm text-muted-foreground">{t('outline.added', { step: data.added.step, reason: data.added.reason })}</p>}
      {onTestOut && data.at < data.steps.length && <TestOut onTestOut={onTestOut} />}
    </section>
  )
}
