import { createContext, useContext, useState } from 'react'
import type { KeyboardEvent, RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { transcribe } from './api'
import type { Message } from './course'
import { textDirection } from './text'
import { Mic } from './Mic'
import { plain } from './plain'
import { usePlayer } from './player'
import { TapWord, WordPanel } from './Words'
import type { Tapped } from './Words'
import { sentenceAt, splitWords, useWordStates } from './wordStates'
import type { WordState } from './wordStates'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from 'cn'

const BUBBLE = 'bubble max-w-[90%] rounded-lg px-4 py-3 wrap-anywhere [&>:first-child]:mt-0 [&>:last-child]:mb-0'

/** A role-play line as it is read aloud: plain text, without the quoted scene-setting in the learner's own language. */
function spoken(markdown: string): string {
  return plain(markdown.split('\n').filter((line) => !line.trimStart().startsWith('>')).join('\n'))
}

type Tapping = { states: Record<string, WordState>; open: Tapped | null; onTap: (tapped: Tapped) => void }
const TapContext = createContext<Tapping | null>(null)

/** A word of a role-play line. Its state comes through context, so Markdown keeps one component for every word. */
function LineWord({ word, sentence }: { word: string; sentence: string }) {
  const tapping = useContext(TapContext)
  if (!tapping) return word
  const open = tapping.open?.word === word && tapping.open.sentence === sentence
  return <TapWord word={word} sentence={sentence} state={tapping.states[word]} open={open} onTap={tapping.onTap} />
}

/** A learner's line with each word tappable. */
function LineWords({ text, lang }: { text: string; lang: string }) {
  let at = 0
  return splitWords(text, [], lang).map((piece, i) => {
    const start = at
    at += piece.text.length
    return piece.kind === 'word' ? <LineWord key={i} word={piece.text} sentence={sentenceAt(text, start)} /> : piece.text
  })
}

/** A tutor or learner message in the chat sidebar; a role-play can read the tutor's lines aloud, and its words open
 * their meaning. */
function Remark({ message, player, tapped, courseId, lang, onClose }: {
  message: Message
  player: ReturnType<typeof usePlayer> | null
  tapped: Tapped | null
  courseId: number
  lang: string | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const panel = tapped && lang && <WordPanel key={tapped.word} courseId={courseId} lang={lang} tapped={tapped} onClose={onClose} />
  if (message.role === 'learner')
    return (
      <>
        <div id={`msg-${message.id}`} className={cn(BUBBLE, 'self-end whitespace-pre-wrap bg-primary text-primary-foreground', lang && '[&_button:not(.border-transparent)]:border-current')} dir={textDirection(message.text)}>
          {lang ? <LineWords text={message.text} lang={lang} /> : message.text}
        </div>
        {panel}
      </>
    )
  const line = player ? spoken(message.text) : ''
  return (
    <div id={`msg-${message.id}`} className={cn(BUBBLE, 'self-start bg-muted')}>
      <Markdown words={lang ? { lang, as: LineWord } : undefined}>{message.text}</Markdown>
      {player && line && (
        <Button type="button" variant="ghost" size="sm" className="-ms-2 mt-1 text-ink-2" onClick={() => (player.current === line ? player.stop() : player.play([line]))}>
          {player.current === line ? t('common.stop') : t('common.listen')}
        </Button>
      )}
      {panel}
    </div>
  )
}

function ChatIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
    </svg>
  )
}

function UnreadBadge({ unread, className }: { unread: number; className: string }) {
  const { t } = useTranslation()
  return (
    <Badge className={cn('bg-warm text-xs text-primary-foreground', className)}>
      <span aria-hidden="true">{unread}</span>
      <span className="sr-only"> {t('chat.unread', { count: unread })}</span>
    </Badge>
  )
}

/** The button that opens the chat beside the lesson; it says what the tutor is doing while it works. */
export function AskButton(props: { unread: number; working: string | null; onAsk: () => void }) {
  const { t } = useTranslation()
  return (
    <Button
      type="button"
      id="ask"
      className="sticky bottom-4 min-w-11 self-end overflow-visible px-3 shadow-float animate-in fade-in slide-in-from-bottom-2 duration-(--motion) ease-(--ease) max-md:hidden min-[1101px]:-me-17 [&_svg:not([class*='size-'])]:size-5"
      aria-label={t('chat.ask')}
      title={t('chat.ask')}
      onClick={props.onAsk}
    >
      <ChatIcon size={20} />
      {props.unread > 0 && <UnreadBadge unread={props.unread} className="absolute -end-2 -top-2 h-5.5 min-w-5.5 rounded-[11px] border-2 border-card px-2 leading-[18px]" />}
      <span role="status">{props.working !== null && ` (${props.working})`}</span>
    </Button>
  )
}

