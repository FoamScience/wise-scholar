import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import type { Core } from 'cytoscape'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { practiceTitle } from './course'
import { day, number, percent } from './i18n'
import { LOCALES } from './locale'
import type { Locale } from './locale'
import Markdown, { InlineMarkdown } from './Md'
import { PlotBox } from './PlotCard'
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
type Narrative = { intro: string; weeks: Record<string, string>; letter: string; locale: Locale; finished: string }
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

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches

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
    <div className="recap-tile">
      <strong>
        {number(Number(n.toFixed(decimals)))}
        {total !== undefined && <span className="muted">/{number(total)}</span>}
      </strong>
      <span>{label}</span>
      {sub && <span className="small muted">{sub}</span>}
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

/** The claims as dots, laid out once and kept still; the ones not yet reached are hidden. */
function RecapGraph(props: {
  claims: Claim[]
  edges: Story['edges']
  positions: Story['positions']
  shown: Set<number>
  fresh: Set<number>
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
      const ink = token('--ink')
      cy.current = cytoscape({
        container: box.current,
        boxSelectionEnabled: false,
        autoungrabify: true,
        userZoomingEnabled: false,
        userPanningEnabled: false,
        elements: [
          ...claims.map((c) => ({
            data: { id: String(c.id), color: token(STATE_COLOR[c.state]) },
            ...(placed ? { position: { x: positions![c.id][0], y: positions![c.id][1] } } : {}),
          })),
          ...edges.map((e) => ({ data: { id: `${e.from_id}-${e.to_id}-${e.kind}`, source: String(e.from_id), target: String(e.to_id), kind: e.kind } })),
        ],
        style: [
          { selector: 'node', style: { width: 9, height: 9, 'background-color': 'data(color)', 'border-width': 0 } },
          { selector: 'node.fresh', style: { width: 14, height: 14, 'border-width': 2, 'border-color': ink } },
          { selector: 'node:selected', style: { 'border-width': 2, 'border-color': ink } },
          { selector: 'node.away', style: { 'background-color': token('--mastery-off'), opacity: 0.35 } },
          { selector: 'edge.away', style: { opacity: 0.08 } },
          { selector: 'edge', style: { width: 0.8, 'line-color': token('--line-strong'), opacity: 0.55, 'curve-style': 'straight' } },
          { selector: 'edge[kind = "contrasts"]', style: { 'line-style': 'dotted', 'line-color': token('--danger') } },
        ],
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
    cy.current?.batch(() => {
      cy.current!.nodes().forEach((n) => {
        n.toggleClass('away', !reached(n.id()))
        n.toggleClass('fresh', props.fresh.has(Number(n.id())))
      })
      cy.current!.edges().forEach((e) => {
        e.toggleClass('away', !reached(e.source().id()) || !reached(e.target().id()))
      })
    })
  }, [props.shown, props.fresh, built])

  return <div ref={box} className="recap-graph" role="img" aria-label={t('recap.graphAlt', { n: props.shown.size, total: claims.length })} />
}

export function Recap({ courseId, profile, preview }: { courseId: number; profile: number; preview: boolean }) {
  const { t, i18n } = useTranslation()
  const [story, setStory] = useState<Story | null>(null)
  const [error, setError] = useState('')
  const [cursor, setCursor] = useState(-1)
  const [playing, setPlaying] = useState(false)
  const [picked, setPicked] = useState<number | null>(null)
  const [next, setNext] = useState<Suggestion[]>([])
  const end = useRef<HTMLElement>(null)
  const timeline = useRef<HTMLDivElement>(null)

  const load = () => api<Story>(`/api/courses/${courseId}/recap${preview ? '?preview=true' : ''}`).then(setStory, (e: Error) => setError(e.message))

  useEffect(() => {
    load()
    if (!preview) api(`/api/courses/${courseId}/recap/seen`, {}).catch(() => {})
    api<{ suggestions: Suggestion[] }>(`/api/suggestions?profile=${profile}`).then((s) => setNext(s.suggestions), () => {})
    const source = new EventSource(`/api/courses/${courseId}/events`)
    source.onmessage = (raw) => {
      if (JSON.parse(raw.data).type === 'recap.written') load()
    }
    return () => source.close()
  }, [courseId, preview]) // eslint-disable-line react-hooks/exhaustive-deps

  // print shows every step open and the whole graph
  useEffect(() => {
    const open = () => document.querySelectorAll<HTMLDetailsElement>('.recap details').forEach((d) => (d.open = true))
    addEventListener('beforeprint', open)
    return () => removeEventListener('beforeprint', open)
  }, [])

  // the step crossing the middle of the screen is where the story stands
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

  if (error) return <main className="home"><div className="error">{error}</div></main>
  if (!story || !derived) return <main className="recap" />

  const { stats, steps, narrative } = story
  const reached = steps.slice(0, cursor + 1)
  const reachedAt = reached.at(-1)?.finished
  const graphShown = story.claims.length >= GRAPH_FROM
  const range = (from: string | null, to: string | null) => [from, to].map((d) => (d ? day(d) : '…')).join(' – ')
  const weekLabel = (w: string) => t('recap.week', { date: day(w) })
  const unitLink = (conceptId: number | null) => (conceptId ? `#/course/${courseId}?concept=${conceptId}` : `#/course/${courseId}`)
  const weak = story.claims.filter((c) => c.state === 'shaky' || c.state === 'fading')
  const open = story.mistakes.filter((m) => !m.put_right)
  const conceptOfClaim = (c: Claim) => (c.step !== null ? steps[c.step].concept_id : null)
  const answers = story.answers
  const quarter = Math.max(5, Math.floor(answers.length / 4))
  const nextUp = next.filter((s) => s.builds_on === story.course.topic).slice(0, 3)
  const language = LOCALES[i18n.language as Locale]

  function saveLayout(positions: Record<number, [number, number]>) {
    if (!story!.preview) api(`/api/courses/${courseId}/recap/positions`, { positions }).catch(() => {})
  }

  function rewrite() {
    api(`/api/courses/${courseId}/recap/write`, {}).then(() => setStory((s) => s && { ...s, writing: true, failed: false }), (e: Error) => setError(e.message))
  }

  const weeks = story.weeks.map((w) => {
    const sums = answers.filter((a) => a.created >= w && a.created < nextWeek(w))
    return sums.length ? { week: new Date(w), sure: (100 * sums.reduce((s, a) => s + a.confidence, 0)) / sums.length, right: (100 * sums.filter((a) => a.correct).length) / sums.length } : null
  }).filter((w) => w !== null)
  const chart = {
    height: 260,
    y: { label: '%', domain: [0, 100] as [number, number] },
    x: { label: '' },
    marks: [
      { type: 'line' as const, data: weeks.flatMap((w) => [{ week: w.week, value: w.sure, series: t('recap.sure') }, { week: w.week, value: w.right, series: t('recap.right') }]), x: 'week', y: 'value', stroke: 'series', strokeWidth: 2 },
      { type: 'dot' as const, data: weeks.flatMap((w) => [{ week: w.week, value: w.sure, series: t('recap.sure') }, { week: w.week, value: w.right, series: t('recap.right') }]), x: 'week', y: 'value', fill: 'series' },
    ],
  }

  return (
    <main className="recap">
      <header className="recap-hero">
        {story.course.cover && <img className="recap-cover" src={`/api/courses/${courseId}/cover`} alt={story.course.cover_alt ?? ''} />}
        <div className="recap-title">
          <div className="label">{t(story.preview ? 'recap.eyebrowPreview' : 'recap.eyebrow', { dates: range(story.started, story.finished) })}</div>
          <h1 dir="auto">{story.course.topic}</h1>
          <div className="recap-tiles">
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

      <Narration story={story} onRewrite={rewrite} language={language}>
        {narrative && <p className="recap-intro" dir="auto"><InlineMarkdown>{narrative.intro}</InlineMarkdown></p>}
      </Narration>

      <div className="recap-body">
        <aside className="recap-panel" aria-label={t('recap.panel')}>
          {graphShown && (
            <RecapGraph claims={story.claims} edges={story.edges} positions={story.positions} shown={shown} fresh={fresh} onLaidOut={saveLayout} onPick={setPicked} />
          )}
          <div className="recap-now">
            <span className="label">{reachedAt ? day(reachedAt) : t('recap.start')}</span>
            <div className="recap-counts">
              <span><strong>{number(story.before.length + reached.length)}</strong> {t('recap.countUnits')}</span>
              {stats.claims > 0 && <span><strong>{number(shown.size)}</strong> {t('recap.countClaims')}</span>}
              {stats.mistakes > 0 && (
                <span><strong>{number(story.mistakes.filter((m) => m.fixed && reachedAt && m.fixed <= nextDay(reachedAt)).length)}</strong> {t('recap.countFixed')}</span>
              )}
              <span><strong>{number(reached.reduce((s, x) => s + x.minutes, 0) / 60)}</strong> {t('recap.countHours')}</span>
            </div>
            {picked !== null && derived.claims.get(picked) && (
              <p className="small" dir="auto">
                <span className={`legend-dot state-${derived.claims.get(picked)!.state}`} />
                <InlineMarkdown>{derived.claims.get(picked)!.text}</InlineMarkdown>
              </p>
            )}
            <button type="button" className="btn recap-play" aria-pressed={playing} onClick={() => setPlaying((p) => !p)} title={t('recap.playHint')}>
              {playing ? t('recap.pause') : t('recap.play')}
            </button>
          </div>
          <ul className="recap-modules small">
            {story.modules.map((m) => (
              <li key={m} dir="auto">
                <i style={{ background: moduleColor(story.modules, m) }} /> {m}
              </li>
            ))}
          </ul>
        </aside>

        <div ref={timeline} className="recap-timeline">
          {story.before.length > 0 && (
            <details className="recap-before" data-step={-1}>
              <summary>
                <strong>{t('recap.before')}</strong> <span className="muted">{t('recap.beforeCount', { count: story.before.length })}</span>
              </summary>
              <ul>
                {story.before.map((u) => (
                  <li key={u.concept_id} dir="auto">{u.title}</li>
                ))}
              </ul>
            </details>
          )}
          {story.weeks.map((w) => (
            <section key={w} className="recap-week">
              <h2 className="label">{weekLabel(w)}</h2>
              {narrative?.weeks[w] && <p className="recap-caption" dir="auto"><InlineMarkdown>{narrative.weeks[w]}</InlineMarkdown></p>}
              <ol>
                {steps.map((s, n) => s.week === w && (
                  <li key={s.concept_id} data-step={n} className={n <= cursor ? 'recap-step reached' : 'recap-step'} style={{ '--module': moduleColor(story.modules, s.module) } as CSSProperties}>
                    <StepCard step={s} claims={derived.claims} mistakes={derived.mistakes} link={unitLink(s.concept_id)} />
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </div>
      </div>

      <section ref={end} className="recap-end">
        {answers.length >= CHART_FROM && (
          <div className="recap-sure">
            <h2>{t('recap.sureTitle')}</h2>
            <PlotBox spec={chart} alt={t('recap.chartAlt')} />
            <p className="small muted">
              {t('recap.brier', { start: brier(answers.slice(0, quarter)).toFixed(2), end: brier(answers.slice(-quarter)).toFixed(2) })}
            </p>
          </div>
        )}

        <div className="recap-weak">
          <h2>{t('recap.weakTitle')}</h2>
          {weak.length === 0 && open.length === 0 && <p className="muted">{t('recap.nothingWeak')}</p>}
          {weak.length > 0 && (
            <>
              <div className="label">{t('recap.weakClaims')}</div>
              <ul>
                {weak.map((c) => (
                  <li key={c.id} dir="auto">
                    <span className={`legend-dot state-${c.state}`} title={t(`graph.state.${c.state}`)} />
                    <a href={unitLink(conceptOfClaim(c))}><InlineMarkdown>{c.text}</InlineMarkdown></a>
                  </li>
                ))}
              </ul>
            </>
          )}
          {open.length > 0 && (
            <>
              <div className="label">{t('recap.openMistakes')}</div>
              <ul>
                {open.map((m) => (
                  <li key={m.id} dir="auto">
                    <Prompt text={m.prompt}>
                      <a className="small" href={unitLink(m.concept_id)}>{t('recap.openUnit')}</a>
                    </Prompt>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {narrative && (
          <div className="recap-letter">
            <h2>{t('recap.letterTitle')}</h2>
            <p dir="auto"><InlineMarkdown>{narrative.letter}</InlineMarkdown></p>
          </div>
        )}

        <div className="recap-next">
          <h2>{t('recap.nextTitle')}</h2>
          {nextUp.length > 0 && (
            <ul>
              {nextUp.map((s) => (
                <li key={s.id}>
                  <strong dir="auto">{s.title}</strong>
                  <span className="small muted" dir="auto">{s.pitch}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <a className="btn as-link" href="#/explore">{t('recap.explore')}</a>
            <a className="btn as-link" href={`/api/courses/${courseId}/book.pdf`}>{t('recap.book')}</a>
          </div>
        </div>
      </section>
    </main>
  )
}

function Narration({ story, onRewrite, language, children }: { story: Story; onRewrite: () => void; language: string; children: ReactNode }) {
  const { t, i18n } = useTranslation()
  if (story.preview) return <p className="muted small">{t('recap.previewNote')}</p>
  if (story.writing) return <p className="muted" role="status">{t('recap.writing')}</p>
  if (story.failed && !story.narrative)
    return (
      <p className="muted" role="status">
        {t('recap.failed')}{' '}
        <button type="button" className="btn" onClick={onRewrite}>{t('recap.tryAgain')}</button>
      </p>
    )
  return (
    <>
      {children}
      {story.narrative && story.narrative.locale !== i18n.language && (
        <button type="button" className="btn recap-rewrite" onClick={onRewrite}>
          {t('recap.rewrite', { language })}
        </button>
      )}
    </>
  )
}

function StepCard({ step, claims, mistakes, link }: { step: Step; claims: Map<number, Claim>; mistakes: Map<number, Mistake>; link: string }) {
  const { t } = useTranslation()
  const own = step.claims.map((id) => claims.get(id)!).filter(Boolean)
  const missed = step.mistakes.map((id) => mistakes.get(id)!).filter(Boolean)
  const fixed = missed.filter((m) => m.put_right).length
  const right = step.checks.filter((c) => c.correct).length
  const sure = step.checks.length ? step.checks.reduce((s, c) => s + c.confidence, 0) / step.checks.length : 0
  return (
    <details>
      <summary>
        <span className="recap-step-head">
          <strong dir="auto">{step.kind === 'practice' ? practiceTitle(step.title, t) : step.title}</strong>
          <span className="small muted">{day(step.finished)}</span>
        </span>
        {own.length > 0 && (
          <span className="recap-chips">
            {own.slice(0, 3).map((c) => (
              <span key={c.id} className={`recap-chip state-${c.state}`} dir="auto">
                {c.text}
              </span>
            ))}
            {own.length > 3 && <span className="small muted">{t('recap.moreClaims', { count: own.length - 3 })}</span>}
          </span>
        )}
        {(missed.length > 0 || step.milestone) && (
          <span className="recap-marks small">
            {missed.length > 0 && <span className="mark-missed">{t('recap.mistakes', { count: missed.length })}</span>}
            {fixed > 0 && <span className="mark-fixed">{t('recap.putRight', { count: fixed })}</span>}
            {step.milestone && (
              <span className="mark-project" title={step.milestone.deliverable}>
                {t('recap.project')}
              </span>
            )}
          </span>
        )}
      </summary>
      <div className="recap-step-body">
        {own.length > 0 && (
          <ul className="recap-claims">
            {own.map((c) => (
              <li key={c.id} dir="auto">
                <span className={`legend-dot state-${c.state}`} title={t(`graph.state.${c.state}`)} />
                <InlineMarkdown>{c.text}</InlineMarkdown>
              </li>
            ))}
          </ul>
        )}
        {missed.length > 0 && (
          <ul className="recap-mistakes">
            {missed.map((m) => (
              <li key={m.id} dir="auto">
                <Prompt text={m.prompt}>
                  <span className={m.put_right ? 'small mark-fixed' : 'small mark-missed'}>
                    {m.fixed ? t('recap.fixedOn', { date: day(m.fixed) }) : m.put_right ? t('recap.fixed') : t('recap.stillOpen')}
                  </span>
                </Prompt>
              </li>
            ))}
          </ul>
        )}
        {step.milestone && (
          <p className="small" dir="auto">
            <span className="mark-project">{t('recap.project')}</span> {step.milestone.project}: <code>{step.milestone.deliverable}</code>
          </p>
        )}
        <p className="small muted">
          {t(step.estimated ? 'recap.minutesAbout' : 'recap.minutes', { n: step.minutes })}
          {step.checks.length > 0 && ` · ${t('recap.checks', { right, total: step.checks.length, sure: percent(sure) })}`}
        </p>
        <a className="small" href={link}>{t('recap.openUnit')}</a>
      </div>
    </details>
  )
}

/** A mistake's question: its first paragraph, with the rest (tables, display math, the parts) folded under it. */
function Prompt({ text, children }: { text: string; children: ReactNode }) {
  const [lead, ...rest] = text.trim().split(/\n\s*\n/)
  if (lead.trimStart().startsWith('|') || lead.includes('$$'))
    return (
      <div className="recap-prompt">
        <Markdown>{text}</Markdown>
        {children}
      </div>
    )
  if (rest.length === 0)
    return (
      <div className="recap-prompt">
        <InlineMarkdown>{lead}</InlineMarkdown> {children}
      </div>
    )
  return (
    <details className="recap-prompt">
      <summary>
        <InlineMarkdown>{lead}</InlineMarkdown> {children}
      </summary>
      <Markdown>{rest.join('\n\n')}</Markdown>
    </details>
  )
}

function nextWeek(w: string): string {
  const d = new Date(`${w}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 7)
  return d.toISOString().slice(0, 10)
}

function nextDay(stamp: string): string {
  return `${stamp.slice(0, 10)} 23:59:59`
}
