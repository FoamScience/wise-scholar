import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { Swap } from './Swap'
import { refreshWords } from './wordStates'
import type { WordState } from './wordStates'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from 'cn'

export type Tapped = { word: string; sentence: string }
type Entry = { head: string; pos: string; ipa: string; glosses: string[]; form_of: string[] }
type Looked = { state: WordState; saved: boolean; entries: Entry[] }

// told apart by line style as well as colour
const MARK: Record<WordState, string> = {
  new: 'border-dashed border-warm',
  learning: 'border-solid border-primary',
  seen: 'border-dotted border-muted-foreground',
  known: 'border-transparent',
}
const PANEL_BTN = 'border-warm bg-transparent text-warm hover:bg-warm-tint hover:text-warm'

/** A word that opens its meaning. Known words are left out of the tab order, so a text is not a tab stop per word. */
export function TapWord(props: { word: string; sentence: string; state: WordState | undefined; open: boolean; onTap: (tapped: Tapped) => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className={cn('cursor-pointer border-0 border-b-2 bg-transparent p-0 [font:inherit] text-inherit', MARK[props.state ?? 'known'], props.open && 'bg-warm-tint text-warm-ink')}
      title={props.state && t(`words.${props.state}`)}
      tabIndex={props.state && props.state !== 'known' ? undefined : -1}
      aria-expanded={props.open}
      onClick={() => props.onTap({ word: props.word, sentence: props.sentence })}
    >
      {props.word}
    </button>
  )
}

/** The tapped word: its dictionary entries, a meaning to save it with, and the buttons that file it. */
export function WordPanel(props: { courseId: number; lang: string; tapped: Tapped; onClose: () => void }) {
  const { t } = useTranslation()
  const { courseId, tapped } = props
  const [looked, setLooked] = useState<Looked | null>(null)
  const [meaning, setMeaning] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    api<Looked>(`/api/courses/${courseId}/words?word=${encodeURIComponent(tapped.word)}`).then(
      (found) => {
        if (!current) return
        setLooked(found)
        setMeaning((typed) => typed || (found.entries.flatMap((e) => e.glosses)[0] ?? ''))
      },
      (e: Error) => current && setError(e.message),
    )
    return () => {
      current = false
    }
  }, [courseId, tapped.word])

  function file(path: string, body: unknown, done: Partial<Looked>) {
    setBusy(true)
    setError('')
    api(`/api/courses/${courseId}/${path}`, body)
      .then(
        () => {
          setLooked((l) => l && { ...l, ...done })
          return refreshWords(courseId)
        },
        (e: Error) => setError(e.message),
      )
      .finally(() => setBusy(false))
  }

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-md bg-warm-tint px-4 py-3 text-base text-warm-ink" role="group" aria-label={tapped.word}>
      <div className="flex items-baseline justify-between gap-3">
        <span>
          <strong lang={props.lang} dir="auto">{tapped.word}</strong>
          {looked && ` · ${t(`words.${looked.state}`)}`}
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={props.onClose}>
          {t('words.close')}
        </Button>
      </div>
      {looked && looked.entries.length === 0 && <div className="text-sm">{t('words.noEntry')}</div>}
      {looked?.entries.map((e, i) => (
        <div key={i} className="text-sm">
          <span lang={props.lang} dir="auto" className="font-medium">{e.head}</span> <bdi dir="ltr">{[e.pos, e.ipa].filter(Boolean).join(' · ')}</bdi>
          {e.glosses.length > 0 && (
            <ol lang="en" dir="ltr" className="m-0 list-decimal ps-5">
              {e.glosses.map((g, k) => (
                <li key={k}>{g}</li>
              ))}
            </ol>
          )}
        </div>
      ))}
      {looked && !looked.saved && (
        <label className="flex flex-col gap-1 text-sm">
          {t('words.meaning')}
          <Input dir="auto" maxLength={500} value={meaning} onChange={(e) => setMeaning(e.target.value)} />
        </label>
      )}
      {looked && (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" className={PANEL_BTN} disabled={busy || looked.saved || !meaning.trim()} onClick={() => file('words', { ...tapped, meaning }, { saved: true, state: 'learning' })}>
            <Swap labels={[t('reading.addVocabulary'), t('reading.inVocabulary')]} at={looked.saved ? 1 : 0} />
          </Button>
          <Button type="button" variant="outline" className={PANEL_BTN} disabled={busy || looked.state === 'known'} onClick={() => file('words/known', { word: tapped.word }, { state: 'known' })}>
            <Swap labels={[t('reading.iKnow'), t('reading.known')]} at={looked.state === 'known' ? 1 : 0} />
          </Button>
        </div>
      )}
      {error && <div className="text-sm" role="alert">{error}</div>}
    </div>
  )
}