/** The chat with the tutor: its messages, the reply coming in, and the composer. */
export function ChatPanel({ messagesRef, className, ...props }: {
  className: string
  open: boolean
  running: boolean
  doing: string
  messages: Message[]
  streaming: string
  draft: string
  onDraft: (update: (draft: string) => string) => void
  placeholder: string | undefined
  onKey: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  speech: boolean
  voice: string | null
  lessonId: number
  courseId: number
  canSend: boolean
  onSend: () => void
  onStop: () => void
  onClose: () => void
  onError: (message: string) => void
  messagesRef: RefObject<HTMLDivElement | null>
}) {
  const { t } = useTranslation()
  const player = usePlayer(props.voice ?? '', props.speech, props.lessonId)
  const states = useWordStates(props.voice ? props.courseId : null, props.messages.map((m) => m.text), props.voice ?? '')
  const [tapped, setTapped] = useState<(Tapped & { message: number }) | null>(null)
  return (
    <aside
      className={cn(
        'flex w-92 shrink-0 flex-col border-s bg-card transition-opacity duration-(--motion) ease-(--ease) starting:opacity-0',
        'md:max-[1100px]:absolute md:max-[1100px]:inset-y-0 md:max-[1100px]:end-0 md:max-[1100px]:z-5 md:max-[1100px]:shadow-float',
        'max-md:absolute max-md:inset-x-0 max-md:top-0 max-md:bottom-13 max-md:z-5 max-md:w-auto max-md:border-0',
        className,
      )}
      aria-label={t('chat.label')}
      hidden={!props.open}
      onKeyDown={(e) => {
        if (e.key === 'Escape') props.onClose()
      }}
    >
      <div className="flex h-13 shrink-0 items-center justify-between border-b px-4">
        <strong>{t('chat.tutor')}</strong>
        <span className={cn('text-sm whitespace-nowrap', props.running ? 'font-medium text-primary' : 'text-muted-foreground')} role="status">
          {props.running && props.doing}
        </span>
        <Button type="button" variant="ghost" className="text-ink-2" onClick={props.onClose}>
          {t('chat.close')}
        </Button>
      </div>
      <div ref={messagesRef} className="flex grow flex-col gap-3 overflow-y-auto p-4">
        {props.messages.map((m) => (
          <TapContext.Provider key={m.id} value={{ states, open: tapped?.message === m.id ? tapped : null, onTap: (word) => setTapped({ ...word, message: m.id }) }}>
            <Remark message={m} player={props.voice ? player : null} tapped={tapped?.message === m.id ? tapped : null} courseId={props.courseId} lang={props.voice} onClose={() => setTapped(null)} />
          </TapContext.Provider>
        ))}
        {props.voice && player.error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{player.error}</div>}
        {props.open && props.streaming && (
          <div className={cn(BUBBLE, 'self-start bg-muted')}>
            <Markdown>{props.streaming}</Markdown>
            <span className="ms-1 inline-block h-4 w-2 bg-foreground align-text-bottom" />
          </div>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-2 border-t px-4 pt-3 pb-4">
        <label htmlFor="chat" className="text-sm text-muted-foreground">
          {t('chat.message')}
        </label>
        <Textarea
          id="chat"
          className="resize-none py-3"
          dir="auto"
          rows={3}
          value={props.draft}
          placeholder={props.placeholder}
          onChange={(e) => props.onDraft(() => e.target.value)}
          onKeyDown={props.onKey}
        />
        <div className="flex flex-wrap items-center justify-end gap-2">
          {props.speech && <Mic onClip={(clip) => transcribe(clip).then((t) => props.onDraft((d) => (d ? `${d} ${t}` : t)))} onError={props.onError} />}
          {props.running && (
            <Button variant="outline" onClick={props.onStop}>
              {t('common.stop')}
            </Button>
          )}
          <Button onClick={props.onSend} disabled={!props.canSend}>
            {t('common.send')}
          </Button>
        </div>
      </div>
    </aside>
  )
}

const PANE =
  'inline-flex min-h-13 flex-1 items-center justify-center border-0 border-t-3 border-transparent bg-transparent text-muted-foreground aria-pressed:border-t-primary aria-pressed:font-semibold aria-pressed:text-accent-foreground'

const PANE_ICONS = {
  map: (
    <>
      <path d="M14.1 6.3 9.9 4.2a2 2 0 0 0-1.8 0L3.6 6.4A1 1 0 0 0 3 7.3v12.1a1 1 0 0 0 1.4.9l3.7-1.9a2 2 0 0 1 1.8 0l4.2 2.1a2 2 0 0 0 1.8 0l4.5-2.2a1 1 0 0 0 .6-.9V5.3a1 1 0 0 0-1.4-.9l-3.7 1.9a2 2 0 0 1-1.8 0z" />
      <path d="M15 5.8v15M9 3.2v15" />
    </>
  ),
  lesson: (
    <>
      <path d="M12 7v14" />
      <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" />
    </>
  ),
}

/** On a phone, the bar that switches between the map, the lesson and the chat. */
export function PaneSwitcher(props: {
  pane: 'map' | 'lesson'
  open: boolean
  unread: number
  working: string | null
  onPane: (pane: 'map' | 'lesson') => void
  onChat: () => void
}) {
  const { t } = useTranslation()
  return (
    <nav className="mt-auto hidden shrink-0 border-t bg-card max-md:flex" aria-label={t('panes.label')}>
      {(['map', 'lesson'] as const).map((p) => (
        <button
          key={p}
          className={PANE}
          aria-pressed={props.pane === p && !props.open}
          aria-label={p === 'map' ? t('map.label') : t('panes.lesson')}
          title={p === 'map' ? t('map.label') : t('panes.lesson')}
          onClick={() => props.onPane(p)}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {PANE_ICONS[p]}
          </svg>
        </button>
      ))}
      <button className={PANE} aria-pressed={props.open} aria-label={t('chat.ask')} title={t('chat.ask')} onClick={props.onChat}>
        <ChatIcon size={22} />
        {props.unread > 0 && !props.open && <UnreadBadge unread={props.unread} className="ms-1 h-5 min-w-5 rounded-[10px] px-1" />}
        {/* the chat's head names what the tutor is doing; with the chat closed, a pulse here says it is at work */}
        {props.working !== null && <span className="ms-1 mb-3.5 size-2 animate-pulse rounded-full bg-primary" aria-hidden="true" />}
        <span className="sr-only" role="status">
          {props.working}
        </span>
      </button>
    </nav>
  )
}
