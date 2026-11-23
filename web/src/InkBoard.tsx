import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ANNOTATIONS, InkError, prefill, readInk } from './ink'
import { mount } from './inkPlayer'
import type { Player, ThemeName } from './inkPlayer'
import { InlineMarkdown } from './Md'
import { useTheme } from './theme'

const REDUCED = '(prefers-reduced-motion: reduce)'
const still = () => window.matchMedia?.(REDUCED).matches ?? false
// a board is drawn only once it comes this close to the screen
const NEAR = '400px'
const shownTheme = (): ThemeName =>
  (document.documentElement.dataset.theme ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark' ? 'dark' : 'light'

// `[the sum](#board-12-main.sum)` in the lesson text names part of board block 12 (see Md.tsx).
const LINKED = '[data-board-ref]'

/** A handwritten board (an ink document from wise-board), played beat by beat with its captions. */
export function InkBoard(props: { id: number; doc: unknown; disabled?: boolean; onAsk?: (ref: string, question: string) => void }) {
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const player = useRef<Player | null>(null)
  const doc = useMemo(() => {
    try {
      return readInk(props.doc)
    } catch (e) {
      if (e instanceof InkError) return null
      throw e
    }
  }, [props.doc])
  const beats = doc?.beats.map((b) => b.say) ?? []
  const [at, setAt] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [paused, setPaused] = useState(false)
  const [near, setNear] = useState(() => typeof IntersectionObserver === 'undefined')
  const [asking, setAsking] = useState<{ ref: string; question: string } | null>(null)
  const theme = useTheme()
  const ask = useRef(props.onAsk)
  useEffect(() => {
    ask.current = props.onAsk
  }, [props.onAsk])

  useEffect(() => {
    if (near || !host.current) return
    const seen = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), { rootMargin: NEAR })
    seen.observe(host.current)
    return () => seen.disconnect()
  }, [near])

  useEffect(() => {
    if (!doc || !near) return
    const title = doc.elements.find((e) => e.kind === 'title')?.alt
    const p = mount(host.current!, doc, { theme: shownTheme(), reducedMotion: still(), label: title ? t('board.label', { title }) : t('block.board') })
    player.current = p
    p.show(doc.beats.length - 1)
    const media = window.matchMedia?.(REDUCED)
    const motion = () => p.motion(still())
    media?.addEventListener('change', motion)
    const offs = [
      () => media?.removeEventListener('change', motion),
      p.on('beat', (n) => setAt(n)),
      p.on('end', () => {
        setPlaying(false)
        setPaused(false)
      }),
      p.on('ask', (ref) => {
        if (ask.current) setAsking({ ref, question: prefill(doc, ref, (what) => t('board.askPrefill', { what })) })
      }),
    ]
    return () => {
      offs.forEach((off) => off())
      p.destroy()
      player.current = null
    }
  }, [doc, near]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => player.current?.theme(shownTheme()), [theme])

  // A term in the text lights up its part of the board while pointed at or focused, and brings the board into view.
  useEffect(() => {
    const ref = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.(LINKED)
      return el && el.getAttribute('data-board') === String(props.id) ? el : null
    }
    const on = (e: Event) => {
      const el = ref(e)
      if (!el) return
      el.classList.add('term-on')
      player.current?.highlight(el.getAttribute('data-board-ref'))
    }
    const off = (e: Event) => {
      const el = ref(e)
      if (!el) return
      el.classList.remove('term-on')
      player.current?.highlight(null)
    }
    const go = (e: Event) => {
      const el = ref(e)
      if (!el) return
      host.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      player.current?.highlight(el.getAttribute('data-board-ref'))
    }
    const key = (e: Event) => {
      const k = (e as KeyboardEvent).key
      if ((k === 'Enter' || k === ' ') && ref(e)) {
        e.preventDefault()
        go(e)
      }
    }
    const events: [string, (e: Event) => void][] = [['pointerover', on], ['focusin', on], ['pointerout', off], ['focusout', off], ['click', go], ['keydown', key]]
    for (const [k, f] of events) document.addEventListener(k, f)
    return () => {
      for (const [k, f] of events) document.removeEventListener(k, f)
    }
  }, [props.id])

  if (!doc) return <p className="m-0 text-sm text-muted-foreground">{t('board.unreadable')}</p>

  const last = beats.length - 1
  function go(n: number, onward: boolean) {
    const p = player.current
    if (!p) return
    p.seek({ beat: n })
    setAt(n)
    setPaused(false)
    if (onward) {
      p.play()
      setPlaying(true)
    } else {
      p.show(n)
      setPlaying(false)
    }
  }
  // Goes on from where the board stands: inside the paused beat, or after the beat stepped to.
  function resume() {
    player.current?.play()
    setPlaying(true)
    setPaused(false)
  }
  function pause() {
    player.current?.pause()
    setPlaying(false)
    setPaused(true)
  }
  function whole() {
    player.current?.show(last)
    setPlaying(false)
    setPaused(false)
    setAt(null)
  }
  const fresh = at === null || (at === last && !paused)
  function closeAsk() {
    setAsking(null)
    player.current?.highlight(null)
  }

  return (
    <div className="flex flex-col gap-2">
      <div ref={host} className="overflow-hidden rounded-md border border-border" />
      {at !== null && beats[at] && (
        <p className="m-0" dir="auto" aria-live="polite">
          {beats[at]}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {playing ? (
          <Button size="sm" onClick={pause}>{t('board.pause')}</Button>
        ) : (
          <Button size="sm" disabled={!beats.length} onClick={() => (fresh ? go(0, true) : resume())}>
            {at === null ? t('board.play') : fresh ? t('board.again') : t('board.resume')}
          </Button>
        )}
        <Button variant="outline" size="sm" disabled={!at} onClick={() => go(at! - 1, false)}>{t('board.back')}</Button>
        <Button variant="outline" size="sm" disabled={at === last} onClick={() => go(at === null ? 0 : at + 1, false)}>{t('board.next')}</Button>
        <span className="text-sm text-muted-foreground tabular-nums">
          {at === null ? t('board.steps', { count: beats.length }) : t('board.at', { n: at + 1, count: beats.length })}
        </span>
        {at !== null && <Button variant="ghost" size="sm" onClick={whole}>{t('board.wholeBoard')}</Button>}
      </div>
      {asking ? (
        <form
          className="grid gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!asking.question.trim()) return
            props.onAsk!(asking.ref, asking.question)
            closeAsk()
          }}
        >
          <Input
            dir="auto"
            maxLength={1000}
            aria-label={t('board.askThis')}
            placeholder={t('board.askThis')}
            value={asking.question}
            onChange={(e) => setAsking({ ...asking, question: e.target.value })}
            onKeyDown={(e) => e.key === 'Escape' && closeAsk()}
            autoFocus
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={props.disabled || !asking.question.trim()}>{t('board.ask')}</Button>
            <Button variant="outline" size="sm" onClick={closeAsk}>{t('common.cancel')}</Button>
          </div>
        </form>
      ) : (
        props.onAsk && <p className="m-0 text-sm text-muted-foreground">{t('board.tapToAsk')}</p>
      )}
      <ul className="sr-only">
        {doc.elements.filter((e) => !ANNOTATIONS.has(e.kind) && e.alt).map((e, i) => (
          <li key={i} dir="auto">{e.alt}</li>
        ))}
      </ul>
    </div>
  )
}

/** A board block: `{script, doc}` written by the tutor with add_board. */
export function InkBoardCard(props: { id: number; caption: string; data: unknown; disabled?: boolean; onAsk?: (ref: string, question: string) => void }) {
  const { t } = useTranslation()
  const doc = (props.data as { doc?: unknown } | null)?.doc
  return (
    <section id={`block-${props.id}`} className="block flex flex-col gap-2 border-t border-border pt-6 break-inside-avoid first:border-t-0 first:pt-0">
      <div className="text-sm leading-snug font-medium text-ink-2 break-after-avoid">{t('block.board')}</div>
      <InkBoard id={props.id} doc={doc} disabled={props.disabled} onAsk={props.onAsk} />
      {props.caption && <div className="text-sm text-muted-foreground"><InlineMarkdown>{props.caption}</InlineMarkdown></div>}
    </section>
  )
}
