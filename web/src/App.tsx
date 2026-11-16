import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DirectionProvider } from '@base-ui/react/direction-provider'
import { cn } from 'cn'
import { buttonVariants } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { TooltipProvider } from '@/components/ui/tooltip'
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
import type { Profile } from './profiles'
import { LOCALES, browserLocale, rememberLocale } from './locale'
import type { Locale } from './locale'
import { Home } from './Home'
import { ThemeToggle } from './ThemeToggle'
import { Workspace } from './Workspace'
import { courseRoute, profileRoute } from './route'
import { searchHref } from './course'

const NAV_LINK =
  'inline-flex min-h-11 shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-3 text-sm font-medium text-ink-2 no-underline transition-colors hover:bg-muted hover:text-foreground max-[30rem]:min-w-11 max-[30rem]:justify-center max-[30rem]:p-0'

function useHash(): string {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const onChange = () => setHash(location.hash)
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

type Meta = { agent: string; speech: boolean; pdf: boolean; commands: boolean; crafted: boolean }

function useMeta(): Meta {
  const [meta, setMeta] = useState<Meta>({ agent: '', speech: false, pdf: false, commands: true, crafted: false })
  useEffect(() => {
    api<Meta>('/api/meta').then(setMeta, () => {})
  }, [])
  return meta
}

/** The language shown: the profile's own, or the browser's until there is one. */
function useLocale(current: Profile | null, reload: () => Promise<unknown>) {
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

  return { locale, localeError, switchLocale }
}

/** Pages of one course or lesson: the workspace, its search, recap, book, publishing and handouts. */
function coursePage(hash: string, current: Profile, meta: Meta) {
  const route = courseRoute(hash)
  switch (route?.page) {
    case 'workspace':
      return (
        <Workspace
          key={route.courseId}
          profile={current.id}
          courseId={route.courseId}
          speech={meta.speech}
          commands={meta.commands}
          crafted={meta.crafted}
          sketched={current.sketch}
          concept={route.concept}
          start={route.start}
          found={route.found}
        />
      )
    case 'search':
      return <SearchPage key={hash} courseId={route.courseId} query={route.query} kind={route.kind} />
    case 'recap':
      return <Recap key={hash} courseId={route.courseId} profile={current.id} preview={route.preview} />
    case 'book':
      return <Book key={route.courseId} courseId={route.courseId} learner={current.name} pdf={meta.pdf} sketched={current.sketch} />
    case 'handout':
      return <Handout key={hash} lessonId={route.lessonId} version={route.version} pdf={meta.pdf} />
    case 'publish':
      return <PublishPage key={route.courseId} courseId={route.courseId} />
  }
  return null
}

const PROFILE_PAGES = {
  errors: ErrorsPage,
  sitting: SittingPage,
  commands: CommandsPage,
  usage: UsagePage,
}

/** Pages across the profile's courses: review, errors, the graph, sittings, exploring, commands, usage, settings. */
function profilePage(hash: string, current: Profile) {
  const route = profileRoute(hash)
  if (!route) return null
  if (route.page === 'review') return <Review profile={current.id} then={route.then} />
  if (route.page === 'graph') return <GraphPage key={hash} profile={current.id} course={route.course} />
  if (route.page === 'explore') return current.mode !== 'teacher' ? <ExplorePage key={current.id} profile={current.id} /> : null
  if (route.page === 'settings') return <SettingsPage />
  const Page = PROFILE_PAGES[route.page]
  return <Page profile={current.id} />
}

export default function App() {
  const hash = useHash()
  const { t } = useTranslation()
  const online = useOnline()
  const meta = useMeta()
  const { profiles, current, select, reload } = useProfiles()
  const { locale, localeError, switchLocale } = useLocale(current, reload)

  function page() {
    const hand = hash.match(/^#\/hand\/([\w-]+)$/)
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
    if (hash === '#/profile')
      return <ProfilePage profiles={profiles} current={current} locale={locale} onSelect={select} onChanged={reload} />
    return coursePage(hash, current, meta) ?? profilePage(hash, current) ?? <Home key={current.id} profile={current.id} teacher={current.mode === 'teacher'} />
  }

  // the course a page belongs to, for the search box in the bar; the search page has its own
  const shown = courseRoute(hash)
  const searchCourse = shown && 'courseId' in shown && shown.page !== 'search' ? shown.courseId : null

  return (
    <DirectionProvider direction={i18n.dir(locale)}>
      <TooltipProvider>
        <div className="flex h-dvh flex-col print:block print:h-auto">
          <header className="flex h-14 shrink-0 print:hidden items-center gap-2 border-b bg-card px-4 max-[30rem]:gap-1 max-[30rem]:px-2">
            <a className="me-2 flex h-11 shrink-0 items-center no-underline max-[30rem]:me-0" href="#/" title="wise-scholar">
              <Logo />
            </a>
            {current && (
              <nav className="flex shrink-0 items-center gap-1">
                <a className={NAV_LINK} href="#/graph" title={t('graph.link')} aria-label={t('graph.link')}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                    <circle cx="6" cy="6" r="2.5" />
                    <circle cx="18" cy="8" r="2.5" />
                    <circle cx="9" cy="18" r="2.5" />
                    <path d="M8.4 6.6 15.6 7.4M7 8.4 8.4 15.6M16.5 10 10.8 16.2" />
                  </svg>
                  <span className="max-[30rem]:hidden">{t('graph.link')}</span>
                </a>
                {current.mode !== 'teacher' && (
                  <a className={NAV_LINK} href="#/explore" title={t('explore.link')} aria-label={t('explore.link')}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="12" cy="12" r="9" />
                      <path d="M15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5Z" />
                    </svg>
                    <span className="max-[30rem]:hidden">{t('explore.link')}</span>
                  </a>
                )}
              </nav>
            )}
            {searchCourse !== null && (
              <form
                role="search"
                className="min-w-16 flex-[0_1_14rem]"
                onSubmit={(e) => {
                  e.preventDefault()
                  const query = String(new FormData(e.currentTarget).get('q') ?? '')
                  if (query.trim()) location.hash = searchHref(searchCourse, query)
                }}
              >
                <Input type="search" name="q" dir="auto" className="h-10 w-full" aria-label={t('search.label')} placeholder={t('search.placeholder')} />
              </form>
            )}
            <span className="grow" />
            <span className="whitespace-nowrap text-sm text-muted-foreground max-md:hidden">{t('header.agent', { agent: meta.agent })}</span>
            {localeError && <span className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{localeError}</span>}
            <ThemeToggle />
            <Select value={locale} items={LOCALES} onValueChange={(code) => switchLocale(code as Locale)}>
              <SelectTrigger className="h-10 shrink-0 font-medium hover:border-foreground max-[30rem]:px-2" aria-label={t('header.language')}>
                <SelectValue>
                  {(code: Locale) => (
                    <>
                      <span className="max-sm:hidden">{LOCALES[code]}</span>
                      <span className="sm:hidden">{code.toUpperCase()}</span>
                    </>
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent alignItemWithTrigger={false} align="end">
                {Object.entries(LOCALES).map(([code, name]) => (
                  <SelectItem key={code} value={code} lang={code}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {current && (
              <a
                className={cn(buttonVariants({ variant: 'outline' }), 'h-10 shrink-0 max-[30rem]:block max-[30rem]:max-w-28 max-[30rem]:truncate max-[30rem]:px-2 max-[30rem]:leading-[38px]')}
                href="#/profile"
              >
                {current.name}
              </a>
            )}
          </header>
          {!online && (
            <div className="shrink-0 border-b bg-warm-tint px-4 py-2 text-sm" role="status">
              {t('offline.banner')}
            </div>
          )}
          {page()}
        </div>
      </TooltipProvider>
    </DirectionProvider>
  )
}
