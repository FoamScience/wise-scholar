import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import i18n from './i18n'
import Logo from './Logo'
import { Review } from './Quiz'
import { useOnline } from './offline'
import { ErrorsPage } from './Errors'
import { CommandsPage } from './Commands'
import { UsagePage } from './Usage'
import { PublishPage } from './Publish'
import { GraphPage } from './Graph'
import { SittingPage } from './Sitting'
import { ExplorePage } from './Explore'
import { SettingsPage } from './Settings'
import { SearchPage } from './Search'
import { HandPage } from './Handwork'
import { Book } from './Book'
import { Recap } from './Recap'
import { Handout } from './Handout'
import { FirstProfile, ProfilePage } from './Profile'
import { useProfiles } from './profiles'
import { LOCALES, browserLocale, rememberLocale } from './locale'
import type { Locale } from './locale'
import { Home } from './Home'
import { ThemeToggle } from './ThemeToggle'
import { Workspace } from './Workspace'

function useHash(): string {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const onChange = () => setHash(location.hash)
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

export default function App() {
  const hash = useHash()
  const { t } = useTranslation()
  const online = useOnline()
  const [agent, setAgent] = useState('')
  const [speech, setSpeech] = useState(false)
  const [pdf, setPdf] = useState(false)
  const [commands, setCommands] = useState(true)
  const [crafted, setCrafted] = useState(false)
  const { profiles, current, select, reload } = useProfiles()
  const [chosen, setChosen] = useState<Locale>(browserLocale)
  const [localeError, setLocaleError] = useState('')
  const locale = current?.locale ?? chosen
  useEffect(() => {
    i18n.changeLanguage(locale)
  }, [locale])

  function switchLocale(next: Locale) {
    setLocaleError('')
    const saved = current ? api(`/api/profiles/${current.id}/locale`, { locale: next }).then(reload) : Promise.resolve()
    saved.then(
      () => {
        rememberLocale(next)
        setChosen(next)
      },
      (err: Error) => setLocaleError(err.message),
    )
  }
  useEffect(() => {
    api<{ agent: string; speech: boolean; pdf: boolean; commands: boolean; crafted: boolean }>('/api/meta').then(
      (m) => {
        setAgent(m.agent)
        setSpeech(m.speech)
        setPdf(m.pdf)
        setCommands(m.commands)
        setCrafted(m.crafted)
      },
      () => {},
    )
  }, [])
  const match = hash.match(/^#\/course\/(\d+)(?:\?concept=(\d+)|\?start=(episode|writing)|\?lesson=(\d+)&(card|chat)=(\d+))?$/)
  const review = hash.match(/^#\/review(?:\?then=(.*))?$/)
  const book = hash.match(/^#\/course\/(\d+)\/book$/)
  const recapped = hash.match(/^#\/course\/(\d+)\/recap(\?preview)?$/)
  const publishing = hash.match(/^#\/course\/(\d+)\/publish$/)
  const found = hash.match(/^#\/course\/(\d+)\/search\?(.*)$/)
  const hand = hash.match(/^#\/hand\/([\w-]+)$/)
  const graph = hash.match(/^#\/graph(?:\?course=(\d+))?$/)
  const handout = hash.match(/^#\/lesson\/(\d+)\/handout\/(student|teacher)$/)

  function page() {
    if (hand) return <HandPage key={hand[1]} token={hand[1]} />
    if (!profiles) return null
    if (!current)
      return (
        <FirstProfile
          locale={locale}
          onCreated={(created) => {
            reload()
            select(created.id)
          }}
        />
      )
    if (match)
      return (
        <Workspace
          key={match[1]}
          profile={current.id}
          courseId={Number(match[1])}
          speech={speech}
          commands={commands}
          crafted={crafted}
          sketched={current.sketch}
          concept={match[2] ? Number(match[2]) : null}
          start={(match[3] as 'episode' | 'writing' | undefined) ?? null}
          found={match[4] ? { lesson: Number(match[4]), at: `${match[5] === 'chat' ? 'msg' : 'block'}-${match[6]}` } : null}
        />
      )
    if (found) {
      const params = new URLSearchParams(found[2])
      return <SearchPage key={hash} courseId={Number(found[1])} query={params.get('q') ?? ''} kind={params.get('kind') ?? ''} />
    }
    if (recapped) return <Recap key={hash} courseId={Number(recapped[1])} profile={current.id} preview={Boolean(recapped[2])} />
    if (book) return <Book key={book[1]} courseId={Number(book[1])} learner={current.name} pdf={pdf} sketched={current.sketch} />
    if (handout) return <Handout key={handout[0]} lessonId={Number(handout[1])} version={handout[2] as 'student' | 'teacher'} pdf={pdf} />
    if (review) return <Review profile={current.id} then={review[1] ? decodeURIComponent(review[1]) : null} />
    if (hash === '#/errors') return <ErrorsPage profile={current.id} />
    if (graph) return <GraphPage key={hash} profile={current.id} course={graph[1] ? Number(graph[1]) : null} />
    if (hash === '#/sitting') return <SittingPage profile={current.id} />
    if (hash === '#/explore' && current.mode !== 'teacher') return <ExplorePage key={current.id} profile={current.id} />
    if (hash === '#/commands') return <CommandsPage profile={current.id} />
    if (hash === '#/usage') return <UsagePage profile={current.id} />
    if (hash === '#/settings') return <SettingsPage />
    if (publishing) return <PublishPage key={publishing[1]} courseId={Number(publishing[1])} />
    if (hash === '#/profile')
      return <ProfilePage profiles={profiles} current={current} locale={locale} onSelect={select} onChanged={reload} />
    return <Home key={current.id} profile={current.id} teacher={current.mode === 'teacher'} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="wordmark" href="#/" title="wise-scholar">
          <Logo />
        </a>
        {current && (
          <nav className="topnav">
            <a href="#/graph" title={t('graph.link')} aria-label={t('graph.link')}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <circle cx="6" cy="6" r="2.5" />
                <circle cx="18" cy="8" r="2.5" />
                <circle cx="9" cy="18" r="2.5" />
                <path d="M8.4 6.6 15.6 7.4M7 8.4 8.4 15.6M16.5 10 10.8 16.2" />
              </svg>
              <span className="nav-label">{t('graph.link')}</span>
            </a>
            {current.mode !== 'teacher' && (
              <a href="#/explore" title={t('explore.link')} aria-label={t('explore.link')}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5Z" />
                </svg>
                <span className="nav-label">{t('explore.link')}</span>
              </a>
            )}
          </nav>
        )}
        <span className="grow" />
        <span className="status">{t('header.agent', { agent })}</span>
        {localeError && <span className="error">{localeError}</span>}
        <ThemeToggle />
        <span className="locale-pick">
          <span className="btn" aria-hidden="true">
            {locale.toUpperCase()}
          </span>
          <select className="btn locale" aria-label={t('header.language')} value={locale} onChange={(e) => switchLocale(e.target.value as Locale)}>
            {Object.entries(LOCALES).map(([code, name]) => (
              <option key={code} value={code} lang={code}>
                {name}
              </option>
            ))}
          </select>
        </span>
        {current && (
          <a className="btn as-link" href="#/profile">
            {current.name}
          </a>
        )}
      </header>
      {!online && (
        <div className="offline-banner" role="status">
          {t('offline.banner')}
        </div>
      )}
      {page()}
    </div>
  )
}
