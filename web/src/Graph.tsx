import { useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { CollectionReturnValue, Core, Position, StylesheetJson } from 'cytoscape'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { plain } from './plain'
import { useTheme } from './theme'
import { STATE_COLOR, loadCytoscape, token } from './claims'
import type { State } from './claims'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from 'cn'

const label = 'text-sm leading-snug font-medium text-ink-2'
const small = 'text-sm text-muted-foreground'
const row = 'flex flex-wrap items-center gap-2'
const LEGEND_DOT: Record<State, string> = { held: 'bg-primary', fading: 'bg-warm-line', shaky: 'bg-destructive', unseen: 'bg-off ring-1 ring-rule-strong ring-inset' }

type Source = { id: number; title: string; concept_id: number | null; course_id: number; topic: string }
type Evidence = { block_id: number; lesson_id: number; kind: string; markdown: string; verdict: 'held' | 'shaky' | null }
type Claim = { id: number; text: string; state: State; sources: Source[]; evidence: Evidence[] }
type Edge = { from_id: number; to_id: number; kind: 'follows' | 'supports' | 'contrasts' }
type Graph = { claims: Claim[]; edges: Edge[] }

const CARD_TEXT = 180
const CARD_PAD = 8
const FONT_SIZE = 11
const LINE_HEIGHT = 1.3
const MERGE_CHOICES = 8
const PADDING = 16
// the least zoom the graph opens at: the cards' text drawn at its own size, FONT_SIZE
const READABLE = 1

/** Fit the elements, but never so small the cards cannot be read: a bigger graph opens on its most connected claim,
 * with the claims it links to in view when they fit. */
function show(c: Core, eles: CollectionReturnValue) {
  c.fit(eles, PADDING)
  if (c.zoom() >= READABLE) return
  const claims = eles.nodes('[?claim]')
  const hub = claims.max((n) => n.degree(false)).ele
  const near = hub.closedNeighborhood()
  c.fit(near, PADDING)
  const fits = c.zoom() >= READABLE
  c.zoom(READABLE)
  c.center(fits ? near : hub)
}

/** The size of a card that holds the whole claim, wrapped the way cytoscape wraps a label: at spaces, within CARD_TEXT. */
function cardSize(ctx: CanvasRenderingContext2D, text: string): { w: number; h: number } {
  let lines = 1
  let line = ''
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word
    if (line && ctx.measureText(next).width > CARD_TEXT) {
      lines++
      line = word
    } else line = next
  }
  const w = Math.min(CARD_TEXT, ctx.measureText(text).width)
  return { w: w + 2 * CARD_PAD, h: lines * FONT_SIZE * LINE_HEIGHT + 2 * CARD_PAD }
}

/** The claims the chosen one rests on and those that rest on it; everything else is hidden and the chain laid out down to its foundations. */
function focus(c: Core, id: number | null, home: Map<string, Position>) {
  c.resize()
  c.elements().removeClass('away')
  const node = id === null ? c.collection() : c.getElementById(String(id))
  if (node.empty()) {
    if (home.size) c.nodes('[?claim]').positions((n) => home.get(n.id()) ?? n.position())
    home.clear()
    show(c, c.elements())
    return
  }
  if (!home.size) c.nodes('[?claim]').forEach((n) => void home.set(n.id(), { ...n.position() }))
  const nodes = node.union(node.predecessors()).union(node.successors()).union(node.neighborhood()).nodes()
  const keep = nodes.union(nodes.edgesWith(nodes)).union(nodes.parents())
  c.elements().not(keep).addClass('away')
  const roots = nodes.filter((n) => n.incomers('edge').intersection(keep).empty())
  keep
    .layout({
      name: 'breadthfirst',
      directed: true,
      roots: (roots.empty() ? node : roots).map((n) => n.id()),
      boundingBox: { x1: 0, y1: 0, w: c.width(), h: c.height() },
      nodeDimensionsIncludeLabels: true,
      spacingFactor: 1.1,
      padding: PADDING,
      animate: true,
      animationDuration: 250,
    })
    .run()
}

