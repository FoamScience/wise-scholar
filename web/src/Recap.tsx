import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import type { Core } from 'cytoscape'
import { useTranslation } from 'react-i18next'
import { cn } from 'cn'
import { Button, buttonVariants } from '@/components/ui/button'
import { api } from './api'
import { practiceTitle } from './course'
import { followCourse } from './courseEvents'
import { day, number, percent } from './i18n'
import { LOCALES } from './locale'
import type { Locale } from './locale'
import Markdown, { InlineMarkdown } from './Md'
import { PlotBox } from './PlotCard'
import { ContributeSection } from './Contribute'
import { STATE_COLOR, loadCytoscape, token } from './claims'
import type { State } from './claims'
import { useTheme } from './theme'

type Step = {
  concept_id: number
  title: string
  module: string
  kind: string
  finished: string
  week: string
  minutes: number
  estimated: boolean
  checks: { confidence: number; correct: boolean }[]
  claims: number[]
  mistakes: number[]
  milestone: { project: string; deliverable: string } | null
}
type Claim = { id: number; text: string; created: string; state: State; step: number | null }
type Mistake = { id: number; prompt: string; correct: string; created: string; fixed: string | null; put_right: boolean; step: number | null; concept_id: number | null }
// recaps written before the letter was split keep `letter` alone
type Narrative = {
  intro: string
  weeks: Record<string, string>
  letter?: string
  can_do?: string[]
  strengthen?: string[]
  next_step?: string
  locale: Locale
  finished: string
}
type Story = {
  course: { id: number; topic: string; level: string | null; placement: string | null; cover: boolean; cover_alt: string | null }
  started: string | null
  finished: string | null
  modules: string[]
  before: { concept_id: number; title: string; module: string }[]
  steps: Step[]
  weeks: string[]
  claims: Claim[]
  edges: { from_id: number; to_id: number; kind: string }[]
  mistakes: Mistake[]
  answers: { created: string; confidence: number; correct: boolean }[]
  stats: {
    minutes: number
    estimated: boolean
    units_done: number
    units: number
    projects_done: number
    projects: number
    claims_held: number
    claims: number
    mistakes_fixed: number
    mistakes: number
  }
  narrative: Narrative | null
  positions: Record<string, [number, number]> | null
  preview: boolean
  writing: boolean
  failed: boolean
}
type Suggestion = { id: number; title: string; pitch: string; builds_on: string }

// below these the layer says too little to be worth showing
const GRAPH_FROM = 10
const CHART_FROM = 10
const PLAY_MS = 45_000
const COUNT_MS = 900

const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const H2 = 'm-0'
const LEAD = 'm-0 text-[length:var(--text-lead)]'
const LIST = 'm-0 flex list-none flex-col gap-2 p-0'
const PAGE = 'recap mx-auto flex w-full max-w-(--page) flex-col gap-10 px-6 pt-10 pb-24 max-[60rem]:px-4'
const CHIP_EDGE: Record<State, string> = { held: 'border-s-primary', fading: 'border-s-warm-line', shaky: 'border-s-destructive', unseen: 'border-s-off' }
const SUMMARY = 'cursor-pointer list-none [&::-webkit-details-marker]:hidden'
const LENS = 'h-8 flex-1 rounded-sm border-0 bg-transparent px-2 text-sm font-normal text-muted-foreground hover:bg-transparent aria-pressed:bg-card aria-pressed:font-semibold aria-pressed:text-foreground aria-pressed:shadow-[0_0_0_1px_var(--color-border)]'
const STEP = 'recap-step relative scroll-mt-10 border-s-4 border-(--module) py-1 ps-6 before:absolute before:-start-2.5 before:top-[calc(var(--space-sm)+0.25rem)] before:size-4 before:rounded-full before:border-3 before:border-(--module) before:bg-background before:transition-[background] before:duration-(--motion) motion-reduce:before:transition-none max-[60rem]:scroll-mt-32 print:before:bg-(--module)'
const PROMPT = '[&>.prose]:mt-2 [&>summary]:cursor-pointer [&>summary+*]:mt-2'

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches
const isWeak = (c: Claim) => c.state === 'shaky' || c.state === 'fading'

/** Opens a step of the timeline and brings it to the middle of the screen. */
function showStep(n: number) {
  const li = document.querySelector<HTMLElement>(`.recap-step[data-step="${n}"]`)
  if (!li) return
  li.querySelector('details')?.setAttribute('open', '')
  li.scrollIntoView({ block: 'start', behavior: still() ? 'instant' : 'smooth' })
}

/** Counts up to the value once, on the first show; at once when motion is reduced. */
function useCountUp(value: number): number {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (still()) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / COUNT_MS)
      setShown(value * (1 - (1 - p) ** 3))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return still() ? value : shown
}

function Tile({ value, total, label, sub, decimals = 0 }: { value: number; total?: number; label: string; sub?: string; decimals?: number }) {
  const n = useCountUp(value)
  return (
    <div className="flex flex-col gap-0.5 rounded-b-md border-t-2 border-primary bg-card px-4 py-3 text-sm">
      <strong className="font-heading text-2xl leading-[1.1] tabular-nums">
        {number(Number(n.toFixed(decimals)))}
        {total !== undefined && <span className="text-base font-normal text-muted-foreground">/{number(total)}</span>}
      </strong>
      <span>{label}</span>
      {sub && <span className={SMALL}>{sub}</span>}
    </div>
  )
}

