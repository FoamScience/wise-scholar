import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { lookup } from './i18n'

const MAIN = 'mx-auto flex w-full max-w-160 flex-col gap-10 px-6 pt-10 pb-16'
const BLOCK = 'flex flex-col gap-3 border-t pt-6'
const ROW = 'flex flex-wrap items-center gap-2'
const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const ERROR = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const FIELD = 'min-w-0 flex-[1_1_16rem]'
const CHIP = 'h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground'
const WARN = 'h-auto rounded-sm bg-warm-tint px-2 py-0.5 text-sm text-warm'
const WRAP = 'min-w-0 max-w-full shrink justify-start text-start whitespace-normal wrap-anywhere'

type Setting = {
  name: string
  kind: 'int' | 'bool' | 'text' | 'agent'
  minimum: number
  default: string
  value: string | null
  saved: string | null
  source: 'default' | 'file' | 'shell'
  changeable: boolean
  editable: boolean
  pending: boolean
}
type Settings = { settings: Setting[]; editable: boolean; restart: boolean }

const RESTART_POLL_MS = 1000

/** The server's settings: the safe ones edited here and saved to .env, the rest shown as they run. */
/** Restarting the server for saved settings to take hold; the page is back once the server answers again. */
function useRestart(setState: (state: Settings) => void, setError: (message: string) => void) {
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    if (!restarting) return
    // The server is gone for a moment; the page is back once it answers again.
    const timer = setInterval(
      () =>
        api<Settings>('/api/settings').then((s) => {
          setState(s)
          setRestarting(false)
        }, () => {}),
      RESTART_POLL_MS,
    )
    return () => clearInterval(timer)
  }, [restarting, setState])

  function restart() {
    setError('')
    api('/api/settings/restart', {}).then(
      () => setRestarting(true),
      (e: Error) => setError(e.message),
    )
  }

  return { restarting, restart }
}

function RestartNotice(props: { state: Settings; restarting: boolean; changed: boolean; onRestart: () => void }) {
  const { t } = useTranslation()
  return (
    <div className={BLOCK}>
      <div>{t('settings.pending')}</div>
      {props.state.restart ? (
        <div className={ROW}>
          <Button type="button" disabled={!props.state.editable || props.restarting || props.changed} onClick={props.onRestart}>
            {props.restarting ? t('settings.restarting') : t('settings.restart')}
          </Button>
          <span className={SMALL}>{t('settings.restartNote')}</span>
        </div>
      ) : (
        <div className={SMALL}>{t('settings.restartByHand')}</div>
      )}
    </div>
  )
}

export function SettingsPage() {
  const { t } = useTranslation()
  const [state, setState] = useState<Settings | null>(null)
  const [draft, setDraft] = useState<Record<string, string | null>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<Settings>('/api/settings').then(setState, (e: Error) => setError(e.message))
  }, [])

  const { restarting, restart } = useRestart(setState, setError)

  if (!state) return <main className={MAIN}>{error && <div className={ERROR}>{error}</div>}</main>

  const changed = Object.keys(draft).length > 0
  const pending = state.settings.some((s) => s.pending)
  const shown = (s: Setting) => (s.name in draft ? draft[s.name] : s.saved)

  function set(s: Setting, value: string | null) {
    const next = { ...draft }
    if (value === (s.saved ?? null)) delete next[s.name]
    else next[s.name] = value
    setDraft(next)
  }

  function save() {
    setBusy(true)
    setError('')
    api<Settings>('/api/settings', { values: draft }).then(
      (s) => {
        setState(s)
        setDraft({})
        setBusy(false)
      },
      (e: Error) => {
        setError(e.message)
        setBusy(false)
      },
    )
  }

  function control(s: Setting) {
    const value = shown(s)
    const disabled = !state?.editable || !s.editable || busy || restarting
    if (s.kind === 'bool')
      return (
        <Select
          disabled={disabled}
          value={value ?? s.default}
          items={{ '1': t('settings.on'), '0': t('settings.off') }}
          onValueChange={(next) => set(s, next === s.default ? null : next)}
        >
          <SelectTrigger className={`${FIELD} w-auto`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            <SelectItem value="1">{t('settings.on')}</SelectItem>
            <SelectItem value="0">{t('settings.off')}</SelectItem>
          </SelectContent>
        </Select>
      )
    return (
      <Input
        className={FIELD}
        dir="ltr"
        disabled={disabled}
        inputMode={s.kind === 'int' ? 'numeric' : undefined}
        placeholder={s.default || t('settings.unset')}
        value={value ?? ''}
        onChange={(e) => set(s, e.target.value.trim() === '' ? null : e.target.value.trim())}
      />
    )
  }

  function display(s: Setting, value: string | null) {
    const shown = value ?? s.default
    if (s.kind === 'bool') return shown === '0' ? t('settings.off') : t('settings.on')
    return shown || t('settings.unset')
  }

  function row(s: Setting) {
    return (
      <section key={s.name} className={BLOCK}>
        <div className={LABEL}>
          {lookup(`settings.items.${s.name}.label`, s.name)} <code dir="ltr" className="font-mono text-[0.93em] wrap-anywhere">{s.name}</code>
        </div>
        <div className={SMALL}>{lookup(`settings.items.${s.name}.help`, '')}</div>
        <div className={ROW}>
          {s.editable ? control(s) : <code dir="ltr" className="font-mono text-[0.93em] wrap-anywhere">{display(s, s.value)}</code>}
          <Badge className={s.source === 'shell' ? WARN : CHIP}>{t(`settings.source.${s.source}`)}</Badge>
          {s.pending && <Badge className={`${WARN} ${WRAP}`}>{t('settings.afterRestart', { value: display(s, s.saved) })}</Badge>}
        </div>
      </section>
    )
  }

  return (
    <main className={MAIN}>
      <h1 className="m-0 max-w-none font-heading text-2xl font-semibold">{t('settings.heading')}</h1>
      <div className="text-muted-foreground">{t('settings.intro')}</div>
      {!state.editable && <div className={ERROR}>{t('settings.remote')}</div>}
      {error && <div className={ERROR}>{error}</div>}
      {pending && <RestartNotice state={state} restarting={restarting} changed={changed} onRestart={restart} />}
      <h2 className="m-0 font-heading text-lg font-semibold">{t('settings.editableHeading')}</h2>
      {state.settings.filter((s) => s.changeable).map(row)}
      {state.editable && (
        <div className={ROW}>
          <Button type="button" disabled={!changed || busy} onClick={save}>
            {t('settings.save')}
          </Button>
          <Button type="button" variant="ghost" className="text-ink-2" disabled={!changed || busy} onClick={() => setDraft({})}>
            {t('settings.discard')}
          </Button>
        </div>
      )}
      <h2 className="m-0 font-heading text-lg font-semibold">{t('settings.lockedHeading')}</h2>
      <div className="text-muted-foreground">{t('settings.lockedIntro')}</div>
      {state.settings.filter((s) => !s.changeable).map(row)}
    </main>
  )
}
