import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Locale } from './locale'
import type { Profile } from './profiles'
import { Reminder } from './Reminder'
import { CastFeed } from './CastFeed'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from 'cn'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'

const MAIN = 'mx-auto flex w-full max-w-160 flex-col gap-10 px-6 pt-10 pb-16'
const BLOCK = 'flex flex-col gap-3 border-t pt-6'
const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const ERROR = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const FACT = 'flex min-h-11 items-center justify-between gap-3'
const LINK = cn(buttonVariants({ variant: 'outline' }), 'w-fit')

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
    <form className="flex flex-col gap-2" onSubmit={submit}>
      <label htmlFor={props.id} className={SMALL}>{props.label}</label>
      <div className="flex gap-3">
        <Input id={props.id} className="flex-1 border-rule-strong" dir="auto" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={!name.trim() || name.trim() === props.initial}>
          {props.button}
        </Button>
      </div>
      {error && <div className={ERROR}>{error}</div>}
    </form>
  )
}

export function FirstProfile(props: { locale: Locale; onCreated: (profile: Profile) => void }) {
  const { t } = useTranslation()
  return (
    <main className={MAIN}>
      <h1 className="m-0 max-w-none font-heading text-2xl font-semibold">{t('profile.who')}</h1>
      <div className="text-muted-foreground">{t('profile.intro')}</div>
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
  const [error, setError] = useState('')

  useEffect(() => {
    api<{ facts: Fact[] }>(`/api/profiles/${current.id}`).then((p) => setFacts(p.facts), () => {})
  }, [current.id])

  function forget(fact: Fact) {
    api(`/api/facts/${fact.id}/forget`, {}).then(() => setFacts((all) => all.filter((f) => f.id !== fact.id)), () => {})
  }

  function setMode(mode: Profile['mode']) {
    if (mode !== current.mode) api(`/api/profiles/${current.id}/mode`, { mode }).then(props.onChanged, () => {})
  }

  return (
    <main className={MAIN}>
      <h1 className="m-0 max-w-none font-heading text-2xl font-semibold">{current.name}</h1>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.modeHeading')}</div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant={current.mode === 'learner' ? 'default' : 'outline'} onClick={() => setMode('learner')}>
            {t('profile.learner')}
          </Button>
          <Button type="button" variant={current.mode === 'teacher' ? 'default' : 'outline'} onClick={() => setMode('teacher')}>
            {t('profile.teacher')}
          </Button>
        </div>
        <div className={SMALL}>{current.mode === 'teacher' ? t('profile.teacherHelp') : t('profile.learnerHelp')}</div>
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.sketchHeading')}</div>
        <label className="flex items-center gap-2">
          <Checkbox
            checked={current.sketch}
            onCheckedChange={(checked) => api(`/api/profiles/${current.id}/sketch`, { sketch: checked }).then(props.onChanged, (err: Error) => setError(err.message))}
          />
          {t('profile.sketch')}
        </label>
        <div className={SMALL}>{t('profile.sketchHelp')}</div>
        {error && <div className={ERROR}>{error}</div>}
      </section>

      {current.mode === 'learner' && <Reminder key={`${current.id} ${current.remind_at}`} profile={current} onChanged={props.onChanged} />}

      {current.mode === 'learner' && <CastFeed profile={current.id} />}

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.knows')}</div>
        {facts.length === 0 && <div className="text-muted-foreground">{t('profile.nothing')}</div>}
        {facts.map((f) => (
          <div key={f.id} className={FACT}>
            <span>{f.text}</span>
            <Button type="button" variant="ghost" className="text-ink-2" onClick={() => forget(f)}>
              {t('profile.forget')}
            </Button>
          </div>
        ))}
        <div className={SMALL}>{t('profile.factsScope')}</div>
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.commandsHeading')}</div>
        <div className={SMALL}>{t('profile.commandsScope')}</div>
        <a className={LINK} href="#/commands">
          {t('profile.commands')}
        </a>
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.usageHeading')}</div>
        <div className={SMALL}>{t('profile.usageScope')}</div>
        <a className={LINK} href="#/usage">
          {t('profile.usage')}
        </a>
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.settingsHeading')}</div>
        <div className={SMALL}>{t('profile.settingsScope')}</div>
        <a className={LINK} href="#/settings">
          {t('profile.settings')}
        </a>
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.nameHeading')}</div>
        <NameForm
          key={current.id}
          id="rename"
          label={t('profile.name')}
          button={t('profile.rename')}
          initial={current.name}
          onSubmit={(name) => api(`/api/profiles/${current.id}`, { name }).then(props.onChanged)}
        />
      </section>

      <section className={BLOCK}>
        <div className={LABEL}>{t('profile.onComputer')}</div>
        {props.profiles.map((p) => (
          <div key={p.id} className={FACT}>
            <span>
              <strong>{p.name}</strong>, {t('profile.courses', { count: p.courses })}
            </span>
            {p.id === current.id ? (
              <Badge className="h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground">{t('profile.current')}</Badge>
            ) : (
              <Button type="button" variant="outline" onClick={() => props.onSelect(p.id)}>
                {t('profile.switch')}
              </Button>
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
        <div className={SMALL}>{t('profile.noPassword')}</div>
      </section>
    </main>
  )
}