/** A module's colour on the ribbon: the course's modules run from the accent to the warm line, in map order. */
function moduleColor(modules: string[], module: string): string {
  const n = modules.length
  const share = n > 1 ? Math.round((100 * modules.indexOf(module)) / (n - 1)) : 0
  return `color-mix(in oklab, var(--amber-line) ${share}%, var(--teal))`
}

function brier(answers: Story['answers']): number {
  return answers.reduce((sum, a) => sum + (a.confidence - (a.correct ? 1 : 0)) ** 2, 0) / answers.length
}

function graphElements(claims: Claim[], edges: Story['edges'], positions: Story['positions']) {
  return [
    ...claims.map((c) => ({
      data: { id: String(c.id), color: token(STATE_COLOR[c.state]) },
      ...(positions ? { position: { x: positions[c.id][0], y: positions[c.id][1] } } : {}),
    })),
    ...edges.map((e) => ({ data: { id: `${e.from_id}-${e.to_id}-${e.kind}`, source: String(e.from_id), target: String(e.to_id), kind: e.kind } })),
  ]
}

function graphStyle() {
  const ink = token('--ink')
  return [
    { selector: 'node', style: { width: 9, height: 9, 'background-color': 'data(color)', 'border-width': 0 } },
    { selector: 'node.fresh', style: { width: 14, height: 14, 'border-width': 2, 'border-color': ink } },
    { selector: 'node:selected', style: { 'border-width': 2, 'border-color': ink } },
    { selector: 'node.away', style: { 'background-color': token('--mastery-off'), opacity: 0.35 } },
    { selector: 'edge.away', style: { opacity: 0.08 } },
    { selector: 'node.dim', style: { opacity: 0.15 } },
    { selector: 'edge.dim', style: { opacity: 0.05 } },
    { selector: 'edge', style: { width: 0.8, 'line-color': token('--line-strong'), opacity: 0.55, 'curve-style': 'straight' } },
    { selector: 'edge[kind = "contrasts"]', style: { 'line-style': 'dotted', 'line-color': token('--danger') } },
  ]
}

/** The claims as dots, laid out once and kept still; the ones not yet reached are hidden. */
function RecapGraph(props: {
  claims: Claim[]
  edges: Story['edges']
  positions: Story['positions']
  shown: Set<number>
  fresh: Set<number>
  weakOnly: boolean
  onLaidOut: (positions: Record<number, [number, number]>) => void
  onPick: (id: number | null) => void
}) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const [built, setBuilt] = useState(0)
  const theme = useTheme()
  const { claims, edges, positions, onLaidOut, onPick } = props

  useEffect(() => {
    if (!box.current) return
    let gone = false
    loadCytoscape().then((cytoscape) => {
      if (gone || !box.current) return
      const placed = positions !== null && claims.every((c) => positions[c.id])
      cy.current = cytoscape({
        container: box.current,
        boxSelectionEnabled: false,
        autoungrabify: true,
        userZoomingEnabled: false,
        userPanningEnabled: false,
        elements: graphElements(claims, edges, placed ? positions : null),
        style: graphStyle(),
        layout: placed
          ? { name: 'preset', fit: true, padding: 12 }
          : ({ name: 'fcose', quality: 'proof', animate: false, nodeRepulsion: () => 6000, idealEdgeLength: () => 40, padding: 12 } as cytoscape.LayoutOptions),
      })
      if (!placed) onLaidOut(Object.fromEntries(cy.current.nodes().map((n) => [Number(n.id()), [Math.round(n.position('x')), Math.round(n.position('y'))]])))
      cy.current.on('tap', 'node', (e) => onPick(Number(e.target.id())))
      cy.current.on('tap', (e) => e.target === cy.current && onPick(null))
      fit.observe(box.current)
      setBuilt((n) => n + 1)
    })
    const fit = new ResizeObserver(() => {
      cy.current?.resize()
      cy.current?.fit(undefined, 12)
    })
    return () => {
      gone = true
      fit.disconnect()
      cy.current?.destroy()
      cy.current = null
    }
  }, [claims, edges, theme]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const reached = (id: string) => props.shown.has(Number(id))
    const weak = new Set(claims.filter(isWeak).map((c) => String(c.id)))
    const dim = (id: string) => props.weakOnly && !weak.has(id)
    cy.current?.batch(() => {
      cy.current!.nodes().forEach((n) => {
        n.toggleClass('away', !reached(n.id()))
        n.toggleClass('fresh', props.fresh.has(Number(n.id())))
        n.toggleClass('dim', dim(n.id()))
      })
      cy.current!.edges().forEach((e) => {
        e.toggleClass('away', !reached(e.source().id()) || !reached(e.target().id()))
        e.toggleClass('dim', dim(e.source().id()) || dim(e.target().id()))
      })
    })
  }, [claims, props.shown, props.fresh, props.weakOnly, built])

  return <div ref={box} className="h-64 max-[60rem]:h-22 max-[60rem]:flex-[0_0_6.5rem]" role="img" aria-label={t('recap.graphAlt', { n: props.shown.size, total: claims.length })} />
}

