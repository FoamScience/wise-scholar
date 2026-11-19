import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from 'cn'
import { sketch } from './sketch'
import { Board } from './Board'
import { partBoxes, show, type BoardStep, type PartBox } from './board'
import { InlineMarkdown } from './Md'

export type Credit = { name: string; author: string; licence: string; pack: string; url: string }
export type FigureData = {
  svg: string
  alt: string
  credits?: Credit[]
  diagram?: { domain: string; substance?: string; stages?: string[] }
  crafted?: { script: string }
  frames?: string[]
  // answer: where the steps drawn in answer to the learner's last question begin
  board?: { steps: BoardStep[]; answer?: number }
  teaches?: Teaches
  previous?: FigureData & { caption: string }
  restored?: boolean
}
export type Teaches = { claim: string; notice: string; misconception: string; limits: string }

/** Where a figure or plot stops matching the real thing, as the tutor stated it. */
export function Limits({ teaches }: { teaches?: Teaches }) {
  const { t } = useTranslation()
  if (!teaches?.limits) return null
  return (
    <div className="text-sm text-muted-foreground" dir="auto">
      <InlineMarkdown>{t('block.limits', { limits: teaches.limits })}</InlineMarkdown>
    </div>
  )
}

/** The attribution a figure owes the art pack: every icon with its author and licence, and the pack it came from. */
export function Credits({ credits }: { credits?: Credit[] }) {
  const { t } = useTranslation()
  if (!credits?.length) return null
  const packs = [...new Map(credits.map((c) => [c.pack, c.url]))]
  return (
    <div className="text-xs text-muted-foreground">
      {t('block.art')} {credits.map((c) => `${c.name} (${c.author}, ${c.licence})`).join(', ')}
      {'; '}
      {packs.map(([pack, url]) => (
        <a key={pack} href={url} target="_blank" rel="noreferrer">
          {pack}
        </a>
      ))}
    </div>
  )
}

/** The SVG inline, so its text follows the theme; sketched in place when the profile asks for it. A board shows as
 * it stands after its last step. */
export function Drawing({ svg, alt, sketched, board, className }: { svg: string; alt: string; sketched: boolean; board?: BoardStep[]; className?: string }) {
  const box = useRef<HTMLDivElement>(null)
  // by content: a lesson refetched hands over equal steps in a new array, and redrawing would cut a playing board
  const steps = JSON.stringify(board ?? null)
  useEffect(() => {
    const el = box.current!
    el.innerHTML = svg
    if (sketched && el.querySelector('svg')) {
      try {
        sketch(el.querySelector('svg')!)
      } catch {
        el.innerHTML = svg // a shape rough.js cannot redraw: the figure is shown as drawn
      }
    }
    const drawing = el.querySelector('svg')
    if (board && drawing) show(drawing, board, board.length)
  }, [svg, sketched, steps]) // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={box} dir="ltr" className={className} role="img" aria-label={alt} />
}

/** Buttons to hold an animation at one of its stages, or let it play; the stage times come from the SVG itself. */
function Stages({ box, count }: { box: React.RefObject<HTMLDivElement | null>; count: number }) {
  const { t } = useTranslation()
  const [held, setHeld] = useState<number | null>(null)
  useEffect(() => {
    // Those who asked for less motion get the first stage, still; the buttons step through the rest.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) hold(0)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  function hold(stage: number | null) {
    const svg = box.current?.querySelector('svg')
    if (!svg) return
    const seconds = Number(svg.getAttribute('data-seconds')) || 3 * count
    if (stage === null) svg.unpauseAnimations()
    else {
      svg.pauseAnimations()
      svg.setCurrentTime((stage / count) * seconds + 0.01)
    }
    setHeld(stage)
  }
  return (
    <div className="flex flex-wrap gap-2">
      {Array.from({ length: count }, (_, i) => (
        <Button key={i} variant={held === i ? 'default' : 'outline'} size="sm" onClick={() => hold(i)}>
          {t('block.stage', { n: i + 1 })}
        </Button>
      ))}
      <Button variant={held === null ? 'default' : 'outline'} size="sm" onClick={() => hold(null)}>
        {t('block.play')}
      </Button>
    </div>
  )
}

/** "Redraw", then the learner's notes on what to change. */
function Redraw(props: { disabled?: boolean; onRedraw: (notes: string) => void }) {
  const { t } = useTranslation()
  const [notes, setNotes] = useState<string | null>(null)
  if (notes === null) {
    return (
      <Button variant="ghost" size="sm" className="-ms-3 self-start text-muted-foreground" disabled={props.disabled} onClick={() => setNotes('')}>
        {t('block.redraw')}
      </Button>
    )
  }
  return (
    <form
      className="grid gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        props.onRedraw(notes)
        setNotes(null)
      }}
    >
      <Input
        dir="auto"
        maxLength={1000}
        aria-label={t('block.redrawNotes')}
        placeholder={t('block.redrawNotes')}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && setNotes(null)}
        autoFocus
      />
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={props.disabled}>
          {t('block.redrawGo')}
        </Button>
        <Button variant="outline" size="sm" onClick={() => setNotes(null)}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  )
}

