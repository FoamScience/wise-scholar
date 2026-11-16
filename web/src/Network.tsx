import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from 'cn'

export type NetworkData = {
  command: string
  status: 'asked' | 'running' | 'allowed' | 'refused'
  result: { exit_code: number | null; output: string } | null
}

const CHIP = 'ms-2 h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground'
const PRE = 'm-0 overflow-x-auto rounded-md bg-code px-4 py-3 font-mono text-[0.93em] whitespace-pre-wrap text-code-foreground wrap-anywhere'
const WARN = 'ms-2 h-auto rounded-sm bg-warm-tint px-2 py-0.5 text-sm text-warm'

/** The tutor's request to run one command with internet: the learner reads the command and decides. */
export function NetworkCard(props: { id: number; reason: string; data: unknown; disabled: boolean; onDecide?: (allow: boolean) => void }) {
  const { t } = useTranslation()
  const d = props.data as NetworkData
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-3 border-t pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">
        {t('network.label')}
        {d.status === 'allowed' && <Badge className={CHIP}>{t('network.allowed')}</Badge>}
        {d.status === 'refused' && <Badge className={WARN}>{t('network.refused')}</Badge>}
      </div>
      <div dir="auto">{props.reason}</div>
      <pre className={PRE}>
        <code>$ {d.command}</code>
      </pre>
      {d.status === 'asked' && props.onDecide && (
        <>
          <div className="text-sm text-muted-foreground">{t('network.explain')}</div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" disabled={props.disabled} onClick={() => props.onDecide?.(false)}>
              {t('network.refuse')}
            </Button>
            <Button type="button" disabled={props.disabled} onClick={() => props.onDecide?.(true)}>
              {t('network.allow')}
            </Button>
          </div>
        </>
      )}
      {d.status === 'running' && <div className="text-muted-foreground">{t('network.running')}</div>}
      {d.result && (
        <div className="overflow-hidden rounded-md border">
          <div className="flex min-h-11 items-center justify-between gap-3 ps-4 pe-1 wrap-anywhere">
            <span className="text-sm leading-snug font-medium text-ink-2">{d.result.exit_code === null ? t('network.stopped') : t('network.exit', { code: d.result.exit_code })}</span>
          </div>
          <pre className={cn(PRE, 'max-h-[420px] overflow-auto rounded-none', d.result.exit_code !== 0 && 'text-[var(--code-failed)]')}>{d.result.output || t('exercise.noOutput')}</pre>
        </div>
      )}
    </section>
  )
}
