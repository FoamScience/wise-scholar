import { useEffect, useMemo, useRef, useState } from 'react'
import type { Core } from 'cytoscape'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { useTheme } from './theme'

type State = 'held' | 'fading' | 'shaky' | 'unseen'
type Source = { id: number; title: string; concept_id: number | null; course_id: number; topic: string }
type Evidence = { block_id: number; lesson_id: number; kind: string; markdown: string; verdict: 'held' | 'shaky' | null }
type Claim = { id: number; text: string; state: State; sources: Source[]; evidence: Evidence[] }
type Edge = { from_id: number; to_id: number; kind: 'follows' | 'supports' | 'contrasts' }
type Graph = { claims: Claim[]; edges: Edge[] }

const STATE_COLOR: Record<State, string> = { held: '--teal', fading: '--amber-line', shaky: '--danger', unseen: '--mastery-off' }
const LABEL_CHARS = 70
const MERGE_CHOICES = 8

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** A card's opening words without the Markdown marks, for a one-line mention. */
function plain(markdown: string): string {
  return markdown.replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim()
}

function short(text: string): string {
  return text.length <= LABEL_CHARS ? text : `${text.slice(0, LABEL_CHARS - 1)}…`
}

/** The learner's claims from every course as a network: coloured by where they stand, linked by how they follow. */
export function GraphPage({ profile, course }: { profile: number; course: number | null }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [filter, setFilter] = useState<number | null>(course)
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)

  const reload = () => api<Graph>(`/api/claims?profile=${profile}`)

  useEffect(() => {
    reload().then(setGraph, (e: Error) => setError(e.message))
  }, [profile]) // eslint-disable-line react-hooks/exhaustive-deps

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

  useEffect(() => {
    if (!box.current || shown.claims.length === 0) return
    let gone = false
    import('cytoscape').then(({ default: cytoscape }) => {
      if (gone || !box.current) return
      const ink = token('--ink')
      const grouped = filter === null && courses.length > 1
      cy.current = cytoscape({
        container: box.current,
        elements: [
          ...(grouped ? courses.map(([id, topic]) => ({ data: { id: `course-${id}`, label: topic } })) : []),
          ...shown.claims.map((c) => ({
            data: {
              id: String(c.id),
              label: short(c.text),
              claim: true,
              color: token(STATE_COLOR[c.state]),
              ...(grouped && c.sources[0] ? { parent: `course-${c.sources[0].course_id}` } : {}),
            },
          })),
          ...shown.edges.map((e) => ({ data: { id: `${e.from_id}-${e.to_id}-${e.kind}`, source: String(e.from_id), target: String(e.to_id), kind: e.kind } })),
        ],
        style: [
          {
            selector: 'node[?claim]',
            style: {
              'background-color': 'data(color)',
              label: 'data(label)',
              color: ink,
              'font-size': 11,
              'min-zoomed-font-size': 7,
              'text-wrap': 'wrap',
              'text-max-width': '120px',
              'text-valign': 'bottom',
              'text-margin-y': 4,
              width: 18,
              height: 18,
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
          { selector: 'edge', style: { width: 1.2, 'line-color': token('--line-strong'), 'target-arrow-color': token('--line-strong'), 'curve-style': 'bezier' } },
          { selector: 'edge[kind = "follows"]', style: { 'target-arrow-shape': 'triangle' } },
          { selector: 'edge[kind = "supports"]', style: { 'line-style': 'dashed', 'target-arrow-shape': 'triangle' } },
          { selector: 'edge[kind = "contrasts"]', style: { 'line-style': 'dotted', 'line-color': token('--danger') } },
        ],
        layout: { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true, componentSpacing: 30, padding: 16 },
      })
      cy.current.on('tap', 'node[?claim]', (e) => setSelected(Number(e.target.id())))
      cy.current.on('tap', (e) => e.target === cy.current && setSelected(null))
      fit.observe(box.current)
    })
    // the layout runs against the box as first measured; a box that settles or changes size afterwards gets the graph refitted
    const fit = new ResizeObserver(() => {
      cy.current?.resize()
      cy.current?.fit(undefined, 16)
    })
    return () => {
      fit.disconnect()
      gone = true
      cy.current?.destroy()
      cy.current = null
    }
  }, [shown, courses, filter, theme])

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
    <main className="home graph-page">
      <div className="row">
        <h1 className="grow">{t('graph.heading', { n: graph?.claims.length ?? 0 })}</h1>
        {courses.length > 1 && (
          <select className="btn" aria-label={t('graph.course')} value={filter ?? ''} onChange={(e) => setFilter(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t('graph.allCourses')}</option>
            {courses.map(([id, topic]) => (
              <option key={id} value={id}>
                {topic}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {graph && shown.claims.length === 0 && <div className="muted">{t('graph.empty')}</div>}
      <div className="graph-legend small">
        {(Object.keys(STATE_COLOR) as State[]).map((s) => (
          <span key={s} className={`legend-dot state-${s}`}>
            {t(`graph.state.${s}`)}
          </span>
        ))}
        <span>{t('graph.edges')}</span>
      </div>
      <div className="graph-layout">
        <div ref={box} className="graph-canvas" role="img" aria-label={t('graph.canvas')} />
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
    <aside className="block claim-panel">
      <div className="row">
        <span className="label grow">{t(`graph.state.${claim.state}`)}</span>
        <button type="button" className="link" onClick={props.onClose}>
          {t('graph.close')}
        </button>
      </div>
      <textarea className="field" dir="auto" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <button
          type="button"
          className="btn"
          disabled={!text.trim() || text.trim() === claim.text}
          onClick={() => props.onChange(api(`/api/claims/${claim.id}`, { text }).then(props.reload))}
        >
          {t('graph.reword')}
        </button>
        {confirming ? (
          <button type="button" className="btn danger" onClick={() => props.onChange(api(`/api/claims/${claim.id}`, { wrong: true }).then(props.reload))}>
            {t('graph.wrongConfirm')}
          </button>
        ) : (
          <button type="button" className="link" onClick={() => setConfirming(true)}>
            {t('graph.wrong')}
          </button>
        )}
      </div>
      <div className="small">{t('graph.from')}</div>
      <ul className="small">
        {claim.sources.map((s) => (
          <li key={s.id}>
            <a href={s.concept_id ? `#/course/${s.course_id}?concept=${s.concept_id}` : `#/course/${s.course_id}`}>{s.topic}</a>: <span dir="auto">{s.title}</span>
          </li>
        ))}
      </ul>
      {claim.evidence.length > 0 && (
        <>
          <div className="small">{t('graph.evidence')}</div>
          <ul className="small">
            {claim.evidence.map((e) => (
              <li key={e.block_id} dir="auto">
                {e.verdict ? t(`graph.verdict.${e.verdict}`) : t('graph.verdict.open')}: {plain(e.markdown)}
              </li>
            ))}
          </ul>
        </>
      )}
      <label className="small" htmlFor="merge">
        {t('graph.mergeInto')}
      </label>
      <input id="merge" className="field" dir="auto" value={find} onChange={(e) => setFind(e.target.value)} placeholder={t('graph.mergeFind')} />
      {choices.map((c) => (
        <button key={c.id} type="button" className="link merge-choice" dir="auto" onClick={() => props.onChange(api(`/api/claims/${claim.id}/merge`, { into: c.id }))}>
          {c.text}
        </button>
      ))}
    </aside>
  )
}
