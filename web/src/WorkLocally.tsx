import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { localCommands } from './workLocally'

const COMMANDS = 'm-0 overflow-auto rounded-md bg-code px-4 py-3 text-start text-[0.93em] text-code-foreground'

/** How to work on the exercise in the learner's own editor with ws.py, which this server hands out. */
export function WorkLocally(props: { blockId: number }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const { setup, submit } = localCommands(location.origin, props.blockId)
  return (
    <details className="group rounded-md border border-border">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 ps-4 pe-1 text-sm text-ink-2 [&::-webkit-details-marker]:hidden">
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform duration-(--dur-micro) group-not-open:ltr:-rotate-90 group-not-open:rtl:rotate-90" />
        {t('workLocally.title')}
      </summary>
      <div className="flex flex-col gap-3 px-4 pb-4 text-sm">
        <p className="m-0">{t('workLocally.install')}</p>
        <pre dir="ltr" className={COMMANDS}>{setup}</pre>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" onClick={() => navigator.clipboard.writeText(setup).then(() => setCopied(true), () => {})}>
            {copied ? t('workLocally.copied') : t('workLocally.copy')}
          </Button>
          <a href="/api/ws.py" download="ws.py" className="text-ink-2 underline">{t('workLocally.download')}</a>
        </div>
        <p className="m-0">{t('workLocally.after')}</p>
        <pre dir="ltr" className={COMMANDS}>{submit}</pre>
        <p className="m-0 text-muted-foreground">{t('workLocally.noPassword')}</p>
      </div>
    </details>
  )
}