function graphElements(shown: { claims: Claim[]; edges: Edge[] }, courses: [number, string][], grouped: boolean, ctx: CanvasRenderingContext2D) {
  return [
    ...(grouped ? courses.map(([id, topic]) => ({ data: { id: `course-${id}`, label: topic } })) : []),
    ...shown.claims.map((c) => ({
      data: {
        id: String(c.id),
        label: c.text,
        ...cardSize(ctx, c.text),
        claim: true,
        color: token(STATE_COLOR[c.state]),
        ...(grouped && c.sources[0] ? { parent: `course-${c.sources[0].course_id}` } : {}),
      },
    })),
    ...shown.edges.map((e) => ({ data: { id: `${e.from_id}-${e.to_id}-${e.kind}`, source: String(e.from_id), target: String(e.to_id), kind: e.kind } })),
  ]
}

function graphStyle(font: string): StylesheetJson {
  const ink = token('--ink')
  return [
    {
      selector: 'node[?claim]',
      style: {
        shape: 'round-rectangle',
        width: 'data(w)',
        height: 'data(h)',
        'background-color': 'data(color)',
        'background-opacity': 0.16,
        // the card is solid, so links run under it rather than through its text
        'underlay-color': token('--panel'),
        'underlay-opacity': 1,
        'underlay-padding': 0,
        'underlay-shape': 'round-rectangle',
        'border-color': 'data(color)',
        'border-width': 2,
        label: 'data(label)',
        color: ink,
        'font-family': font,
        'font-size': FONT_SIZE,
        'line-height': LINE_HEIGHT,
        'min-zoomed-font-size': 7,
        'text-wrap': 'wrap',
        'text-max-width': `${CARD_TEXT}px`,
        'text-valign': 'center',
        'text-halign': 'center',
      },
    },
    {
      selector: ':parent',
      style: {
        label: 'data(label)',
        color: token('--muted'),
        'font-size': 12,
        'text-valign': 'top',
        'background-color': token('--panel'),
        'border-color': token('--line'),
        'border-width': 1,
      },
    },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': ink } },
    { selector: '.away', style: { display: 'none' } },
    { selector: 'edge', style: { width: 1.2, 'line-color': token('--line-strong'), 'target-arrow-color': token('--line-strong'), 'curve-style': 'bezier' } },
    { selector: 'edge[kind = "follows"]', style: { 'target-arrow-shape': 'triangle' } },
    { selector: 'edge[kind = "supports"]', style: { 'line-style': 'dashed', 'target-arrow-shape': 'triangle' } },
    { selector: 'edge[kind = "contrasts"]', style: { 'line-style': 'dotted', 'line-color': token('--danger') } },
  ]
}

/** The claims and links shown under the course filter, and the courses the claims come from. */
function useShownClaims(graph: Graph | null, filter: number | null) {
  const courses = useMemo(() => {
    const seen = new Map<number, string>()
    for (const c of graph?.claims ?? []) for (const s of c.sources) seen.set(s.course_id, s.topic)
    return [...seen.entries()]
  }, [graph])

  const shown = useMemo(() => {
    const claims = (graph?.claims ?? []).filter((c) => filter === null || c.sources.some((s) => s.course_id === filter))
    const ids = new Set(claims.map((c) => c.id))
    return { claims, edges: (graph?.edges ?? []).filter((e) => ids.has(e.from_id) && ids.has(e.to_id)) }
  }, [graph, filter])
  return { courses, shown }
}

