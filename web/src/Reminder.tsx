import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
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
    <section className="flex flex-col gap-3 border-t pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">{t('remind.heading')}</div>
      {!supported ? (
        <div className="text-sm text-muted-foreground">{t('remind.unsupported')}</div>
      ) : (
        <>
          <label className="flex items-center gap-2">
            <Checkbox checked={on} disabled={device === undefined} onCheckedChange={(checked) => run(checked ? turnOn : turnOff)} />
            {t('remind.toggle')}
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="remind-at">{t('remind.at')}</label>
            <Input
              id="remind-at"
              className="w-auto"
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              onBlur={() => on && time && time !== profile.remind_at && run(() => schedule(time))}
            />
            {on && (
              <Button type="button" variant="outline" onClick={() => run(test)}>
                {t('remind.test')}
              </Button>
            )}
          </div>
          <div className="text-sm text-muted-foreground">{t('remind.help')}</div>
          {status && <div className="text-sm text-muted-foreground">{status}</div>}
        </>
      )}
      {error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div>}
    </section>
  )
}
