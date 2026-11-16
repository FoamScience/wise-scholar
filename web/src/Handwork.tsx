import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import QRCode from 'qrcode'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { cn } from 'cn'
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
      className={cn('my-2 flex flex-col gap-2 rounded-md border border-dashed p-2', dragging ? 'border-primary bg-accent' : 'border-transparent')}
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
        <ul className="m-0 mt-1 flex list-none flex-wrap gap-2 p-0">
          {pending.map((p) => (
            <li key={p.name} className="relative">
              <a href={photoUrl(props.blockId, p.name)} target="_blank" rel="noreferrer">
                <img className="block size-22 rounded-sm border border-border bg-muted object-cover" src={photoUrl(props.blockId, p.name)} alt={t('hand.photoAlt')} />
              </a>
              <Button
                variant="outline"
                size="icon-sm"
                className="absolute -end-2 -top-2 rounded-full bg-card leading-none"
                aria-label={t('hand.remove')}
                disabled={props.disabled}
                onClick={() => api(`/api/blocks/${props.blockId}/photos/${p.name}/delete`, {}).catch((e: Error) => props.onError(e.message))}
              >
                ×
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
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
        <Button
          variant="outline"
          size="icon"
          disabled={props.disabled}
          aria-label={t(phone() ? 'hand.takePhoto' : 'hand.addPhoto')}
          title={t(phone() ? 'hand.takePhoto' : 'hand.addPhoto')}
          onClick={() => input.current?.click()}
        >
          <svg className="size-5" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z" />
            <circle cx="12" cy="13" r="3" />
          </svg>
        </Button>
        {touchscreen() && (
          <Button variant="outline" disabled={props.disabled} onClick={() => setWriting(true)}>
            {t('pad.open')}
          </Button>
        )}
        {!phone() && (
          <Button
            variant="outline"
            size="icon"
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
            <svg className="size-5" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="6" y="2" width="12" height="20" rx="2" />
              <path d="M11 18h2" />
            </svg>
          </Button>
        )}
        <span className="text-sm text-muted-foreground">{sending > 0 ? t('hand.sending') : pending.length > 0 ? t('hand.waiting', { count: pending.length }) : t('hand.hint')}</span>
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
  const [qr, setQr] = useState('')
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)

  useEffect(() => {
    QRCode.toDataURL(props.link, { margin: 1, width: 240 }).then(setQr)
  }, [props.link])

  return (
    <Dialog open disablePointerDismissal onOpenChange={(open) => !open && props.onClose()}>
      <DialogContent showCloseButton={false} className="w-[min(22rem,calc(100vw-2rem))] gap-3 border border-border bg-card p-6 text-center text-base">
        <DialogTitle className="m-0 text-lg">{t('hand.phoneHeading')}</DialogTitle>
        <p>{t('hand.phoneSteps')}</p>
        {qr ? <img className="mx-auto my-3 block size-60 rounded-sm bg-white" src={qr} width={240} height={240} alt={t('hand.qrAlt')} /> : <div className="mx-auto my-3 size-60 rounded-sm bg-white" />}
        {local && <p className="rounded-md bg-warm-tint px-4 py-3 text-sm text-warm-ink">{t('hand.localAddress')}</p>}
        <p className="text-sm text-muted-foreground">
          <a className="text-primary" href={props.link} target="_blank" rel="noreferrer">
            {t('hand.openLink')}
          </a>{' '}
          · {t('hand.expires')}
        </p>
        <p className="text-sm text-muted-foreground" role="status">
          {t('hand.waiting', { count: props.count })}
        </p>
        <DialogClose render={<Button className="mx-auto" />}>{t('common.done')}</DialogClose>
      </DialogContent>
    </Dialog>
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
      <ul className="m-0 mt-1 flex list-none flex-wrap gap-2 p-0">
        {sent.map((p) => (
          <li key={p.name}>
            <a href={photoUrl(props.blockId, p.name)} target="_blank" rel="noreferrer">
              <img className="block size-22 rounded-sm border border-border bg-muted object-cover" src={photoUrl(props.blockId, p.name)} alt={t('hand.photoAlt')} />
            </a>
          </li>
        ))}
      </ul>
      {reading && (
        <div className="mt-2 flex flex-col gap-1 rounded-sm border-s-3 border-rule-strong bg-muted px-3 py-2">
          <div className="flex items-baseline gap-3 text-sm leading-snug font-medium text-ink-2">
            {t(reading.by === 'learner' ? 'hand.readByYou' : 'hand.readByTutor')}
            {draft === null && (
              <Button variant="ghost" className="text-ink-2" onClick={() => setDraft(reading.text)}>
                {t('hand.fixReading')}
              </Button>
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
              <Textarea dir="auto" rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={() => setDraft(null)}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" disabled={!draft.trim()}>
                  {t('hand.saveReading')}
                </Button>
              </div>
            </form>
          ) : marked.length > 0 ? (
            // a hint's marks point at pieces of the reading, so it shows as text with them
            <p className="m-0 whitespace-pre-wrap" dir="auto">
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
    <main className="mx-auto flex w-full max-w-(--measure) flex-col gap-10 px-6 pt-10 pb-16">
      <h1 className="m-0 max-w-none text-2xl">{t('hand.pageHeading')}</h1>
      {error && <div className="rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{error}</div>}
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
          <Button className="h-14" disabled={sending > 0} onClick={() => input.current?.click()}>
            {sending > 0 ? t('hand.sending') : card.photos.length ? t('hand.another') : t('hand.takePhoto')}
          </Button>
          {card.photos.length > 0 && (
            <>
              <ul className="m-0 mt-1 flex list-none flex-wrap gap-2 p-0">
                {card.photos.map((name) => (
                  <li key={name}>
                    <img className="block size-30 rounded-sm border border-border bg-muted object-cover" src={photoUrl(card.block_id, name)} alt={t('hand.photoAlt')} />
                  </li>
                ))}
              </ul>
              <p>{t('hand.sentBack')}</p>
            </>
          )}
          <details className="block border-t border-border pt-6">
            <summary>{t('hand.task')}</summary>
            <Markdown>{card.markdown}</Markdown>
          </details>
        </>
      )}
    </main>
  )
}