type Asked = (part: string, question: string, parts: PartBox[]) => void

/** "Ask about a part", then a click on the part, then the question; the tutor answers by drawing on the figure. */
function AskPart(props: { picked: { id: string; label: string } | null; picking: boolean; disabled?: boolean; onPick: (on: boolean) => void; onAsk: (question: string) => void }) {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')
  if (props.picked) {
    return (
      <form
        className="grid gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!question.trim()) return
          props.onAsk(question)
          setQuestion('')
        }}
      >
        <Input
          dir="auto"
          maxLength={1000}
          aria-label={t('board.askAbout', { part: props.picked.label })}
          placeholder={t('board.askAbout', { part: props.picked.label })}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Escape' && props.onPick(false)}
          autoFocus
        />
        <div className="flex gap-2">
          <Button type="submit" size="sm" disabled={props.disabled || !question.trim()}>{t('board.ask')}</Button>
          <Button variant="outline" size="sm" onClick={() => props.onPick(false)}>{t('common.cancel')}</Button>
        </div>
      </form>
    )
  }
  if (props.picking) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span aria-live="polite">{t('board.pickPart')}</span>
        <Button variant="outline" size="sm" onClick={() => props.onPick(false)}>{t('common.cancel')}</Button>
      </div>
    )
  }
  return (
    <Button variant="ghost" size="sm" className="-ms-3 self-start text-muted-foreground" disabled={props.disabled} onClick={() => props.onPick(true)}>
      {t('board.askPart')}
    </Button>
  )
}

/** A tutor-drawn figure; click to see it large. Steps the tutor just drew in answer to a question play at once. */
export function FigureCard(props: { id: number; caption: string; data: unknown; sketched: boolean; disabled?: boolean; onRestore?: () => void; onRedraw?: (notes: string) => void; onAsk?: Asked }) {
  const { t } = useTranslation()
  const d = props.data as FigureData
  const [large, setLarge] = useState(false)
  const [picking, setPicking] = useState(false)
  const [picked, setPicked] = useState<{ id: string; label: string } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const sketched = props.sketched && !d.diagram && !d.crafted
  // steps added while the figure is on screen are an answer just drawn: they play once, from where it begins
  const count = d.board?.steps.length ?? 0
  const [seen, setSeen] = useState(count)
  const [answered, setAnswered] = useState<number | undefined>()
  if (count !== seen) {
    setSeen(count)
    setAnswered(count > seen ? d.board?.answer : undefined)
  }
  const askable = props.onAsk && !d.frames && d.svg.includes('data-part=')

  function pick(e: React.MouseEvent) {
    if (!picking) return
    e.preventDefault()
    e.stopPropagation()
    const part = (e.target as Element).closest('[data-part]')
    if (!part) return
    const id = part.getAttribute('data-part')!
    const label = [...part.querySelectorAll('text')].map((x) => x.textContent?.trim()).filter(Boolean).join(' ').slice(0, 40)
    setPicked({ id, label: label || id })
    setPicking(false)
  }

  function ask(question: string) {
    const svg = box.current?.querySelector('svg')
    if (!svg || !picked) return
    props.onAsk!(picked.id, question, partBoxes(svg))
    setPicked(null)
  }

  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.figure')}</div>
      <button
        type="button"
        className={cn('figure-box mx-auto block w-full break-inside-avoid text-start', large ? 'max-w-full cursor-zoom-out' : 'max-w-[600px] cursor-zoom-in')}
        aria-label={large ? t('block.shrinkFigure') : t('block.enlargeFigure', { alt: d.alt })}
        onClick={() => setLarge(!large)}
        onClickCapture={pick}
      >
        <div ref={box} className={cn(picking && 'cursor-pointer')}>
          <Drawing svg={d.svg} alt={d.alt} sketched={sketched} board={d.board?.steps} />
        </div>
      </button>
      {d.frames && d.frames.length > 1 && <Stages key={d.svg} box={box} count={d.frames.length} />}
      {d.board && <Board key={`${sketched}${JSON.stringify(d.board)}${d.svg}`} box={box} steps={d.board.steps} from={answered} />}
      {askable && (
        <AskPart
          picked={picked}
          picking={picking}
          disabled={props.disabled}
          onPick={(on) => {
            setPicking(on)
            setPicked(null)
          }}
          onAsk={ask}
        />
      )}
      {props.caption && <div className="text-sm text-muted-foreground"><InlineMarkdown>{props.caption}</InlineMarkdown></div>}
      <Limits teaches={d.teaches} />
      <Credits credits={d.credits} />
      {props.onRedraw && <Redraw disabled={props.disabled} onRedraw={props.onRedraw} />}
      {d.previous && props.onRestore && (
        <Button variant="ghost" size="sm" className="-ms-3 self-start text-muted-foreground" disabled={props.disabled} onClick={props.onRestore}>
          {d.restored ? t('block.backToRedrawn') : t('block.restoreDrawing')}
        </Button>
      )}
    </section>
  )
}