/** The network drawn in the box, laid out again when what is shown or the theme changes; a tap selects a claim. */
function useClaimNetwork(
  box: RefObject<HTMLDivElement | null>,
  shown: { claims: Claim[]; edges: Edge[] },
  courses: [number, string][],
  filter: number | null,
  selected: number | null,
  setSelected: (id: number | null) => void,
) {
  const theme = useTheme()
  const [built, setBuilt] = useState(0)
  const cy = useRef<Core | null>(null)
  const home = useRef(new Map<string, Position>())

  useEffect(() => {
    if (!box.current || shown.claims.length === 0) return
    let gone = false
    const font = getComputedStyle(document.body).fontFamily
    // every subset of the font the cards' letters need, so a card is sized and wrapped in the font it is drawn in;
    // a font that fails to load costs only that, never the drawing
    const letters = document.fonts.load(`${FONT_SIZE}px ${font}`, shown.claims.map((c) => c.text).join(' '))
    Promise.all([loadCytoscape(), letters.catch(() => undefined)]).then(([cytoscape]) => {
      if (gone || !box.current) return
      const grouped = filter === null && courses.length > 1
      const ctx = document.createElement('canvas').getContext('2d')!
      ctx.font = `${FONT_SIZE}px ${font}`
      cy.current = cytoscape({
        container: box.current,
        elements: graphElements(shown, courses, grouped, ctx),
        style: graphStyle(font),
        layout: { name: 'fcose', quality: 'proof', animate: false, packComponents: false, nodeRepulsion: () => 20000, idealEdgeLength: () => 120, padding: PADDING } as cytoscape.LayoutOptions,
      })
      show(cy.current, cy.current.elements())
      home.current.clear()
      cy.current.on('tap', 'node[?claim]', (e) => setSelected(Number(e.target.id())))
      cy.current.on('tap', (e) => e.target === cy.current && setSelected(null))
      fit.observe(box.current)
      setBuilt((n) => n + 1)
    })
    // the layout runs against the box as first measured; a box that settles or changes size afterwards gets the graph refitted
    const fit = new ResizeObserver(() => {
      cy.current?.resize()
      if (cy.current) show(cy.current, cy.current.elements(':visible'))
    })
    return () => {
      fit.disconnect()
      gone = true
      cy.current?.destroy()
      cy.current = null
    }
  }, [box, shown, courses, filter, theme, setSelected])

  useEffect(() => {
    if (cy.current) focus(cy.current, selected, home.current)
  }, [selected, built])
}

