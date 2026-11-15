import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Profile } from './profiles'

const DEFAULT_TIME = '19:00'
const supported = typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

function zone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** The daily review reminder: on for the profile and pushed to this device, at a local time. */
export function Reminder(props: { profile: Profile; onChanged: () => Promise<unknown> }) {
  const { profile } = props
  const { t } = useTranslation()
  // undefined while this device's subscription is being looked up
  const [device, setDevice] = useState<PushSubscription | null | undefined>(supported ? undefined : null)
  // the profile the server sends this device's reminders for; one device follows one profile
  const [linked, setLinked] = useState<number | null>(null)
  const [time, setTime] = useState(profile.remind_at ?? DEFAULT_TIME)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!supported) return
    navigator.serviceWorker
      .getRegistration()
      .then((r) => r?.pushManager.getSubscription() ?? null, () => null)
      .then(async (subscription) => {
        if (subscription) setLinked((await api<{ profile: number | null }>('/api/push/device', { endpoint: subscription.endpoint })).profile)
        setDevice(subscription)
      })
      .catch(() => setDevice(null))
  }, [])

  const on = profile.remind_at !== null && !!device && linked === profile.id

  function run(action: () => Promise<unknown>) {
    setError('')
    setStatus('')
    action().catch((err: Error) => setError(err.message))
  }

  const schedule = (at: string | null) => api(`/api/profiles/${profile.id}/remind`, { at, tz: zone() }).then(props.onChanged)

  async function turnOn() {
    if ((await Notification.requestPermission()) !== 'granted') throw new Error(t('remind.blocked'))
    const registration = await navigator.serviceWorker.getRegistration()
    if (!registration) throw new Error(t('remind.noWorker'))
    const { key } = await api<{ key: string }>('/api/push/key')
    const subscription = (await registration.pushManager.getSubscription()) ?? (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }))
    await api(`/api/profiles/${profile.id}/push`, subscription.toJSON())
    await schedule(time)
    setDevice(subscription)
    setLinked(profile.id)
  }

  async function turnOff() {
    await schedule(null)
    if (device) {
      await api('/api/push/forget', { endpoint: device.endpoint })
      await device.unsubscribe()
    }
    setDevice(null)
  }

  async function test() {
    const { sent } = await api<{ sent: number }>(`/api/profiles/${profile.id}/remind/test`, {})
    setStatus(sent ? t('remind.sent') : t('remind.none'))
  }

  return (
    <section className="block stack">
      <div className="label">{t('remind.heading')}</div>
      {!supported ? (
        <div className="small">{t('remind.unsupported')}</div>
      ) : (
        <>
          <label className="check">
            <input type="checkbox" checked={on} disabled={device === undefined} onChange={(e) => run(e.target.checked ? turnOn : turnOff)} />
            {t('remind.toggle')}
          </label>
          <div className="row">
            <label htmlFor="remind-at">{t('remind.at')}</label>
            <input
              id="remind-at"
              className="field"
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              onBlur={() => on && time && time !== profile.remind_at && run(() => schedule(time))}
            />
            {on && (
              <button type="button" className="btn" onClick={() => run(test)}>
                {t('remind.test')}
              </button>
            )}
          </div>
          <div className="small">{t('remind.help')}</div>
          {status && <div className="small">{status}</div>}
        </>
      )}
      {error && <div className="error">{error}</div>}
    </section>
  )
}