export function Recap({ courseId, profile, preview }: { courseId: number; profile: number; preview: boolean }) {
  const { t, i18n } = useTranslation()
  const [story, setStory] = useState<Story | null>(null)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState<number | null>(null)
  const [weakOnly, setWeakOnly] = useState(false)
  const [next, setNext] = useState<Suggestion[]>([])
  const [contributed, setContributed] = useState(0)
  const load = () => api<Story>(`/api/courses/${courseId}/recap${preview ? '?preview=true' : ''}`).then(setStory, (e: Error) => setError(e.message))

  useEffect(() => {
    load()
    if (!preview) api(`/api/courses/${courseId}/recap/seen`, {}).catch(() => {})
    api<{ suggestions: Suggestion[] }>(`/api/suggestions?profile=${profile}`).then((s) => setNext(s.suggestions), () => {})
    return followCourse(
      courseId,
      ({ type }) => {
        if (type === 'recap.written') load()
        else if (type === 'contributions.written') setContributed((n) => n + 1)
      },
      load,
    )
  }, [courseId, preview]) // eslint-disable-line react-hooks/exhaustive-deps

  // print shows every step open and the whole graph
  useEffect(() => {
    const open = () => document.querySelectorAll<HTMLDetailsElement>('.recap details').forEach((d) => (d.open = true))
    addEventListener('beforeprint', open)
    return () => removeEventListener('beforeprint', open)
  }, [])

  const { cursor, playing, setPlaying, timeline, end } = useStoryScroll(story)

  const derived = useMemo(() => {
    if (!story) return null
    const at = (c: Claim) => c.step ?? story.steps.findIndex((s) => s.finished >= c.created)
    const claimAt = new Map(story.claims.map((c) => [c.id, at(c) === -1 ? story.steps.length - 1 : at(c)]))
    return { claimAt, claims: new Map(story.claims.map((c) => [c.id, c])), mistakes: new Map(story.mistakes.map((m) => [m.id, m])) }
  }, [story])

  const shown = useMemo(
    () => new Set(story?.claims.filter((c) => derived!.claimAt.get(c.id)! <= cursor).map((c) => c.id) ?? []),
    [story, derived, cursor],
  )
  const fresh = useMemo(() => new Set(story?.claims.filter((c) => derived!.claimAt.get(c.id) === cursor).map((c) => c.id) ?? []), [story, derived, cursor])

  if (error) return <main className="mx-auto flex w-full max-w-(--measure) flex-col gap-10 px-6 pt-10 pb-16"><div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div></main>
  if (!story || !derived) return <main className={PAGE} />

  const unitLink = (conceptId: number | null) => (conceptId ? `#/course/${courseId}?concept=${conceptId}` : `#/course/${courseId}`)
  const weak = story.claims.filter(isWeak)
  const open = story.mistakes.filter((m) => !m.put_right)
  const sure = story.answers.length >= CHART_FROM ? sureGroups(story.answers) : null

  function saveLayout(positions: Record<number, [number, number]>) {
    if (!story!.preview) api(`/api/courses/${courseId}/recap/positions`, { positions }).catch(() => {})
  }

  function rewrite() {
    api(`/api/courses/${courseId}/recap/write`, {}).then(() => setStory((s) => s && { ...s, writing: true, failed: false }), (e: Error) => setError(e.message))
  }

  return (
    <main className={PAGE}>
      <RecapHero story={story} courseId={courseId} />

      <Narration story={story} onRewrite={rewrite} language={LOCALES[i18n.language as Locale]}>
        {story.narrative && <p className={cn(LEAD, 'leading-[1.6]')} dir="auto"><InlineMarkdown>{story.narrative.intro}</InlineMarkdown></p>}
      </Narration>

      <div className="grid grid-cols-[minmax(0,1fr)_20rem] items-start gap-10 max-[60rem]:grid-cols-1 max-[60rem]:gap-4">
        <RecapPanel
          story={story}
          cursor={cursor}
          shown={shown}
          fresh={fresh}
          weak={weak}
          weakOnly={weakOnly}
          onWeakOnly={setWeakOnly}
          picked={picked !== null ? derived.claims.get(picked) : undefined}
          onPick={setPicked}
          onLaidOut={saveLayout}
          playing={playing}
          onPlay={() => setPlaying((p) => !p)}
        />

        <div ref={timeline} className="col-start-1 row-start-1 flex min-w-0 flex-col gap-10 max-[60rem]:row-start-2">
          <Timeline story={story} cursor={cursor} claims={derived.claims} mistakes={derived.mistakes} unitLink={unitLink} />
        </div>
      </div>

      <section ref={end} className="grid grid-cols-2 gap-10 border-t pt-10 max-[60rem]:grid-cols-1 [&>div]:flex [&>div]:min-w-0 [&>div]:flex-col [&>div]:gap-3">
        {sure && <SureChart answers={story.answers} {...sure} />}
        <WeakSection story={story} weak={weak} open={open} unitLink={unitLink} />
        {story.narrative?.letter && (
          <div className="rounded-lg bg-accent p-6">
            <h2 className={H2}>{t('recap.letterTitle')}</h2>
            <p className={cn(LEAD, 'leading-[1.65]')} dir="auto"><InlineMarkdown>{story.narrative.letter}</InlineMarkdown></p>
          </div>
        )}
        <NextSection story={story} next={next} courseId={courseId} />
        <ContributeSection courseId={courseId} preview={story.preview} written={contributed} />
      </section>
    </main>
  )
}