/** The learner's claims from every course as a network: coloured by where they stand, linked by how they follow. */
export function GraphPage({ profile, course }: { profile: number; course: number | null }) {
  const { t } = useTranslation()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [filter, setFilter] = useState<number | null>(course)
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState('')
  const box = useRef<HTMLDivElement>(null)

  const reload = () => api<Graph>(`/api/claims?profile=${profile}`)

  useEffect(() => {
    reload().then(setGraph, (e: Error) => setError(e.message))
  }, [profile]) // eslint-disable-line react-hooks/exhaustive-deps

  const { courses, shown } = useShownClaims(graph, filter)
  useClaimNetwork(box, shown, courses, filter, selected, setSelected)

  function apply(next: Promise<Graph>) {
    next.then(
      (g) => {
        setGraph(g)
        setError('')
      },
      (e: Error) => setError(e.message),
    )
  }

  const claim = graph?.claims.find((c) => c.id === selected) ?? null

  return (
    <main className="mx-auto flex w-full flex-col gap-4 px-6 pt-10 pb-16">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="m-0 grow text-[length:var(--text-display)] font-semibold">{t('graph.heading', { n: graph?.claims.length ?? 0 })}</h1>
        {courses.length > 1 && (
          <select className="h-11 max-w-full min-w-0 rounded-md border border-input bg-card px-4 font-medium text-ellipsis hover:border-foreground" aria-label={t('graph.course')} value={filter ?? ''} onChange={(e) => setFilter(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t('graph.allCourses')}</option>
            {courses.map(([id, topic]) => (
              <option key={id} value={id}>
                {topic}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div>}
      {graph && shown.claims.length === 0 && <div className="text-muted-foreground">{t('graph.empty')}</div>}
      <div className="my-2 flex flex-wrap gap-3 text-sm text-muted-foreground">
        {(Object.keys(STATE_COLOR) as State[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1">
            <span className={cn('inline-block size-[0.7rem] rounded-full', LEGEND_DOT[s])} />
            {t(`graph.state.${s}`)}
          </span>
        ))}
        <span>{t('graph.edges')}</span>
      </div>
      <div className={cn('grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]', !claim && 'md:grid-cols-1')}>
        <div ref={box} className="h-[55dvh] min-h-96 rounded-lg border border-border bg-card md:h-[calc(100dvh-var(--bar-height)-14rem)]" role="img" aria-label={t('graph.canvas')} />
        {claim && <ClaimPanel key={claim.id} claim={claim} all={graph!.claims} reload={reload} onChange={apply} onClose={() => setSelected(null)} />}
      </div>
    </main>
  )
}

function ClaimPanel(props: { claim: Claim; all: Claim[]; reload: () => Promise<Graph>; onChange: (next: Promise<Graph>) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const { claim } = props
  const [text, setText] = useState(claim.text)
  const [confirming, setConfirming] = useState(false)
  const [find, setFind] = useState('')
  const choices = find.trim()
    ? props.all.filter((c) => c.id !== claim.id && c.text.toLowerCase().includes(find.trim().toLowerCase())).slice(0, MERGE_CHOICES)
    : []

  return (
    <aside className="grid gap-2 rounded-lg border border-primary bg-card p-6 [&_ul]:m-0 [&_ul]:ps-4">
      <div className={row}>
        <span className={cn(label, 'grow')}>{t(`graph.state.${claim.state}`)}</span>
        <Button type="button" variant="ghost" className={'text-ink-2'} onClick={props.onClose}>
          {t('graph.close')}
        </Button>
      </div>
      <Textarea dir="auto" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className={row}>
        <Button
          type="button"
          variant="outline"
          disabled={!text.trim() || text.trim() === claim.text}
          onClick={() => props.onChange(api(`/api/claims/${claim.id}`, { text }).then(props.reload))}
        >
          {t('graph.reword')}
        </Button>
        {confirming ? (
          <Button type="button" variant="destructive" onClick={() => props.onChange(api(`/api/claims/${claim.id}`, { wrong: true }).then(props.reload))}>
            {t('graph.wrongConfirm')}
          </Button>
        ) : (
          <Button type="button" variant="ghost" className={'text-ink-2'} onClick={() => setConfirming(true)}>
            {t('graph.wrong')}
          </Button>
        )}
      </div>
      <div className={small}>{t('graph.from')}</div>
      <ul className={small}>
        {claim.sources.map((s) => (
          <li key={s.id}>
            <a href={s.concept_id ? `#/course/${s.course_id}?concept=${s.concept_id}` : `#/course/${s.course_id}`}>{s.topic}</a>: <span dir="auto">{s.title}</span>
          </li>
        ))}
      </ul>
      {claim.evidence.length > 0 && (
        <>
          <div className={small}>{t('graph.evidence')}</div>
          <ul className={small}>
            {claim.evidence.map((e) => (
              <li key={e.block_id} dir="auto">
                {e.verdict ? t(`graph.verdict.${e.verdict}`) : t('graph.verdict.open')}: {plain(e.markdown)}
              </li>
            ))}
          </ul>
        </>
      )}
      <label className={small} htmlFor="merge">
        {t('graph.mergeInto')}
      </label>
      <Input id="merge" dir="auto" value={find} onChange={(e) => setFind(e.target.value)} placeholder={t('graph.mergeFind')} />
      {choices.map((c) => (
        <Button key={c.id} type="button" variant="ghost" className="h-auto min-h-11 justify-start py-2 text-start font-medium whitespace-normal text-ink-2" dir="auto" onClick={() => props.onChange(api(`/api/claims/${claim.id}/merge`, { into: c.id }))}>
          {c.text}
        </Button>
      ))}
    </aside>
  )
}
