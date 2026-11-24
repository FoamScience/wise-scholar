import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { usePlayer } from './player'
import { splitSentences } from './text'
import { TapWord, WordPanel } from './Words'
import type { Tapped } from './Words'
import { refreshWords, splitWords, useWordStates } from './wordStates'
import type { WordState } from './wordStates'
import { Swap } from './Swap'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { cn } from 'cn'

const BLOCK = 'flex flex-col gap-3 border-t pt-6'
const LABEL = 'text-sm leading-snug font-medium text-ink-2'
const SMALL = 'text-sm text-muted-foreground'
const CHIP = 'h-auto rounded-sm bg-accent px-2 py-0.5 text-sm text-accent-foreground'
const GLOSS_BTN = 'border-warm bg-transparent text-warm hover:bg-warm-tint hover:text-warm'

export type ReadingData = {
  title: string
  lang: string
  glossary: { word: string; meaning: string }[]
  added: string[]
  saved?: string[]
  targets?: string[]
  known?: string[]
  story?: string
  episode?: number
}
type Strands = { input: number; output: number; language: number; fluency: number }

const CEFR = ['C2', 'C1', 'B2', 'B1', 'A2', 'A1']
const STRANDS = ['input', 'output', 'language', 'fluency'] as const

export function ReadingCard(props: {
  id: number
  text: string
  data: unknown
  speech: boolean
  courseId: number | null
  onAdd: (word: string, sentence: string) => Promise<void>
  onKnown: (word: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const d = props.data as ReadingData
  const [open, setOpen] = useState<Tapped | null>(null)
  const [shown, setShown] = useState(false)
  const gloss = d.glossary.find((g) => g.word === open?.word)
  const paragraphs = props.text.split(/\n\s*\n/).map(splitSentences)
  const player = usePlayer(d.lang, props.speech)
  const { courseId } = props
  const states = useWordStates(courseId, [props.text], d.lang)
  const refresh = () => (courseId === null ? undefined : refreshWords(courseId))

  return (
    <section id={`block-${props.id}`} className={`block ${cn(BLOCK, 'gap-0')}`}>
      <div className="flex items-center justify-between gap-3">
        <div className={LABEL}>{d.story ? t('reading.story', { story: d.story, n: d.episode }) : t('reading.label')}</div>
        <label className={cn(SMALL, 'me-3 ms-auto flex items-center gap-2')}>
          <Checkbox checked={player.slow} onCheckedChange={player.setSlow} /> {t('reading.slow')}
        </label>
        <Button
          type="button"
          variant="outline"
          title={props.speech ? t('reading.localVoice') : t('reading.browserVoice')}
          onClick={() => (player.current ? player.stop() : player.play(paragraphs.flat()))}
        >
          {player.current ? t('common.stop') : t('common.listen')}
        </Button>
      </div>
      <h2 lang={d.lang} dir="auto" className="mt-3 mb-0 font-heading text-lg font-semibold">{d.title}</h2>
      {d.targets && d.targets.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={SMALL}>{t('reading.targets')}</span>
          {d.targets.map((target) => (
            <Badge key={target} className={CHIP} lang={d.lang} dir="auto">
              {target}
            </Badge>
          ))}
        </div>
      )}
      {paragraphs.map((sentences, i) => (
        <p key={i} lang={d.lang} dir="auto" className="my-3 text-lg leading-[1.7]">
          {sentences.map((sentence, k) => (
            <GlossedSentence
              key={k}
              sentence={sentence}
              text={props.text}
              lang={d.lang}
              glossary={d.glossary.map((g) => g.word)}
              states={courseId === null ? null : states}
              open={open}
              playing={sentence === player.current}
              onOpen={(tapped) => {
                setOpen(tapped)
                setShown(false)
              }}
            />
          ))}
        </p>
      ))}
      {player.error && <div className="mt-3 rounded-md bg-warm-tint px-4 py-3 text-warm-ink">{player.error}</div>}
      {open && !gloss && courseId !== null && <WordPanel key={open.word} courseId={courseId} lang={d.lang} tapped={open} onClose={() => setOpen(null)} />}
      {open && gloss && (
        <GlossPanel
          gloss={gloss}
          lang={d.lang}
          shown={shown}
          added={d.added.includes(gloss.word) || (d.saved ?? []).includes(gloss.word)}
          known={(d.known ?? []).includes(gloss.word)}
          onShow={() => setShown(true)}
          onAdd={() => void props.onAdd(gloss.word, open.sentence).then(refresh)}
          onKnown={() => void props.onKnown(gloss.word).then(refresh)}
        />
      )}
    </section>
  )
}

/** A sentence of the reading: its glossary words, and with states all its words, are buttons that open their meaning. */
function GlossedSentence(props: {
  sentence: string
  text: string
  lang: string
  glossary: string[]
  states: Record<string, WordState> | null
  open: Tapped | null
  playing: boolean
  onOpen: (tapped: Tapped) => void
}) {
  const { sentence, states } = props
  const isOpen = (word: string) => word === props.open?.word && sentence === props.open.sentence
  return (
    <span className={props.playing ? 'rounded-sm bg-accent shadow-[0_0_0_2px_var(--accent)]' : undefined}>
      {splitWords(sentence, props.glossary, props.lang, props.text).map((piece, j) =>
        piece.kind === 'gloss' ? (
          <button key={j} type="button" className={cn('cursor-pointer border-0 border-b-2 bg-transparent p-0 font-medium', isOpen(piece.text) ? 'border-solid border-warm bg-warm-tint' : 'border-double border-warm')} onClick={() => props.onOpen({ word: piece.text, sentence })}>
            {piece.text}
          </button>
        ) : piece.kind === 'word' && states ? (
          <TapWord key={j} word={piece.text} sentence={sentence} state={states[piece.text]} open={isOpen(piece.text)} onTap={props.onOpen} />
        ) : (
          piece.text
        ),
      )}{' '}
    </span>
  )
}

/** The open glossary word: guess first, then its meaning, and the buttons that file it. */
function GlossPanel(props: {
  gloss: { word: string; meaning: string }
  lang: string
  shown: boolean
  added: boolean
  known: boolean
  onShow: () => void
  onAdd: () => void
  onKnown: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-md bg-warm-tint px-4 py-3 text-warm-ink">
      <span className="grow">
        <strong lang={props.lang} dir="auto">{props.gloss.word}</strong>
        {props.shown ? `: ${props.gloss.meaning}` : ` ${t('reading.guess')}`}
      </span>
      {!props.shown && (
        <Button type="button" variant="outline" className={GLOSS_BTN} onClick={props.onShow}>
          {t('reading.showMeaning')}
        </Button>
      )}
      <Button type="button" variant="outline" className={GLOSS_BTN} disabled={props.added} onClick={props.onAdd}>
        <Swap labels={[t('reading.addVocabulary'), t('reading.inVocabulary')]} at={props.added ? 1 : 0} />
      </Button>
      <Button type="button" variant="outline" className={GLOSS_BTN} disabled={props.known} onClick={props.onKnown}>
        <Swap labels={[t('reading.iKnow'), t('reading.known')]} at={props.known ? 1 : 0} />
      </Button>
    </div>
  )
}

type VocabRound = { tier: number; words: string[]; known: string[]; passed: boolean }
export type VocabData = { lang: string; rounds: VocabRound[]; current: { tier: number; words: string[] } | null; tier: number | null }
export const TIER_WORDS = 200

export function VocabCheckCard(props: { id: number; data: unknown; disabled: boolean; onSubmit: (known: string[]) => void }) {
  const { t } = useTranslation()
  const d = props.data as VocabData
  return (
    <section id={`block-${props.id}`} className={`block ${BLOCK}`}>
      <div className={LABEL}>{t('vocab.label')}</div>
      {d.rounds.map((r) => (
        <div key={r.tier} className={SMALL}>
          {t('vocab.round', { n: r.tier * TIER_WORDS, known: r.known.length, total: r.words.length })}
        </div>
      ))}
      {d.current && (
        <VocabRoundForm key={d.current.tier} lang={d.lang} round={d.current} disabled={props.disabled} onSubmit={props.onSubmit} />
      )}
      {d.tier && (
        <div>
          {t('vocab.yours')} <Badge className={CHIP}>{t('vocab.tier', { tier: d.tier })}</Badge> {t('vocab.working', { n: d.tier * TIER_WORDS })}
        </div>
      )}
    </section>
  )
}

function VocabRoundForm(props: {
  lang: string
  round: { tier: number; words: string[] }
  disabled: boolean
  onSubmit: (known: string[]) => void
}) {
  const { t } = useTranslation()
  const [ticked, setTicked] = useState<string[]>([])
  const toggle = (w: string) => setTicked((all) => (all.includes(w) ? all.filter((x) => x !== w) : [...all, w]))
  return (
    <>
      <h2 className="m-0 font-heading text-lg font-semibold">{t('vocab.from', { n: props.round.tier * TIER_WORDS })}</h2>
      <div className="flex flex-wrap gap-3">
        {props.round.words.map((w) => (
          <Button
            key={w}
            type="button"
            variant="outline"
            lang={props.lang}
            dir="auto"
            className="h-auto min-h-11 max-w-full justify-start whitespace-normal px-4 py-2 text-start leading-snug font-normal wrap-anywhere hover:border-primary hover:bg-accent aria-pressed:border-primary aria-pressed:bg-accent"
            aria-pressed={ticked.includes(w)}
            onClick={() => toggle(w)}
          >
            {w}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" disabled={props.disabled} onClick={() => props.onSubmit(ticked)}>
          {t('vocab.iKnow', { known: ticked.length, total: props.round.words.length })}
        </Button>
      </div>
    </>
  )
}

export function LevelPanel(props: {
  level: string | null
  strands: Strands
  vocabulary: { total: number; due: number; tier?: number; tier_size?: number; tier_known?: number; tier_words?: number }
  units: { mastery: number | null; kind: 'concept' | 'practice' }[]
  disabled: boolean
  story: boolean
  onStart: (kind: 'episode' | 'writing' | 'roleplay') => void
}) {
  const { t } = useTranslation()
  const current = CEFR.find((l) => props.level?.toUpperCase().startsWith(l))
  const units = props.units.filter((u) => u.kind === 'concept')
  const done = units.filter((u) => (u.mastery ?? 0) >= 2 / 3).length
  const most = Math.max(1, ...Object.values(props.strands))
  const total = Object.values(props.strands).reduce((a, b) => a + b, 0)
  const behind = STRANDS.reduce((low, s) => (props.strands[s] < props.strands[low] ? s : low))

  return (
    <div className="flex flex-col gap-2">
      {current && (
        <div className="flex flex-col gap-1">
          {CEFR.map((l) =>
            l === current ? (
              <div key={l} className="flex flex-col gap-2 rounded-md border border-primary bg-accent p-3 text-accent-foreground">
                <div className="flex justify-between">
                  <strong>{l}</strong>
                  <span>{t('level.units', { done, total: units.length })}</span>
                </div>
                <Progress value={done} max={Math.max(1, units.length)} className="[&_[data-slot=progress-track]]:h-2" />
              </div>
            ) : (
              <div key={l} className="rounded-md px-3 py-2 text-muted-foreground">
                {l}
              </div>
            ),
          )}
        </div>
      )}
      <div className={LABEL}>{t('level.byStrand')}</div>
      {STRANDS.map((key) => (
        <div key={key} className="flex items-center gap-2 text-sm">
          <span className="w-26">{t(`level.${key}`)}</span>
          <span className="h-2.5 grow bg-background">
            <i className="block h-2.5 bg-primary" style={{ width: `${(props.strands[key] / most) * 100}%` }} />
          </span>
          <span>{props.strands[key]}</span>
        </div>
      ))}
      {total > 0 && <div className="text-xs text-muted-foreground">{t('level.behind', { strand: t(`level.${behind}`) })}</div>}
      {props.vocabulary.tier && (
        <div className={SMALL}>
          {t('level.tier', {
            tier: props.vocabulary.tier,
            words: props.vocabulary.tier_words,
            known: props.vocabulary.tier_known,
            size: props.vocabulary.tier_size,
          })}
        </div>
      )}
      <a className={cn(buttonVariants({ variant: 'outline' }), 'w-fit')} href="#/review">
        {t('level.vocabulary', { due: props.vocabulary.due, total: props.vocabulary.total })}
      </a>
      <div className="flex flex-wrap items-center gap-2">
        {props.story && (
          <Button type="button" variant="outline" disabled={props.disabled} onClick={() => props.onStart('episode')}>
            {t('level.nextEpisode')}
          </Button>
        )}
        <Button type="button" variant="outline" disabled={props.disabled} onClick={() => props.onStart('writing')}>
          {t('level.writing')}
        </Button>
        {props.story && (
          <Button type="button" variant="outline" disabled={props.disabled} onClick={() => props.onStart('roleplay')}>
            {t('level.roleplay')}
          </Button>
        )}
      </div>
    </div>
  )
}
