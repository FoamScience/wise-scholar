import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import QRCode from 'qrcode'
import { api, failure } from './api'
import { type ChallengeData, pendingPhotos } from './course'
import Markdown from './Md'
import { Sketchpad } from './Sketchpad'
import { splitBy } from './text'

const photoUrl = (blockId: number, name: string) => `/api/blocks/${blockId}/photos/${name}`
// a phone's own camera is one tap away, so the QR code is only offered where the pointer is a mouse
const phone = () => matchMedia('(pointer: coarse)').matches
// a screen that takes a finger or a stylus can be written on directly
const touchscreen = () => matchMedia('(any-pointer: coarse)').matches

async function send(url: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) throw await failure(res)
  return res.json()
}

/** Photos of work done on paper, waiting to go with the next answer: added from a file, a drop, the camera or a phone. */
export function PhotoTray(props: { blockId: number; task: string; data: ChallengeData; disabled: boolean; onError: (m: string) => void }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [sending, setSending] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [link, setLink] = useState('')
  const [writing, setWriting] = useState(false)
  const pending = pendingPhotos(props.data)

  async function add(files: FileList | File[]) {
    const images = [...files].filter((f) => f.type.startsWith('image/'))
    setSending((n) => n + images.length)
    for (const file of images) {
      // the card updates from the server's event once a photo is stored
      await send(`/api/blocks/${props.blockId}/photos`, file)
        .catch((e: Error) => props.onError(e.message))
        .finally(() => setSending((n) => n - 1))
    }
  }

  return (
    <div
      className={dragging ? 'photo-tray dragging' : 'photo-tray'}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        add(e.dataTransfer.files)
      }}
    >
      {pending.length > 0 && (
        <ul className="photos">
          {pending.map((p) => (
            <li key={p.name}>
              <a href={photoUrl(props.blockId, p.name)} target="_blank" rel="noreferrer">
                <img src={photoUrl(props.blockId, p.name)} alt={t('hand.photoAlt')} />
              </a>
              <button
                type="button"
                className="btn remove"
                aria-label={t('hand.remove')}
                disabled={props.disabled}
                onClick={() => api(`/api/blocks/${props.blockId}/photos/${p.name}/delete`, {}).catch((e: Error) => props.onError(e.message))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="row">
        <input
          ref={input}
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) add(e.target.files)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          className="btn icon"
          disabled={props.disabled}
          aria-label={t(phone() ? 'hand.takePhoto' : 'hand.addPhoto')}
          title={t(phone() ? 'hand.takePhoto' : 'hand.addPhoto')}
          onClick={() => input.current?.click()}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z" />
            <circle cx="12" cy="13" r="3" />
          </svg>
        </button>
        {touchscreen() && (
          <button type="button" className="btn" disabled={props.disabled} onClick={() => setWriting(true)}>
            {t('pad.open')}
          </button>
        )}
        {!phone() && (
          <button
            type="button"
            className="btn icon"
            disabled={props.disabled}
            aria-label={t('hand.usePhone')}
            title={t('hand.usePhone')}
            onClick={() =>
              api<{ token: string }>(`/api/blocks/${props.blockId}/handoff`, {}).then(
                ({ token }) => setLink(`${location.origin}/#/hand/${token}`),
                (e: Error) => props.onError(e.message),
              )
            }
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="6" y="2" width="12" height="20" rx="2" />
              <path d="M11 18h2" />
            </svg>
          </button>
        )}
        <span className="small muted">{sending > 0 ? t('hand.sending') : pending.length > 0 ? t('hand.waiting', { count: pending.length }) : t('hand.hint')}</span>
      </div>
      {writing && (
        <Sketchpad
          blockId={props.blockId}
          task={props.task}
          onClose={() => setWriting(false)}
          onSend={(pages) => {
            setWriting(false)
            add(pages)
          }}
        />
      )}
      {link && <PhoneHandoff link={link} count={pending.length} onClose={() => setLink('')} />}
    </div>
  )
}

function PhoneHandoff(props: { link: string; count: number; onClose: () => void }) {
  const { t } = useTranslation()
  const dialog = useRef<HTMLDialogElement>(null)
  const [qr, setQr] = useState('')
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)

  useEffect(() => {
    dialog.current?.showModal()
    QRCode.toDataURL(props.link, { margin: 1, width: 240 }).then(setQr)
  }, [props.link])

  return (
    <dialog ref={dialog} className="handoff" onClose={props.onClose}>
      <h2>{t('hand.phoneHeading')}</h2>
      <p>{t('hand.phoneSteps')}</p>
      {qr ? <img className="qr" src={qr} width={240} height={240} alt={t('hand.qrAlt')} /> : <div className="qr" />}
      {local && <p className="small error">{t('hand.localAddress')}</p>}
      <p className="small">
        <a href={props.link} target="_blank" rel="noreferrer">
          {t('hand.openLink')}
        </a>{' '}
        · {t('hand.expires')}
      </p>
      <p className="small muted" role="status">
        {t('hand.waiting', { count: props.count })}
      </p>
      <form method="dialog">
        <button className="btn primary">{t('common.done')}</button>
      </form>
    </dialog>
  )
}

/** The photos that went with one attempt, under it in the ladder, with how the tutor read them. */
export function AttemptWork(props: { blockId: number; data: ChallengeData; attempt: number; marks: string[]; onError?: (m: string) => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<string | null>(null)
  const sent = (props.data.photos ?? []).filter((p) => p.attempt === props.attempt)
  const reading = props.data.transcripts?.[props.attempt]
  if (sent.length === 0) return null
  const marked = reading ? props.marks.filter((m) => reading.text.includes(m)) : []
  return (
    <>
      <ul className="photos">
        {sent.map((p) => (
          <li key={p.name}>
            <a href={photoUrl(props.blockId, p.name)} target="_blank" rel="noreferrer">
              <img src={photoUrl(props.blockId, p.name)} alt={t('hand.photoAlt')} />
            </a>
          </li>
        ))}
      </ul>
      {reading && (
        <div className="reading">
          <div className="label">
            {t(reading.by === 'learner' ? 'hand.readByYou' : 'hand.readByTutor')}
            {draft === null && (
              <button type="button" className="link" onClick={() => setDraft(reading.text)}>
                {t('hand.fixReading')}
              </button>
            )}
          </div>
          {draft !== null ? (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                api(`/api/blocks/${props.blockId}/transcripts/${props.attempt}`, { text: draft }).then(
                  () => setDraft(null),
                  (err: Error) => props.onError?.(err.message),
                )
              }}
            >
              <textarea className="field" dir="auto" rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
              <div className="row">
                <button type="button" className="btn" onClick={() => setDraft(null)}>
                  {t('common.cancel')}
                </button>
                <button className="btn primary" disabled={!draft.trim()}>
                  {t('hand.saveReading')}
                </button>
              </div>
            </form>
          ) : marked.length > 0 ? (
            // a hint's marks point at pieces of the reading, so it shows as text with them
            <p className="marked-reading" dir="auto">
              {splitBy(reading.text, marked).map((piece, j) => (piece.hit ? <mark key={j}>{piece.text}</mark> : piece.text))}
            </p>
          ) : (
            <div dir="auto">
              <Markdown>{reading.text}</Markdown>
            </div>
          )}
        </div>
      )}
    </>
  )
}

type Handed = { block_id: number; kind: string; markdown: string; photos: string[] }

/** The phone side of a hand-off: the card's task, the camera and the photos sent so far. */
export function HandPage({ token }: { token: string }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [card, setCard] = useState<Handed | null>(null)
  const [sending, setSending] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Handed>(`/api/handoff/${token}`).then(setCard, (e: Error) => setError(e.message))
  }, [token])

  async function add(files: FileList) {
    setError('')
    setSending((n) => n + files.length)
    for (const file of [...files]) {
      await send(`/api/handoff/${token}/photos`, file)
        .then(({ photos }: { photos: string[] }) => setCard((c) => c && { ...c, photos }))
        .catch((e: Error) => setError(e.message))
        .finally(() => setSending((n) => n - 1))
    }
  }

  return (
    <main className="home hand-page">
      <h1>{t('hand.pageHeading')}</h1>
      {error && <div className="error">{error}</div>}
      {card && (
        <>
          <input
            ref={input}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) add(e.target.files)
              e.target.value = ''
            }}
          />
          <button type="button" className="btn primary big" disabled={sending > 0} onClick={() => input.current?.click()}>
            {sending > 0 ? t('hand.sending') : card.photos.length ? t('hand.another') : t('hand.takePhoto')}
          </button>
          {card.photos.length > 0 && (
            <>
              <ul className="photos">
                {card.photos.map((name) => (
                  <li key={name}>
                    <img src={photoUrl(card.block_id, name)} alt={t('hand.photoAlt')} />
                  </li>
                ))}
              </ul>
              <p>{t('hand.sentBack')}</p>
            </>
          )}
          <details className="block">
            <summary>{t('hand.task')}</summary>
            <Markdown>{card.markdown}</Markdown>
          </details>
        </>
      )}
    </main>
  )
}