/** Where the story stands, the step crossing the middle of the screen, and its playback: play scrolls the story to
its end in PLAY_MS, any scroll, tap or key of the learner's stops it, and Space toggles it. */
function useStoryScroll(story: Story | null) {
  const [cursor, setCursor] = useState(-1)
  const [playing, setPlaying] = useState(false)
  const timeline = useRef<HTMLDivElement>(null)
  const end = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!story || !timeline.current) return
    const seen = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setCursor(Number((e.target as HTMLElement).dataset.step))
      },
      { rootMargin: '-45% 0px -55% 0px' },
    )
    timeline.current.querySelectorAll('[data-step]').forEach((el) => seen.observe(el))
    return () => seen.disconnect()
  }, [story])

  useEffect(() => {
    if (!playing) return
    const top = timeline.current!.getBoundingClientRect().top + scrollY - innerHeight * 0.4
    const bottom = end.current!.getBoundingClientRect().top + scrollY - innerHeight * 0.5
    if (scrollY >= bottom - 4) scrollTo({ top, behavior: 'instant' })
    const from = scrollY
    const length = Math.max(1, bottom - top)
    const ms = (PLAY_MS * (bottom - from)) / length
    const start = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms)
      scrollTo({ top: from + (bottom - from) * p, behavior: 'instant' })
      if (p < 1) frame = requestAnimationFrame(tick)
      else setPlaying(false)
    }
    frame = requestAnimationFrame(tick)
    const stop = (e: Event) => {
      if (!(e.target instanceof Element && e.target.closest('.recap-play'))) setPlaying(false)
    }
    const key = (e: KeyboardEvent) => e.key !== ' ' && setPlaying(false)
    addEventListener('wheel', stop, { passive: true })
    addEventListener('touchstart', stop, { passive: true })
    addEventListener('pointerdown', stop)
    addEventListener('keydown', key)
    return () => {
      cancelAnimationFrame(frame)
      removeEventListener('wheel', stop)
      removeEventListener('touchstart', stop)
      removeEventListener('pointerdown', stop)
      removeEventListener('keydown', key)
    }
  }, [playing])

  // Space plays and pauses, unless it is typing or pressing a control
  useEffect(() => {
    const space = (e: KeyboardEvent) => {
      if (e.key !== ' ' || (e.target instanceof Element && e.target.closest('input, textarea, select, button, summary, a, [contenteditable]'))) return
      e.preventDefault()
      setPlaying((p) => !p)
    }
    addEventListener('keydown', space)
    return () => removeEventListener('keydown', space)
  }, [])

  return { cursor, playing, setPlaying, timeline, end }
}

function RecapHero({ story, courseId }: { story: Story; courseId: number }) {
  const { t } = useTranslation()
  const { stats } = story
  const range = (from: string | null, to: string | null) => [from, to].map((d) => (d ? day(d) : '…')).join(' – ')
  return (
    <header
      className={cn(
        'grid grid-cols-[minmax(0,20rem)_minmax(0,1fr)] items-center gap-10 animate-[recap-rise_var(--dur-long)_var(--ease-out)_both] motion-reduce:animate-none max-[60rem]:grid-cols-1 max-[60rem]:gap-4 print:animate-none',
        !story.course.cover && 'grid-cols-1',
      )}
    >
      {story.course.cover && <img className="block aspect-video w-full rounded-lg border bg-accent object-cover" src={`/api/courses/${courseId}/cover`} alt={story.course.cover_alt ?? ''} />}
      <div>
        <div className={LABEL}>{t(story.preview ? 'recap.eyebrowPreview' : 'recap.eyebrow', { dates: range(story.started, story.finished) })}</div>
        <h1 className="mt-1 mb-6 text-3xl leading-[1.15] text-balance max-[60rem]:text-2xl" dir="auto">{story.course.topic}</h1>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-3">
          <Tile value={stats.minutes / 60} decimals={1} label={t(stats.estimated ? 'recap.hoursAbout' : 'recap.hours')} />
          <Tile
            value={stats.units_done}
            total={stats.units}
            label={t('recap.units')}
            sub={stats.projects ? t('recap.projects', { done: stats.projects_done, total: stats.projects }) : undefined}
          />
          {stats.claims > 0 && <Tile value={stats.claims_held} total={stats.claims} label={t('recap.claimsHeld')} />}
          {stats.mistakes > 0 && <Tile value={stats.mistakes_fixed} total={stats.mistakes} label={t('recap.mistakesFixed')} />}
        </div>
      </div>
    </header>
  )
}

