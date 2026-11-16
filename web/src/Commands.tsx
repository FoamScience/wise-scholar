import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { Badge } from '@/components/ui/badge'
import { moment, number } from './i18n'

const MAIN = 'mx-auto flex w-full max-w-160 flex-col gap-10 px-6 pt-10 pb-16'
const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const PRE = 'my-2 overflow-x-auto rounded-md bg-code px-4 py-3 font-mono text-[0.93em] text-code-foreground'

type Entry = {
  id: number
  topic: string
  lesson: string
  origin: 'tutor' | 'learner' | 'network'
  command: string
  consent: 'none' | 'allowed' | 'refused'
  exit_code: number | null
  output: string
  started: string
  seconds: number | null
}

/** Every command run for the learner's courses: the tutor's own checks, the learner's Run, and commands with internet. */
export function CommandsPage({ profile }: { profile: number }) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<Entry[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Entry[]>(`/api/commands?profile=${profile}`).then(setEntries, (e: Error) => setError(e.message))
  }, [profile])

  if (!entries) return <main className={MAIN}>{error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div>}</main>

  function outcome(e: Entry): string {
    if (e.consent === 'refused') return t('commands.refused')
    if (e.exit_code === null) return t('commands.stopped')
    return t('commands.exit', { code: e.exit_code })
  }

  return (
    <main className={MAIN}>
      <h1 className="m-0 max-w-none font-heading text-2xl font-semibold">{t('commands.heading')}</h1>
      <div className="text-muted-foreground">{t('commands.intro')}</div>
      {entries.length === 0 && <div className="text-muted-foreground">{t('commands.empty')}</div>}
      {entries.map((e) => (
        <section key={e.id} className="flex flex-col gap-3 border-t pt-6">
          <div className={LABEL}>
            {moment(e.started)}, <span dir="auto">{e.topic}</span>, <span dir="auto">{e.lesson}</span>, {t(`commands.${e.origin}`)}
            {e.consent === 'allowed' && <Badge className="ms-2 h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t('commands.allowed')}</Badge>}
            {e.consent === 'refused' && <Badge className="ms-2 h-auto rounded-sm bg-warm-tint px-2 py-0.5 text-sm text-warm">{t('commands.refused')}</Badge>}
          </div>
          <pre dir="ltr" className={PRE}>{e.command}</pre>
          <div className="text-sm text-muted-foreground">
            {outcome(e)}
            {e.seconds !== null && `, ${t('commands.seconds', { n: number(e.seconds) })}`}
          </div>
          {e.output && (
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground">{t('commands.output')}</summary>
              <pre dir="ltr" className={`${PRE} max-h-60 overflow-auto`}>{e.output}</pre>
            </details>
          )}
        </section>
      ))}
    </main>
  )
}
