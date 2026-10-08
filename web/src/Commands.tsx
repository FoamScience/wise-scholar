import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { moment, number } from './i18n'

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

  if (!entries) return <main className="home">{error && <div className="error">{error}</div>}</main>

  function outcome(e: Entry): string {
    if (e.consent === 'refused') return t('commands.refused')
    if (e.exit_code === null) return t('commands.stopped')
    return t('commands.exit', { code: e.exit_code })
  }

  return (
    <main className="home">
      <h1>{t('commands.heading')}</h1>
      <div className="muted">{t('commands.intro')}</div>
      {entries.length === 0 && <div className="muted">{t('commands.empty')}</div>}
      {entries.map((e) => (
        <section key={e.id} className="block entry">
          <div className="label">
            {moment(e.started)} · <span dir="auto">{e.topic}</span> · <span dir="auto">{e.lesson}</span> · {t(`commands.${e.origin}`)}
            {e.consent === 'allowed' && <span className="chip">{t('commands.allowed')}</span>}
            {e.consent === 'refused' && <span className="chip warn">{t('commands.refused')}</span>}
          </div>
          <pre dir="ltr">{e.command}</pre>
          <div className="small">
            {outcome(e)}
            {e.seconds !== null && ` · ${t('commands.seconds', { n: number(e.seconds) })}`}
          </div>
          {e.output && (
            <details>
              <summary className="small">{t('commands.output')}</summary>
              <pre dir="ltr" className="output">{e.output}</pre>
            </details>
          )}
        </section>
      ))}
    </main>
  )
}