function RecapPanel(props: {
  story: Story
  cursor: number
  shown: Set<number>
  fresh: Set<number>
  weak: Claim[]
  weakOnly: boolean
  onWeakOnly: (weakOnly: boolean) => void
  picked: Claim | undefined
  onPick: (id: number | null) => void
  onLaidOut: (positions: Record<number, [number, number]>) => void
  playing: boolean
  onPlay: () => void
}) {
  const { t } = useTranslation()
  const { story, shown, weak, picked: pickedClaim } = props
  const { stats } = story
  const reached = story.steps.slice(0, props.cursor + 1)
  const reachedAt = reached.at(-1)?.finished
  const graphShown = story.claims.length >= GRAPH_FROM
  return (
    <aside
      className="sticky top-4 col-start-2 row-start-1 flex flex-col gap-3 rounded-lg border bg-card p-4 max-[60rem]:top-0 max-[60rem]:z-(--z-sticky) max-[60rem]:col-start-1 max-[60rem]:-mx-4 max-[60rem]:flex-row max-[60rem]:items-center max-[60rem]:rounded-none max-[60rem]:border-x-0 max-[60rem]:px-4 max-[60rem]:py-2 print:static"
      aria-label={t('recap.panel')}>
      {graphShown && weak.length > 0 && (
        <div className="flex rounded-md bg-secondary p-0.5 max-[60rem]:hidden" role="group" aria-label={t('recap.panel')}>
          <Button type="button" variant="outline" className={LENS} aria-pressed={!props.weakOnly} onClick={() => props.onWeakOnly(false)}>{t('recap.graphAll')}</Button>
          <Button type="button" variant="outline" className={LENS} aria-pressed={props.weakOnly} onClick={() => props.onWeakOnly(true)}>
            {t('recap.graphWeak')} <span className="text-muted-foreground">{number(weak.length)}</span>
          </Button>
        </div>
      )}
      {graphShown && (
        <RecapGraph
          claims={story.claims}
          edges={story.edges}
          positions={story.positions}
          shown={shown}
          fresh={props.fresh}
          weakOnly={props.weakOnly}
          onLaidOut={props.onLaidOut}
          onPick={props.onPick}
        />
      )}
      <div className="flex flex-col gap-2 max-[60rem]:min-w-0 max-[60rem]:flex-1">
        <span className={LABEL}>{reachedAt ? day(reachedAt) : t('recap.start')}</span>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm text-muted-foreground max-[60rem]:grid-cols-[repeat(4,auto)] max-[60rem]:justify-start max-[60rem]:text-xs [&_span]:whitespace-nowrap [&_strong]:text-lg [&_strong]:text-foreground [&_strong]:tabular-nums max-[60rem]:[&_strong]:text-base">
          <span><strong>{number(story.before.length + reached.length)}</strong> {t('recap.countUnits')}</span>
          {stats.claims > 0 && <span><strong>{number(shown.size)}</strong> {t('recap.countClaims')}</span>}
          {stats.mistakes > 0 && (
            <span><strong>{number(story.mistakes.filter((m) => m.fixed && reachedAt && m.fixed <= nextDay(reachedAt)).length)}</strong> {t('recap.countFixed')}</span>
          )}
          <span><strong>{number(reached.reduce((s, x) => s + x.minutes, 0) / 60)}</strong> {t('recap.countHours')}</span>
        </div>
        {pickedClaim && (
          <div className="flex flex-col items-start gap-0.5 text-sm text-muted-foreground max-[60rem]:hidden">
            <p className="m-0" dir="auto">
              <Dot state={pickedClaim.state} />
              <InlineMarkdown>{pickedClaim.text}</InlineMarkdown>
            </p>
            {pickedClaim.step !== null && (
              <Button type="button" variant="link" className="h-auto bg-transparent p-0 text-sm font-normal text-accent-foreground underline" onClick={() => showStep(pickedClaim.step!)}>{t('recap.showInStory')}</Button>
            )}
          </div>
        )}
        <Button type="button" variant="outline" className={'recap-play self-start print:hidden'} aria-pressed={props.playing} onClick={props.onPlay} title={t('recap.playHint')}>
          {props.playing ? t('recap.pause') : t('recap.play')}
        </Button>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1 border-t p-0 pt-3 text-sm text-muted-foreground max-[60rem]:hidden">
        {story.modules.map((m) => (
          <li key={m} dir="auto">
            <i className="me-1 inline-block size-3 rounded-[2px] align-[-0.1rem]" style={{ background: moduleColor(story.modules, m) }} /> {m}
          </li>
        ))}
      </ul>
    </aside>
  )
}

