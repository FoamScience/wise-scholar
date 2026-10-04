import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Locale } from './locale'
import type { Profile } from './profiles'

type Fact = { id: number; text: string }

function NameForm(props: { id: string; label: string; button: string; initial?: string; onSubmit: (name: string) => Promise<unknown> }) {
  const [name, setName] = useState(props.initial ?? '')
  const [error, setError] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    props.onSubmit(name.trim()).then(
      () => props.initial === undefined && setName(''),
      (err: Error) => setError(err.message),
    )
  }

  return (
    <form className="name-form" onSubmit={submit}>
      <label htmlFor={props.id}>{props.label}</label>
      <div className="row">
        <input id={props.id} className="field" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <button className="btn primary" disabled={!name.trim() || name.trim() === props.initial}>
          {props.button}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  )
}

export function FirstProfile(props: { locale: Locale; onCreated: (profile: Profile) => void }) {
  const { t } = useTranslation()
  return (
    <main className="home">
      <h1>{t('profile.who')}</h1>
      <div className="muted">{t('profile.intro')}</div>
      <NameForm
        id="first-profile"
        label={t('profile.yourName')}
        button={t('common.start')}
        onSubmit={(name) => api<Profile>('/api/profiles', { name, locale: props.locale }).then(props.onCreated)}
      />
    </main>
  )
}

export function ProfilePage(props: {
  profiles: Profile[]
  current: Profile
  locale: Locale
  onSelect: (id: number) => void
  onChanged: () => Promise<unknown>
}) {
  const { current } = props
  const { t } = useTranslation()
  const [facts, setFacts] = useState<Fact[]>([])

  useEffect(() => {
    api<{ facts: Fact[] }>(`/api/profiles/${current.id}`).then((p) => setFacts(p.facts), () => {})
  }, [current.id])

  function forget(fact: Fact) {
    api(`/api/facts/${fact.id}/forget`, {}).then(() => setFacts((all) => all.filter((f) => f.id !== fact.id)), () => {})
  }

  return (
    <main className="home">
      <h1>{current.name}</h1>

      <section className="block stack">
        <div className="label">{t('profile.knows')}</div>
        {facts.length === 0 && <div className="muted">{t('profile.nothing')}</div>}
        {facts.map((f) => (
          <div key={f.id} className="fact">
            <span>{f.text}</span>
            <button type="button" className="link" onClick={() => forget(f)}>
              {t('profile.forget')}
            </button>
          </div>
        ))}
        <div className="small">{t('profile.factsScope')}</div>
      </section>

      <section className="block stack">
        <div className="label">{t('profile.nameHeading')}</div>
        <NameForm
          key={current.id}
          id="rename"
          label={t('profile.name')}
          button={t('profile.rename')}
          initial={current.name}
          onSubmit={(name) => api(`/api/profiles/${current.id}`, { name }).then(props.onChanged)}
        />
      </section>

      <section className="block stack">
        <div className="label">{t('profile.onComputer')}</div>
        {props.profiles.map((p) => (
          <div key={p.id} className="fact">
            <span>
              <strong>{p.name}</strong> · {t('profile.courses', { count: p.courses })}
            </span>
            {p.id === current.id ? (
              <span className="chip">{t('profile.current')}</span>
            ) : (
              <button type="button" className="btn" onClick={() => props.onSelect(p.id)}>
                {t('profile.switch')}
              </button>
            )}
          </div>
        ))}
        <NameForm
          id="new-profile"
          label={t('profile.add')}
          button={t('profile.addButton')}
          onSubmit={(name) =>
            api<Profile>('/api/profiles', { name, locale: props.locale }).then((created) => props.onChanged().then(() => props.onSelect(created.id)))
          }
        />
        <div className="small">{t('profile.noPassword')}</div>
      </section>
    </main>
  )
}
