import type { KeyboardEvent, RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { transcribe } from './api'
import type { Message } from './course'
import { textDirection } from './text'
import { Mic } from './Mic'

/** A tutor or learner message in the chat sidebar. */
function Remark({ message }: { message: Message }) {
  if (message.role === 'learner')
    return (
      <div id={`msg-${message.id}`} className="bubble learner" dir={textDirection(message.text)}>
        {message.text}
      </div>
    )
  return (
    <div id={`msg-${message.id}`} className="bubble">
      <Markdown>{message.text}</Markdown>
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

function UnreadBadge({ unread }: { unread: number }) {
  const { t } = useTranslation()
  return (
    <span className="badge">
      <span aria-hidden="true">{unread}</span>
      <span className="visually-hidden"> {t('chat.unread', { count: unread })}</span>
    </span>
  )
}

/** The button that opens the chat beside the lesson; it says what the tutor is doing while it works. */
export function AskButton(props: { unread: number; working: string | null; onAsk: () => void }) {
  const { t } = useTranslation()
  return (
    <button type="button" id="ask" className="btn primary icon ask" aria-label={t('chat.ask')} title={t('chat.ask')} onClick={props.onAsk}>
      <ChatIcon size={20} />
      {props.unread > 0 && <UnreadBadge unread={props.unread} />}
      <span className="live" role="status">
        {props.working !== null && ` (${props.working})`}
      </span>
    </button>
  )
}

/** The chat with the tutor: its messages, the reply coming in, and the composer. */
export function ChatPanel({ messagesRef, ...props }: {
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
  canSend: boolean
  onSend: () => void
  onStop: () => void
  onClose: () => void
  onError: (message: string) => void
  messagesRef: RefObject<HTMLDivElement | null>
}) {
  const { t } = useTranslation()
  return (
    <aside
      className="chat"
      aria-label={t('chat.label')}
      hidden={!props.open}
      onKeyDown={(e) => {
        if (e.key === 'Escape') props.onClose()
      }}
    >
      <div className="chat-head">
        <strong>{t('chat.tutor')}</strong>
        <span className={props.running ? 'status live' : 'status'} role="status">
          {props.running && props.doing}
        </span>
        <button type="button" className="link" onClick={props.onClose}>
          {t('chat.close')}
        </button>
      </div>
      <div ref={messagesRef} className="messages">
        {props.messages.map((m) => (
          <Remark key={m.id} message={m} />
        ))}
        {props.open && props.streaming && (
          <div className="bubble">
            <Markdown>{props.streaming}</Markdown>
            <span className="caret" />
          </div>
        )}
      </div>
      <div className="composer">
        <label htmlFor="chat">{t('chat.message')}</label>
        <textarea
          id="chat"
          className="field" dir="auto"
          rows={3}
          value={props.draft}
          placeholder={props.placeholder}
          onChange={(e) => props.onDraft(() => e.target.value)}
          onKeyDown={props.onKey}
        />
        <div className="row">
          {props.speech && <Mic onClip={(clip) => transcribe(clip).then((t) => props.onDraft((d) => (d ? `${d} ${t}` : t)))} onError={props.onError} />}
          {props.running && (
            <button className="btn" onClick={props.onStop}>
              {t('common.stop')}
            </button>
          )}
          <button className="btn primary" onClick={props.onSend} disabled={!props.canSend}>
            {t('common.send')}
          </button>
        </div>
      </div>
    </aside>
  )
}

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
    <nav className="panes" aria-label={t('panes.label')}>
      {(['map', 'lesson'] as const).map((p) => (
        <button
          key={p}
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
      <button aria-pressed={props.open} aria-label={t('chat.ask')} title={t('chat.ask')} onClick={props.onChat}>
        <ChatIcon size={22} />
        {props.unread > 0 && !props.open && <UnreadBadge unread={props.unread} />}
        {/* the chat's head names what the tutor is doing; with the chat closed, a pulse here says it is at work */}
        {props.working !== null && <span className="live" aria-hidden="true" />}
        <span className="visually-hidden" role="status">
          {props.working}
        </span>
      </button>
    </nav>
  )
}