function Timeline(props: { story: Story; cursor: number; claims: Map<number, Claim>; mistakes: Map<number, Mistake>; unitLink: (conceptId: number | null) => string }) {
  const { t } = useTranslation()
  const { story, cursor, unitLink } = props
  const { steps, narrative } = story
  return (
    <>
      {story.before.length > 0 && (
        <details className="rounded-lg bg-secondary px-4 py-3" data-step={-1}>
          <summary className={SUMMARY}>
            <strong>{t('recap.before')}</strong> <span className="text-muted-foreground">{t('recap.beforeCount', { count: story.before.length })}</span>
          </summary>
          <ul className="mt-2 mb-0 ps-6">
            {story.before.map((u) => (
              <li key={u.concept_id} dir="auto">{u.title}</li>
            ))}
          </ul>
        </details>
      )}
      {story.weeks.map((w) => (
        <section key={w} className="flex flex-col gap-3">
          <h2 className={cn(LABEL, 'm-0')}>{t('recap.week', { date: day(w) })}</h2>
          {narrative?.weeks[w] && <p className={cn(LEAD, 'max-w-(--measure) leading-[1.55]')} dir="auto"><InlineMarkdown>{narrative.weeks[w]}</InlineMarkdown></p>}
          <ol className="m-0 flex list-none flex-col p-0">
            {steps.map((s, n) => s.week === w && (
              <li key={s.concept_id} data-step={n} className={cn(STEP, n <= cursor && 'before:bg-(--module)')} style={{ '--module': moduleColor(story.modules, s.module) } as CSSProperties}>
                <StepCard step={s} claims={props.claims} mistakes={props.mistakes} link={unitLink(s.concept_id)} />
              </li>
            ))}
          </ol>
        </section>
      ))}
      {narrative?.can_do && (
        <section className="flex flex-col gap-3 rounded-e-lg border-s-4 border-primary bg-accent px-6 py-4">
          <h2 className={H2}>{t('recap.canDoTitle')}</h2>
          <ul className={LIST}>
            {narrative.can_do.map((p) => (
              <li key={p} className="relative ps-6 leading-normal before:absolute before:start-0 before:top-[0.45em] before:h-[0.8rem] before:w-[0.45rem] before:rotate-45 before:border-0 before:border-r-2 before:border-b-2 before:border-solid before:border-primary" dir="auto"><InlineMarkdown>{p}</InlineMarkdown></li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

/** A course's answers grouped by day when it took under two weeks, by week otherwise; null when they all fall on one day. */
function sureGroups(answers: Story['answers']): { daily: boolean; groups: Map<string, Story['answers']> } | null {
  const days = answers.map((a) => a.created.slice(0, 10))
  if (days[0] === days.at(-1)) return null
  const daily = Date.parse(days.at(-1)!) - Date.parse(days[0]) < 14 * 86_400_000
  const groups = new Map<string, Story['answers']>()
  answers.forEach((a, n) => {
    const key = daily ? days[n] : monday(days[n])
    groups.set(key, [...(groups.get(key) ?? []), a])
  })
  return { daily, groups }
}

/** How sure the learner was against how often they were right, day by day or week by week. */
function SureChart({ answers, daily, groups }: { answers: Story['answers']; daily: boolean; groups: Map<string, Story['answers']> }) {
  const { t } = useTranslation()
  const quarter = Math.max(5, Math.floor(answers.length / 4))
  const points = [...groups].flatMap(([key, sums]) => {
    const when = new Date(key)
    return [
      { when, value: (100 * sums.reduce((s, a) => s + a.confidence, 0)) / sums.length, series: t('recap.sure') },
      { when, value: (100 * sums.filter((a) => a.correct).length) / sums.length, series: t('recap.right') },
    ]
  })
  const chart = {
    height: 260,
    y: { label: '%', domain: [0, 100] as [number, number] },
    x: { label: '' },
    marks: [
      { type: 'line' as const, data: points, x: 'when', y: 'value', stroke: 'series', strokeWidth: 2 },
      { type: 'dot' as const, data: points, x: 'when', y: 'value', fill: 'series' },
    ],
  }
  return (
    <div className="col-span-full">
      <h2 className={H2}>{t('recap.sureTitle')}</h2>
      <PlotBox spec={chart} alt={t(daily ? 'recap.chartAltDaily' : 'recap.chartAlt')} />
      <p className={cn(SMALL, 'm-0')}>
        {t('recap.brier', { start: number(brier(answers.slice(0, quarter)), 2), end: number(brier(answers.slice(-quarter)), 2) })}
      </p>
    </div>
  )
}

function WeakSection({ story, weak, open, unitLink }: { story: Story; weak: Claim[]; open: Mistake[]; unitLink: (conceptId: number | null) => string }) {
  const { t } = useTranslation()
  const { narrative } = story
  const toStrengthen = story.steps
    .map((s, n) => ({
      step: s,
      n,
      shaky: weak.filter((c) => c.step === n && c.state === 'shaky').length,
      fading: weak.filter((c) => c.step === n && c.state === 'fading').length,
      open: open.filter((m) => m.step === n).length,
    }))
    .filter((g) => g.shaky + g.fading + g.open > 0)
  const weakElsewhere = weak.filter((c) => c.step === null)
  const openElsewhere = open.filter((m) => m.step === null)
  return (
    <div>
      <h2 className={H2}>{t('recap.weakTitle')}</h2>
      {weak.length === 0 && open.length === 0 && <p className="text-muted-foreground">{t('recap.nothingWeak')}</p>}
      {narrative?.strengthen && (weak.length > 0 || open.length > 0) && (
        <ul className={LIST}>
          {narrative.strengthen.map((p) => (
            <li key={p} className="leading-[1.55]" dir="auto"><InlineMarkdown>{p}</InlineMarkdown></li>
          ))}
        </ul>
      )}
      {!story.preview && (weak.length > 0 || open.length > 0) && <Revisit courseId={story.course.id} />}
      {toStrengthen.length > 0 && (
        <ul className={LIST}>
          {toStrengthen.map((g) => (
            <li key={g.n} className="flex items-center gap-3 rounded-e-md border-s-4 border-(--module)" style={{ '--module': moduleColor(story.modules, g.step.module) } as CSSProperties}>
              <Button
                type="button"
                variant="outline"
                className="h-auto min-h-11 min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-none rounded-e-md border-0 bg-transparent px-3 py-2 text-start text-base font-normal whitespace-normal text-foreground hover:bg-secondary"
                onClick={() => showStep(g.n)}
                title={t('recap.showInStory')}
              >
                <strong dir="auto">{g.step.kind === 'practice' ? practiceTitle(g.step.title, t) : g.step.title}</strong>
                <WeakCounts shaky={g.shaky} fading={g.fading} open={g.open} />
              </Button>
              <a className="flex-none text-sm text-accent-foreground no-underline hover:underline" href={unitLink(g.step.concept_id)}>{t('recap.openUnit')}</a>
            </li>
          ))}
        </ul>
      )}
      {weakElsewhere.length + openElsewhere.length > 0 && (
        <details>
          <summary className="cursor-pointer">
            <strong>{t('recap.elsewhere')}</strong>{' '}
            <WeakCounts
              shaky={weakElsewhere.filter((c) => c.state === 'shaky').length}
              fading={weakElsewhere.filter((c) => c.state === 'fading').length}
              open={openElsewhere.length}
            />
          </summary>
          <ul className={cn(LIST, 'mt-3')}>
            {weakElsewhere.map((c) => (
              <li key={`c${c.id}`} dir="auto">
                <Dot state={c.state} />
                <InlineMarkdown>{c.text}</InlineMarkdown>
              </li>
            ))}
            {openElsewhere.map((m) => (
              <li key={`m${m.id}`} dir="auto">
                <Prompt text={m.prompt}>
                  <a className="text-sm text-accent-foreground underline" href={unitLink(m.concept_id)}>{t('recap.openUnit')}</a>
                </Prompt>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

/** Opens the lesson that goes over what is still shaky on the board, or the one already open. */
function Revisit({ courseId }: { courseId: number }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  function start() {
    setBusy(true)
    setError('')
    api(`/api/courses/${courseId}/revisit`, {}).then(
      () => (location.hash = `#/course/${courseId}`),
      (e: Error) => {
        setBusy(false)
        setError(e.message)
      },
    )
  }
  return (
    <div className="mb-4 flex flex-col items-start gap-2">
      <Button onClick={start} disabled={busy}>{t('recap.revisit')}</Button>
      <p className={cn(SMALL, 'm-0')}>{t('recap.revisitNote')}</p>
      {error && <div className="rounded-md bg-warm-tint px-4 py-2 text-warm-ink">{error}</div>}
    </div>
  )
}

function NextSection({ story, next, courseId }: { story: Story; next: Suggestion[]; courseId: number }) {
  const { t } = useTranslation()
  const { narrative } = story
  const nextUp = next.filter((s) => s.builds_on === story.course.topic).slice(0, 3)
  return (
    <div>
      <h2 className={H2}>{t('recap.nextTitle')}</h2>
      {narrative?.next_step && <p className="m-0" dir="auto"><InlineMarkdown>{narrative.next_step}</InlineMarkdown></p>}
      {nextUp.length > 0 && (
        <ul className={LIST}>
          {nextUp.map((s) => (
            <li key={s.id} className="flex flex-col gap-0.5">
              <strong dir="auto">{s.title}</strong>
              <span className={SMALL} dir="auto">{s.pitch}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <a className={buttonVariants({ variant: 'outline' })} href="#/explore">{t('recap.explore')}</a>
        <a className={buttonVariants({ variant: 'outline' })} href={`/api/courses/${courseId}/book.pdf`}>{t('recap.book')}</a>
      </div>
    </div>
  )
}

function Narration({ story, onRewrite, language, children }: { story: Story; onRewrite: () => void; language: string; children: ReactNode }) {
  const { t, i18n } = useTranslation()
  if (story.preview) return <p className={SMALL}>{t('recap.previewNote')}</p>
  if (story.writing) return <p className="text-muted-foreground" role="status">{t('recap.writing')}</p>
  if (story.failed && !story.narrative)
    return (
      <p className="text-muted-foreground" role="status">
        {t('recap.failed')}{' '}
        <Button type="button" variant="outline" onClick={onRewrite}>{t('recap.tryAgain')}</Button>
      </p>
    )
  return (
    <>
      {children}
      {story.narrative && story.narrative.locale !== i18n.language && (
        <Button type="button" variant="outline" className={'self-start print:hidden'} onClick={onRewrite}>
          {t('recap.rewrite', { language })}
        </Button>
      )}
    </>
  )
}

/** A claim's state as a coloured dot, before what follows it. */
function Dot({ state, children }: { state: State; children?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <span title={t(`graph.state.${state}`)}>
      <span className="me-1 inline-block size-[0.7rem] rounded-full align-[-0.05rem]" style={{ background: `var(${STATE_COLOR[state]})` }} />
      {children}
    </span>
  )
}

function WeakCounts({ shaky, fading, open }: { shaky: number; fading: number; open: number }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex flex-wrap gap-3 text-sm text-muted-foreground tabular-nums">
      {shaky > 0 && <Dot state="shaky">{number(shaky)}</Dot>}
      {fading > 0 && <Dot state="fading">{number(fading)}</Dot>}
      {open > 0 && <span className="text-destructive">{t('recap.openCount', { count: open })}</span>}
    </span>
  )
}

function StepCard({ step, claims, mistakes, link }: { step: Step; claims: Map<number, Claim>; mistakes: Map<number, Mistake>; link: string }) {
  const { t } = useTranslation()
  const own = step.claims.map((id) => claims.get(id)!).filter(Boolean)
  const missed = step.mistakes.map((id) => mistakes.get(id)!).filter(Boolean)
  const fixed = missed.filter((m) => m.put_right).length
  const weak = own.filter(isWeak).length + missed.filter((m) => !m.put_right).length
  const right = step.checks.filter((c) => c.correct).length
  const sure = step.checks.length ? step.checks.reduce((s, c) => s + c.confidence, 0) / step.checks.length : 0
  return (
    <details>
      <summary className={cn(SUMMARY, 'flex flex-col gap-1 rounded-md px-3 py-2 hover:bg-secondary [details[open]>&]:bg-card [details[open]>&]:shadow-[0_0_0_1px_var(--color-border)]')}>
        <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <strong dir="auto">{step.kind === 'practice' ? practiceTitle(step.title, t) : step.title}</strong>
          <span className={SMALL}>{day(step.finished)}</span>
        </span>
        {own.length > 0 && (
          <span className="flex flex-wrap gap-1">
            {own.slice(0, 3).map((c) => (
              <span key={c.id} className={cn('max-w-full overflow-hidden rounded-sm border border-s-3 bg-card px-2 py-0.5 text-xs text-ellipsis whitespace-nowrap sm:max-w-96', CHIP_EDGE[c.state])} dir="auto">
                {c.text}
              </span>
            ))}
            {own.length > 3 && <span className={SMALL}>{t('recap.moreClaims', { count: own.length - 3 })}</span>}
          </span>
        )}
        {(missed.length > 0 || step.milestone || weak > 0) && <StepMarks step={step} weak={weak} missed={missed.length} fixed={fixed} />}
      </summary>
      <div className="flex flex-col gap-2 px-3 pt-3 pb-4 [&_p]:m-0">
        {own.length > 0 && <ClaimList claims={own} />}
        {missed.length > 0 && <MistakeList mistakes={missed} />}
        {step.milestone && (
          <p className={SMALL} dir="auto">
            <span className="font-semibold text-warm">{t('recap.project')}</span> {step.milestone.project}: <code>{step.milestone.deliverable}</code>
          </p>
        )}
        <p className={SMALL}>
          {t(step.estimated ? 'recap.minutesAbout' : 'recap.minutes', { n: step.minutes })}
          {step.checks.length > 0 && ` · ${t('recap.checks', { right, total: step.checks.length, sure: percent(sure) })}`}
        </p>
        <a className={SMALL} href={link}>{t('recap.openUnit')}</a>
      </div>
    </details>
  )
}

function StepMarks({ step, weak, missed, fixed }: { step: Step; weak: number; missed: number; fixed: number }) {
  const { t } = useTranslation()
  return (
    <span className="flex flex-wrap gap-3 text-sm text-muted-foreground">
      {weak > 0 && <span className="text-warm">{t('recap.toStrengthen', { count: weak })}</span>}
      {missed > 0 && <span className="text-destructive">{t('recap.mistakes', { count: missed })}</span>}
      {fixed > 0 && <span className="text-primary">{t('recap.putRight', { count: fixed })}</span>}
      {step.milestone && (
        <span className="font-semibold text-warm" title={step.milestone.deliverable}>
          {t('recap.project')}
        </span>
      )}
    </span>
  )
}

/** A step's claims, the weak ones first. */
function ClaimList({ claims }: { claims: Claim[] }) {
  return (
    <ul className={cn(LIST, 'text-sm')}>
      {[...claims.filter(isWeak), ...claims.filter((c) => !isWeak(c))].map((c) => (
        <li key={c.id} dir="auto">
          <Dot state={c.state} />
          <InlineMarkdown>{c.text}</InlineMarkdown>
        </li>
      ))}
    </ul>
  )
}

function MistakeList({ mistakes }: { mistakes: Mistake[] }) {
  const { t } = useTranslation()
  return (
    <ul className={cn(LIST, 'text-sm')}>
      {mistakes.map((m) => (
        <li key={m.id} className="border-s-2 ps-3" dir="auto">
          <Prompt text={m.prompt}>
            <span className={cn('text-sm', m.put_right ? 'text-primary' : 'text-destructive')}>
              {m.fixed ? t('recap.fixedOn', { date: day(m.fixed) }) : m.put_right ? t('recap.fixed') : t('recap.stillOpen')}
            </span>
          </Prompt>
        </li>
      ))}
    </ul>
  )
}

/** A mistake's question: its first paragraph, with the rest (tables, display math, the parts) folded under it. */
function Prompt({ text, children }: { text: string; children: ReactNode }) {
  const [lead, ...rest] = text.trim().split(/\n\s*\n/)
  if (lead.trimStart().startsWith('|') || lead.includes('$$'))
    return (
      <div className={PROMPT}>
        <Markdown>{text}</Markdown>
        {children}
      </div>
    )
  if (rest.length === 0)
    return (
      <div className={PROMPT}>
        <InlineMarkdown>{lead}</InlineMarkdown> {children}
      </div>
    )
  return (
    <details className={PROMPT}>
      <summary>
        <InlineMarkdown>{lead}</InlineMarkdown> {children}
      </summary>
      <Markdown>{rest.join('\n\n')}</Markdown>
    </details>
  )
}

function monday(day: string): string {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7))
  return d.toISOString().slice(0, 10)
}

function nextDay(stamp: string): string {
  return `${stamp.slice(0, 10)} 23:59:59`
}
