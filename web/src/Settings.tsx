import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { lookup } from './i18n'

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
export function SettingsPage() {
  const { t } = useTranslation()
  const [state, setState] = useState<Settings | null>(null)
  const [draft, setDraft] = useState<Record<string, string | null>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    api<Settings>('/api/settings').then(setState, (e: Error) => setError(e.message))
  }, [])

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
  }, [restarting])

  if (!state) return <main className="home">{error && <div className="error">{error}</div>}</main>

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

  function restart() {
    setError('')
    api('/api/settings/restart', {}).then(
      () => setRestarting(true),
      (e: Error) => setError(e.message),
    )
  }

  function control(s: Setting) {
    const value = shown(s)
    const disabled = !state?.editable || !s.editable || busy || restarting
    if (s.kind === 'bool')
      return (
        <select className="field" disabled={disabled} value={value ?? s.default} onChange={(e) => set(s, e.target.value === s.default ? null : e.target.value)}>
          <option value="1">{t('settings.on')}</option>
          <option value="0">{t('settings.off')}</option>
        </select>
      )
    return (
      <input
        className="field"
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
      <section key={s.name} className="block stack setting">
        <div className="label">
          {lookup(`settings.items.${s.name}.label`, s.name)} <code dir="ltr">{s.name}</code>
        </div>
        <div className="small">{lookup(`settings.items.${s.name}.help`, '')}</div>
        <div className="row">
          {s.editable ? control(s) : <code dir="ltr">{display(s, s.value)}</code>}
          <span className={`chip ${s.source === 'shell' ? 'warn' : ''}`}>{t(`settings.source.${s.source}`)}</span>
          {s.pending && <span className="chip warn">{t('settings.afterRestart', { value: display(s, s.saved) })}</span>}
        </div>
      </section>
    )
  }

  return (
    <main className="home settings-page">
      <h1>{t('settings.heading')}</h1>
      <div className="muted">{t('settings.intro')}</div>
      {!state.editable && <div className="error">{t('settings.remote')}</div>}
      {error && <div className="error">{error}</div>}
      {pending && (
        <div className="block stack">
          <div>{t('settings.pending')}</div>
          {state.restart ? (
            <div className="row">
              <button type="button" className="btn primary" disabled={!state.editable || restarting || changed} onClick={restart}>
                {restarting ? t('settings.restarting') : t('settings.restart')}
              </button>
              <span className="small">{t('settings.restartNote')}</span>
            </div>
          ) : (
            <div className="small">{t('settings.restartByHand')}</div>
          )}
        </div>
      )}
      <h2>{t('settings.editableHeading')}</h2>
      {state.settings.filter((s) => s.changeable).map(row)}
      {state.editable && (
        <div className="row">
          <button type="button" className="btn primary" disabled={!changed || busy} onClick={save}>
            {t('settings.save')}
          </button>
          <button type="button" className="link" disabled={!changed || busy} onClick={() => setDraft({})}>
            {t('settings.discard')}
          </button>
        </div>
      )}
      <h2>{t('settings.lockedHeading')}</h2>
      <div className="muted">{t('settings.lockedIntro')}</div>
      {state.settings.filter((s) => !s.changeable).map(row)}
    </main>
  )
}
