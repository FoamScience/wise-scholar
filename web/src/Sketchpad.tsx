import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getStroke } from 'perfect-freehand'
import { Button } from '@/components/ui/button'
import Markdown from './Md'

type Point = [number, number, number]
type Stroke = { points: Point[]; pen: boolean; erase: boolean }
type Page = Stroke[]

const INK = '#1a1f1e'
const SIZE = 3.2
const ERASER = 22

// pages written on a card stay while the app is open, so closing the pad to read the card loses nothing
const drafts = new Map<number, Page[]>()

function outline(stroke: Stroke): Path2D {
  const shape = getStroke(stroke.points, {
    size: stroke.erase ? ERASER : SIZE,
    thinning: stroke.pen ? 0.6 : 0.2,
    simulatePressure: !stroke.pen,
    last: true,
  })
  const path = new Path2D()
  shape.forEach(([x, y], i) => (i === 0 ? path.moveTo(x, y) : path.lineTo(x, y)))
  path.closePath()
  return path
}

function paint(context: CanvasRenderingContext2D, page: Page) {
  for (const stroke of page) {
    context.globalCompositeOperation = stroke.erase ? 'destination-out' : 'source-over'
    context.fill(outline(stroke))
  }
  context.globalCompositeOperation = 'source-over'
}

/** A whole-screen page to write the answer on with a stylus or a finger; each page goes to the card as a picture. */
export function Sketchpad(props: { blockId: number; task: string; onSend: (pages: File[]) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const canvas = useRef<HTMLCanvasElement>(null)
  const [pages, setPages] = useState<Page[]>(() => drafts.get(props.blockId) ?? [[]])
  const [at, setAt] = useState(pages.length - 1)
  const [erasing, setErasing] = useState(false)
  const [taskOpen, setTaskOpen] = useState(false)
  const drawing = useRef<Stroke | null>(null)
  // once a pen has touched the page, a resting palm or finger no longer draws
  const penSeen = useRef(false)

  useEffect(() => {
    drafts.set(props.blockId, pages)
  }, [props.blockId, pages])

  function redraw() {
    const c = canvas.current
    if (!c) return
    const context = c.getContext('2d')!
    context.setTransform(1, 0, 0, 1, 0, 0)
    context.clearRect(0, 0, c.width, c.height)
    context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    context.fillStyle = INK
    paint(context, drawing.current ? [...pages[at], drawing.current] : pages[at])
  }

  useEffect(() => {
    const fit = () => {
      const c = canvas.current
      if (!c) return
      c.width = c.clientWidth * devicePixelRatio
      c.height = c.clientHeight * devicePixelRatio
      redraw()
    }
    fit()
    addEventListener('resize', fit)
    return () => removeEventListener('resize', fit)
  })

  function point(e: PointerEvent | React.PointerEvent): Point {
    const box = canvas.current!.getBoundingClientRect()
    return [e.clientX - box.left, e.clientY - box.top, e.pressure || 0.5]
  }

  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    if (e.pointerType === 'pen') penSeen.current = true
    else if (e.pointerType === 'touch' && penSeen.current) return
    e.currentTarget.setPointerCapture(e.pointerId)
    // a pen's eraser end or its barrel button erases too
    const erase = erasing || (e.buttons & 32) !== 0
    drawing.current = { points: [point(e)], pen: e.pointerType === 'pen', erase }
    redraw()
  }

  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return
    for (const each of e.nativeEvent.getCoalescedEvents?.() ?? [e.nativeEvent]) drawing.current.points.push(point(each))
    redraw()
  }

  function up() {
    const stroke = drawing.current
    drawing.current = null
    if (stroke) setPages((all) => all.map((page, i) => (i === at ? [...page, stroke] : page)))
  }

  function render(page: Page): Promise<File> {
    const c = canvas.current!
    const out = document.createElement('canvas')
    out.width = c.width
    out.height = c.height
    const context = out.getContext('2d')!
    context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    // strokes go on their own layer first, so the eraser takes ink and leaves the paper white
    const ink = document.createElement('canvas')
    ink.width = c.width
    ink.height = c.height
    const inkContext = ink.getContext('2d')!
    inkContext.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    inkContext.fillStyle = INK
    paint(inkContext, page)
    context.fillStyle = '#fff'
    context.fillRect(0, 0, c.clientWidth, c.clientHeight)
    context.setTransform(1, 0, 0, 1, 0, 0)
    context.drawImage(ink, 0, 0)
    return new Promise((done) => out.toBlob((blob) => done(new File([blob!], 'page.png', { type: 'image/png' })), 'image/png'))
  }

  const written = pages.filter((p) => p.some((s) => !s.erase))

  return (
    <div className="fixed inset-0 z-50 bg-white" role="dialog" aria-modal="true" aria-label={t('pad.label')}>
      <canvas ref={canvas} className="absolute inset-0 size-full cursor-crosshair touch-none" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
      <div className="absolute inset-x-2 top-2 flex flex-wrap items-center gap-1 rounded-lg border border-border bg-card p-1 text-foreground shadow-float" role="toolbar" aria-label={t('pad.tools')}>
        <Button variant="outline" className="aria-expanded:border-primary aria-expanded:bg-accent" aria-expanded={taskOpen} onClick={() => setTaskOpen((o) => !o)}>
          {t('pad.task')}
        </Button>
        <Button variant="outline" className="aria-pressed:border-primary aria-pressed:bg-accent" aria-pressed={!erasing} onClick={() => setErasing(false)}>
          {t('pad.pen')}
        </Button>
        <Button variant="outline" className="aria-pressed:border-primary aria-pressed:bg-accent" aria-pressed={erasing} onClick={() => setErasing(true)}>
          {t('pad.eraser')}
        </Button>
        <Button
          variant="outline"
          disabled={pages[at].length === 0}
          onClick={() => setPages((all) => all.map((page, i) => (i === at ? page.slice(0, -1) : page)))}
        >
          {t('pad.undo')}
        </Button>
        <Button variant="outline" disabled={pages[at].length === 0} onClick={() => setPages((all) => all.map((page, i) => (i === at ? [] : page)))}>
          {t('pad.clear')}
        </Button>
        <span className="inline-flex items-center gap-1">
          <Button variant="outline" size="icon" disabled={at === 0} aria-label={t('pad.previous')} onClick={() => setAt(at - 1)}>
            ‹
          </Button>
          <span className="text-sm text-muted-foreground">{t('pad.page', { n: at + 1, total: pages.length })}</span>
          <Button
            variant="outline"
            size="icon"
            aria-label={at === pages.length - 1 ? t('pad.newPage') : t('pad.next')}
            onClick={() => {
              if (at === pages.length - 1) setPages((all) => [...all, []])
              setAt(at + 1)
            }}
          >
            {at === pages.length - 1 ? '+' : '›'}
          </Button>
        </span>
        <span className="grow" />
        <Button variant="outline" onClick={props.onClose}>
          {t('pad.close')}
        </Button>
        <Button
          disabled={written.length === 0}
          onClick={async () => {
            const files = []
            for (const page of written) files.push(await render(page))
            drafts.delete(props.blockId)
            props.onSend(files)
          }}
        >
          {t('pad.send', { count: written.length })}
        </Button>
      </div>
      {taskOpen && (
        <aside className="absolute start-2 top-17 max-h-[calc(100%-76px)] w-[min(24rem,calc(100%-1rem))] overflow-y-auto rounded-lg border border-border bg-card p-4 text-foreground shadow-float">
          <Markdown>{props.task}</Markdown>
        </aside>
      )}
    </div>
  )
}
