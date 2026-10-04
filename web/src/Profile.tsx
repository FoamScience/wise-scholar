import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
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
  return (
    <main className="home">
      <h1>Who is learning?</h1>
      <div className="muted">
        A profile keeps one person's courses, reviews and what the tutor knows about them. No password; anyone using this
        browser can switch profiles.
      </div>
      <NameForm
        id="first-profile"
        label="Your name"
        button="Start"
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
        <div className="label">What the tutor knows about you</div>
        {facts.length === 0 && <div className="muted">Nothing yet. The tutor records what you tell it in interviews.</div>}
        {facts.map((f) => (
          <div key={f.id} className="fact">
            <span>{f.text}</span>
            <button type="button" className="link" onClick={() => forget(f)}>
              Forget
            </button>
          </div>
        ))}
        <div className="small">These facts are used in every course of this profile. Facts about one course stay with that course.</div>
      </section>

      <section className="block stack">
        <div className="label">Profile name</div>
        <NameForm
          key={current.id}
          id="rename"
          label="Name"
          button="Rename"
          initial={current.name}
          onSubmit={(name) => api(`/api/profiles/${current.id}`, { name }).then(props.onChanged)}
        />
      </section>

      <section className="block stack">
        <div className="label">Profiles on this computer</div>
        {props.profiles.map((p) => (
          <div key={p.id} className="fact">
            <span>
              <strong>{p.name}</strong> · {p.courses} {p.courses === 1 ? 'course' : 'courses'}
            </span>
            {p.id === current.id ? (
              <span className="chip">Current</span>
            ) : (
              <button type="button" className="btn" onClick={() => props.onSelect(p.id)}>
                Switch
              </button>
            )}
          </div>
        ))}
        <NameForm
          id="new-profile"
          label="Add a profile"
          button="Add"
          onSubmit={(name) =>
            api<Profile>('/api/profiles', { name, locale: props.locale }).then((created) => props.onChanged().then(() => props.onSelect(created.id)))
          }
        />
        <div className="small">No password. Anyone using this browser can switch profiles.</div>
      </section>
    </main>
  )
}
