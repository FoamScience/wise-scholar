import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Cancelled, play, show, type BoardStep, type Run } from './board'

// A step's sentence stays this long per character before the next step, and no less than the floor.
const READ_MS_PER_CHAR = 55
const READ_MS_FLOOR = 1500
const PAUSE_MS = 500

const still = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

function wait(ms: number, run: Run): Promise<void> {
  return new Promise((done, fail) => setTimeout(() => (run.cancelled ? fail(new Cancelled()) : done()), ms))
}

/** A figure played as a whiteboard: each step drawn under its sentence, held long enough to read it.
 * from: a step to play on mount, onward to the end (the steps just added in answer to the learner). */
export function Board(props: { box: React.RefObject<HTMLDivElement | null>; steps: BoardStep[]; from?: number }) {
  const { steps } = props
  const { t } = useTranslation()
  const [at, setAt] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const run = useRef<Run | null>(null)

  useEffect(() => {
    if (props.from !== undefined) go(props.from, true)
    return cancel
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const drawing = () => props.box.current?.querySelector('svg') ?? null

  function cancel() {
    if (run.current) run.current.cancelled = true
    run.current = null
  }

  function read(text: string, mine: Run): Promise<void> {
    return wait(Math.max(READ_MS_FLOOR, text.length * READ_MS_PER_CHAR), mine)
  }

  async function go(first: number, onward: boolean) {
    const svg = drawing()
    if (!svg) return
    cancel()
    const mine: Run = { cancelled: false }
    run.current = mine
    show(svg, steps, first)
    setPlaying(onward)
    try {
      for (let n = first; n < (onward ? steps.length : first + 1); n++) {
        setAt(n)
        await Promise.all([play(svg, steps, n, mine, still()), read(steps[n].say, mine)])
        if (onward && n + 1 < steps.length) await wait(PAUSE_MS, mine)
      }
    } catch (e) {
      if (e instanceof Cancelled) return
      throw e
    }
    run.current = null
    setPlaying(false)
  }

  function pause() {
    cancel()
    setPlaying(false)
    const svg = drawing()
    if (svg && at !== null) show(svg, steps, at + 1)
  }

  function whole() {
    cancel()
    setPlaying(false)
    setAt(null)
    const svg = drawing()
    if (svg) show(svg, steps, steps.length)
  }

  const last = steps.length - 1
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {playing ? (
          <Button size="sm" onClick={pause}>{t('board.pause')}</Button>
        ) : (
          <Button size="sm" onClick={() => go(at === null || at === last ? 0 : at + 1, true)}>
            {at === null ? t('board.play') : at === last ? t('board.again') : t('board.resume')}
          </Button>
        )}
        <Button variant="outline" size="sm" disabled={!at} onClick={() => go(at! - 1, false)}>{t('board.back')}</Button>
        <Button variant="outline" size="sm" disabled={at === last} onClick={() => go(at === null ? 0 : at + 1, false)}>{t('board.next')}</Button>
        <span className="text-sm text-muted-foreground tabular-nums">
          {at === null ? t('board.steps', { count: steps.length }) : t('board.at', { n: at + 1, count: steps.length })}
        </span>
        {at !== null && <Button variant="ghost" size="sm" onClick={whole}>{t('board.whole')}</Button>}
      </div>
      {at !== null && <p className="m-0" dir="auto" aria-live="polite">{steps[at].say}</p>}
    </div>
  )
}

/** A board's steps in order, for the page that cannot play it: the book, a print. */
export function BoardSteps({ steps }: { steps: BoardStep[] }) {
  const { t } = useTranslation()
  return (
    <div className="text-sm">
      <div className="font-medium text-ink-2">{t('board.onTheBoard')}</div>
      <ol className="m-0 ps-5">
        {steps.map((s, n) => (
          <li key={n} dir="auto">{s.say}</li>
        ))}
      </ol>
    </div>
  )
}
