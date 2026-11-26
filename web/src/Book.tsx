import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import Markdown, { AnswerText, InlineMarkdown } from './Md'
import { NetworkCard } from './Network'
import { api, failure } from './api'
import { parts, timeline } from './chapters'
import { blockKey, challengeLabel, lessonTitle, practiceTitle, sortItems } from './course'
import { PlacementAreas } from './Areas'
import type { Area, Block, ChallengeData, Concept, CourseDetail, ExerciseData, ExerciseFile, Lesson, Message, QuestionData, SpeakingData } from './course'
import { Correction } from './Diff'
import type { Entry } from './Errors'
import { Credits, Drawing, Limits } from './Figure'
import { BoardSteps } from './Board'
import { WidgetCard } from './Widget'
import type { FigureData } from './Figure'
import { Comparison, Helper, HintList, Ladder } from './Ladder'
import { day, lookup, percent } from './i18n'
import { TIER_WORDS } from './Language'
import type { ReadingData, VocabData } from './Language'
import Logo from './Logo'
import { PlotCard } from './PlotCard'
import type { PodcastData } from './Podcast'
import { GradedAnswer, Translation } from './Quiz'
import { ScopeCard } from './Scope'
import type { QuizData } from './Quiz'
import { textDirection } from './text'
import { pageStyle } from './print'
import { useTheme } from './theme'
import { Swap } from './Swap'
import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from 'cn'

const page = 'mx-auto flex w-full max-w-[var(--measure)] flex-col gap-10 px-6 pt-10 pb-16'
const chip = 'inline-block rounded-sm bg-[var(--teal-tint)] px-2 py-0.5 leading-snug font-medium text-accent-foreground'
const label = 'text-sm leading-snug font-medium text-ink-2'
const errorBox = 'rounded-md bg-warm-tint px-4 py-3 text-warm-ink'
const muted = 'text-muted-foreground'
const bookNumber = 'text-sm font-semibold'
const note = 'rounded-md px-4 py-3 print:break-inside-avoid [&>:last-child]:mb-0'

const file = 'overflow-hidden rounded-md border border-border [&_pre]:m-0 [&_pre]:max-h-[420px] [&_pre]:overflow-auto [&_pre]:rounded-none'
const fileHead = 'flex min-h-11 items-center justify-between gap-3 ps-4 pe-1 [overflow-wrap:anywhere]'

type Files = Map<number, ExerciseFile[]>

function conceptStatus(concept: Concept, started: boolean, t: TFunction): string {
  if (concept.placed_out) return t('map.placedOut')
  if (!started) return t('map.notStarted')
  if (concept.kind === 'practice') return concept.mastery === null ? t('map.started') : t('common.done')
  return concept.mastery === null ? t('map.started') : t('map.mastery', { n: Math.round(concept.mastery * 3) })
}

function Card(props: { label: ReactNode; className?: string; boxed?: boolean; avoid?: boolean; children: ReactNode }) {
  return (
    <section
      className={cn(
        'flex flex-col gap-2 border-t border-border pt-6 print:block print:[box-decoration-break:clone] print:[&>*+*]:mt-2 [&_h3]:m-0 [&_h3]:text-lg [&_h3]:font-medium [&_p:first-of-type]:mt-0 [&>:last-child]:mb-0',
        props.boxed && 'rounded-lg border border-primary bg-card p-6',
        props.avoid && 'print:break-inside-avoid',
        props.className,
      )}
    >
      <div className={cn(label, 'flex items-center gap-2 print:break-after-avoid')}>{props.label}</div>
      {props.children}
    </section>
  )
}

function QuizBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as QuizData
  return (
    <Card label={d.pretest ? t('quiz.pretest') : d.kind === 'sort' ? t('quiz.sort') : t('quiz.quickCheck')} className="quiz" avoid>
      <Markdown>{block.markdown}</Markdown>
      <Translation text={d.translation} open />
      <QuizOptions data={d} />
      <QuizOutcome data={d} />
    </Card>
  )
}

/** A sort card's items and categories while unanswered; a choice card's options with the one picked marked. */
function QuizOptions({ data: d }: { data: QuizData }) {
  if (d.kind === 'sort' && d.answer === null)
    return (
      <ul className="book-options">
        {sortItems(d.options).map((o) => (
          <li key={o.text}>
            <Markdown>{o.text}</Markdown>
          </li>
        ))}
        <li className={muted}>{d.categories?.join(', ')}</li>
      </ul>
    )
  if (d.kind !== 'choice') return null
  return (
    <ul className="book-options" dir={textDirection((d.options as string[]).join(' '))}>
      {(d.options as string[]).map((o) => (
        <li key={o} className={o === d.answer ? 'picked' : undefined}>
          <Markdown>{o}</Markdown>
        </li>
      ))}
    </ul>
  )
}

function QuizOutcome({ data: d }: { data: QuizData }) {
  const { t } = useTranslation()
  if (d.answer === null) return <div className={muted}>{t('book.unanswered')}</div>
  return <GradedAnswer data={d} />
}

function ReadingBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as ReadingData
  return (
    <Card label={d.story ? t('reading.story', { story: d.story, n: d.episode }) : t('card.reading')} className="reading">
      <h3 lang={d.lang} dir="auto">
        {d.title}
      </h3>
      {block.markdown.split(/\n\s*\n/).map((paragraph, i) => (
        <p key={i} lang={d.lang} dir="auto">
          {paragraph}
        </p>
      ))}
      {d.glossary.length > 0 && (
        <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-1 border-t border-border pt-3 [&_dd]:m-0 [&_dd]:text-muted-foreground [&_dt]:font-medium [&>div]:flex [&>div]:gap-2">
          {d.glossary.map((g) => (
            <div key={g.word}>
              <dt lang={d.lang} dir="auto">
                {g.word}
              </dt>
              <dd dir="auto">{g.meaning}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  )
}

function ExerciseBlock({ block, files }: { block: Block; files: ExerciseFile[] }) {
  const { t } = useTranslation()
  const d = block.data as ExerciseData
  return (
    <Card label={d.milestone ? t('challenge.milestone') : t('exercise.label')} className="challenge">
      <Markdown>{block.markdown}</Markdown>
      <Helper data={d} open />
      {files.map((f) => (
        <div key={f.path} className={file}>
          <div className={fileHead}>
            <code>{f.path}</code>
          </div>
          {f.content === null ? (
            <pre>{t('exercise.missing')}</pre>
          ) : (
            <div>
              <Markdown>{`\`\`\`\`${f.path.split('.').pop() ?? ''}\n${f.content}\n\`\`\`\``}</Markdown>
            </div>
          )}
        </div>
      ))}
      <code>$ {d.run}</code>
      {d.last_run && (
        <div className={file}>
          <div className={fileHead}>
            <span className={label}>
              {d.last_run.exit_code === null ? t('exercise.outputStopped') : t('exercise.outputExit', { code: d.last_run.exit_code })}
            </span>
          </div>
          <pre>{d.last_run.output || t('exercise.noOutput')}</pre>
        </div>
      )}
      <Ladder data={d} />
    </Card>
  )
}

type BlockProps = { block: Block; files: Files; sketched: boolean }

/** How each kind of card prints; a kind not here prints its text under its name. */
const BOOK_BLOCKS: Record<string, (props: BlockProps) => ReactNode> = {
  quiz: ({ block }) => <QuizBlock block={block} />,
  reading: ({ block }) => <ReadingBlock block={block} />,
  exercise: ({ block, files }) => <ExerciseBlock block={block} files={files.get(block.id) ?? []} />,
  plot: ({ block }) => <PlotCard id={block.id} title={block.markdown} data={block.data} />,
  widget: ({ block }) => <WidgetCard id={block.id} title={block.markdown} data={block.data} />,
  network: ({ block }) => <NetworkCard id={block.id} reason={block.markdown} data={block.data} disabled />,
  question: ({ block }) => <QuestionBlock block={block} />,
  challenge: ({ block }) => <ChallengeBlock block={block} />,
  speaking: ({ block }) => <SpeakingBlock block={block} />,
  vocab: ({ block }) => <VocabBlock block={block} />,
  podcast: ({ block }) => <PodcastBlock block={block} />,
  figure: ({ block, sketched }) => <FigureBlock block={block} sketched={sketched} />,
  placement: ({ block }) => (
    <PlacementCard level={(block.data as { level: string }).level} text={block.markdown} areas={(block.data as { areas?: Area[] }).areas} />
  ),
}

function BookBlock(props: BlockProps) {
  const render = BOOK_BLOCKS[props.block.kind]
  if (render) return render(props)
  return (
    <Card label={lookup(`block.${blockKey(props.block)}`, props.block.kind)}>
      <Markdown>{props.block.markdown}</Markdown>
    </Card>
  )
}

function SolvedChip({ data: d }: { data: ChallengeData }) {
  const { t } = useTranslation()
  return d.solved && <span className={chip}>{d.writing ? t('common.done') : t('common.solved')}</span>
}

function QuestionBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as QuestionData
  return (
    <Card label={t('card.question')} className="question" boxed avoid>
      <h3 dir="auto"><InlineMarkdown>{block.markdown}</InlineMarkdown></h3>
      {d.answer === null ? (
        <div className={muted}>{t('book.unanswered')}</div>
      ) : (
        <span className={cn(chip, 'w-full rounded-md px-3 py-2 font-medium')}>
          <AnswerText text={d.answer} />
        </span>
      )}
    </Card>
  )
}

function ChallengeBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as ChallengeData
  return (
    <Card
      label={
        <>
          {challengeLabel(d, false, t)}
          <SolvedChip data={d} />
        </>
      }
      className="challenge"
    >
      <Markdown>{block.markdown}</Markdown>
      <Comparison data={d} />
      <Helper data={d} open />
      <Ladder data={d} />
    </Card>
  )
}

function SpeakingBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as SpeakingData
  return (
    <Card
      label={
        <>
          {d.speaking === 'shadow' ? t('speaking.shadow') : t('speaking.read')}
          <SolvedChip data={d} />
        </>
      }
      className="challenge"
    >
      <p className="m-0 text-lg" lang={d.lang} dir="auto">
        {block.markdown}
      </p>
      {d.scores.map((a, i) => (
        <div key={i} className={attempt}>
          <span className={label}>{t('speaking.attemptScore', { n: i + 1, score: percent(a.score) })}</span>
          {a.heard !== null && <span lang={d.lang} dir="auto">{a.heard}</span>}
        </div>
      ))}
      <HintList data={d} />
    </Card>
  )
}

function VocabBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as VocabData
  return (
    <Card label={t('card.vocab')}>
      {d.rounds.map((r) => (
        <div key={r.tier}>{t('vocab.round', { n: r.tier * TIER_WORDS, known: r.known.length, total: r.words.length })}</div>
      ))}
      {d.tier && (
        <div>
          {t('vocab.yours')} <span className={chip}>{t('vocab.tier', { tier: d.tier })}</span> {t('vocab.working', { n: d.tier * TIER_WORDS })}
        </div>
      )}
    </Card>
  )
}

function PodcastBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as PodcastData
  return (
    <Card label={`${d.cues.length ? t('cast.quiz') : t('cast.recap')}: ${t('cast.transcript')}`}>
      <h3 dir="auto">{block.markdown}</h3>
      <div lang={d.lang} dir="auto">
        {d.lines.map((l, i) => (
          <p key={i}>
            <strong>{l.speaker}:</strong> {l.text}
          </p>
        ))}
      </div>
    </Card>
  )
}

function FigureBlock({ block, sketched }: { block: Block; sketched: boolean }) {
  const { t } = useTranslation()
  const d = block.data as FigureData
  return (
    <Card label={t('block.figure')} className="figure" avoid>
      {d.frames && d.frames.length > 1 ? (
        <div className="flex flex-wrap items-start gap-2 [&_.figure-box]:min-w-[220px] [&_.figure-box]:flex-[1_1_220px]">
          {d.frames.map((frame, i) => (
            <Drawing key={i} className="figure-box" svg={frame} alt={`${d.alt}, ${t('block.stage', { n: i + 1 })}`} sketched={false} />
          ))}
        </div>
      ) : (
        <Drawing className="figure-box" svg={d.svg} alt={d.alt} sketched={sketched && !d.diagram} board={d.board?.steps} />
      )}
      {d.board && <BoardSteps steps={d.board.steps} />}
      {block.markdown && <div className="text-sm text-muted-foreground"><InlineMarkdown>{block.markdown}</InlineMarkdown></div>}
      <Limits teaches={d.teaches} />
      <Credits credits={d.credits} />
    </Card>
  )
}

function PlacementCard(props: { level: string | null; text: string; areas: Area[] | undefined }) {
  const { t } = useTranslation()
  return (
    <Card
      label={
        <>
          {t('block.placementResult')} <span className={chip}>{props.level}</span>
        </>
      }
    >
      <Markdown>{props.text}</Markdown>
      <PlacementAreas areas={props.areas} />
    </Card>
  )
}

function Plan({ course }: { course: CourseDetail }) {
  const { t } = useTranslation()
  return (
    <Card label={t('plan.heading')}>
      <ol className="m-0 flex list-decimal flex-col gap-2 ps-6">
        {course.ranking.map((r) => (
          <li key={r.mechanism}>
            <strong>{lookup(`playbooks.${r.mechanism}.title`, r.title)}</strong>
            {r.mechanism === course.mechanism && <span className={chip}>{t('book.chosen')}</span>}
            <div dir="auto">{r.rationale}</div>
            <div className={muted}>{lookup(`playbooks.${r.mechanism}.summary`, r.summary)}</div>
            <div className="text-sm text-muted-foreground">
              {t('plan.evidence')}{' '}
              {r.evidence.map((e, n) => (
                <span key={e.url}>
                  {n > 0 && '; '}
                  <a href={e.url}>{e.source}</a>
                </span>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}

function BookTurn({ message, learner }: { message: Message; learner: string }) {
  const { t } = useTranslation()
  const mine = message.role === 'learner'
  return (
    <div className={cn('flex flex-col items-start gap-1 print:block', mine && 'items-end')}>
      <span className={cn(label, 'print:block print:break-after-avoid', mine && 'print:text-end')}>{mine ? learner : t('chat.tutor')}</span>
      <div
        className={cn(
          'max-w-[78%] rounded-lg border border-border bg-card px-4 py-3 [overflow-wrap:anywhere] print:mt-1 print:w-fit print:[box-decoration-break:clone] [&>:first-child]:mt-0 [&>:last-child]:mb-0',
          mine && 'border-primary bg-primary whitespace-pre-wrap text-primary-foreground print:ms-auto',
        )}
      >
        {mine ? <span dir={textDirection(message.text)}>{message.text}</span> : <Markdown>{message.text}</Markdown>}
      </div>
    </div>
  )
}

const chapterHead = 'mt-6 flex flex-col gap-2 border-b-2 border-primary pb-3 print:mt-0 print:break-after-avoid'
const h2 = 'm-0 text-2xl leading-tight font-semibold'
const attempt = 'flex flex-col gap-0.5 rounded-md bg-secondary px-4 py-3 whitespace-pre-wrap print:break-inside-avoid'

function Chapter(props: { n: number; lesson: Lesson; course: CourseDetail; files: Files; learner: string; sketched: boolean }) {
  const { t } = useTranslation()
  const { lesson, course } = props
  const lastPlacement = course.lessons.filter((l) => l.phase === 'placement').at(-1)
  return (
    <article id={`book-lesson-${lesson.id}`} className="book-chapter flex flex-col gap-4 print:block print:break-before-page print:[&>*+*]:mt-4">
      <header className={chapterHead}>
        <span className={cn(bookNumber, 'text-primary')}>{t('book.chapter', { n: props.n })}</span>
        <h2 className={h2} dir="auto">{lessonTitle(lesson, t)}</h2>
      </header>
      {lesson.phase === 'interview' && <ScopeCard course={course} />}
      {timeline(lesson, course.mode === 'teacher').map((item) =>
        'block' in item ? (
          <BookBlock key={`b${item.block.id}`} block={item.block} files={props.files} sketched={props.sketched} />
        ) : (
          <BookTurn key={`m${item.message.id}`} message={item.message} learner={props.learner} />
        ),
      )}
      {lesson.phase === 'interview' && course.ranking.length > 0 && <Plan course={course} />}
      {lesson.id === lastPlacement?.id && course.placement && !lesson.blocks.some((b) => b.kind === 'placement') && (
        <PlacementCard level={course.level} text={course.placement} areas={course.areas} />
      )}
    </article>
  )
}

function NotebookEntry({ entry: e }: { entry: Entry }) {
  const { t } = useTranslation()
  return (
    <Card
      label={
        <>
          {e.kind === 'writing' ? t('common.correctedText') : t('notebook.confidentMiss')}, {day(e.created)}
          {e.pinned ? <span className={chip}>{t('notebook.pinned')}</span> : null}
          {e.resolved ? <span className={chip}>{t('notebook.resolve')}</span> : null}
        </>
      }
      className={cn('entry', 'print:break-inside-avoid', e.resolved && 'opacity-60')}
    >
      {e.kind === 'quiz' && <Markdown>{e.prompt}</Markdown>}
      <div className={attempt}>
        <span className={label}>{e.kind === 'writing' ? t('notebook.youWrote') : t('notebook.youSaid')}</span>
        <Said entry={e} />
      </div>
      <div className={cn(note, 'flex flex-col bg-[var(--teal-tint)]')}>
        <div className={label}>{e.kind === 'writing' ? t('notebook.corrected') : t('notebook.rightAnswer')}</div>
        <Corrected entry={e} />
        {e.explanation && <Markdown>{e.explanation}</Markdown>}
        {e.misconception && <p><InlineMarkdown>{t('quiz.belief', { belief: e.misconception })}</InlineMarkdown></p>}
      </div>
      {e.note && (
        <div className={cn(note, 'bg-warm-tint text-warm-ink')}>
          <div className={cn(label, 'text-warm')}>{t('book.yourNote')}</div>
          <span dir={textDirection(e.note)}>{e.note}</span>
        </div>
      )}
    </Card>
  )
}

/** What the learner wrote or said: a writing entry as plain text, a quiz entry as its answer. */
function Said({ entry: e }: { entry: Entry }) {
  return e.kind === 'writing' ? <span className="line-through decoration-warm decoration-2" dir={textDirection(e.said)}>{e.said}</span> : <span className="line-through decoration-warm decoration-2"><AnswerText text={e.said} /></span>
}

/** A writing entry's text corrected against what was written; a quiz entry's right answer. */
function Corrected({ entry: e }: { entry: Entry }) {
  return e.kind === 'writing' ? <Correction attempt={e.said} corrected={e.correct} /> : <Markdown>{e.correct}</Markdown>
}

function Notebook({ entries }: { entries: Entry[] }) {
  const { t } = useTranslation()
  return (
    <article id="book-notebook" className="book-chapter flex flex-col gap-4 print:block print:break-before-page print:[&>*+*]:mt-4">
      <header className={chapterHead}>
        <span className={cn(bookNumber, 'text-primary')}>{t('book.appendix')}</span>
        <h2 className={h2}>{t('review.errorNotebook')}</h2>
      </header>
      {entries.map((e) => (
        <NotebookEntry key={e.id} entry={e} />
      ))}
    </article>
  )
}

/** Running head and page number sit in the page margins, which only take literal values: read them from the live theme. */

const jump = (id: string) => (e: { preventDefault: () => void }) => {
  e.preventDefault()
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}

const coverBox =
  'book-cover flex min-h-[560px] flex-col items-start gap-4 rounded-lg bg-primary px-16 pt-16 pb-10 text-primary-foreground print:!m-0 print:box-border print:h-[296mm] print:rounded-none print:px-[24mm] print:pt-[40mm] print:pb-[24mm] print:break-after-page'
const rule = 'block h-[3px] w-16 bg-warm'

function Cover({ course, learner, exported }: { course: CourseDetail; learner: string; exported: string }) {
  const { t } = useTranslation()
  return (
    <header className={coverBox}>
      <Logo size={56} />
      <span className={bookNumber}>{t('book.kicker')}</span>
      <h1 className="m-0 text-[48px] leading-[1.1] font-semibold" dir="auto">{course.topic}</h1>
      <span className={rule} />
      {course.mechanism && <div className="text-lg">{lookup(`playbooks.${course.mechanism}.title`, course.mechanism)}</div>}
      <div className="flex-grow" />
      <div>
        {learner}
        {course.level && `, ${t('map.level')} ${course.level}`}
      </div>
      <div className={bookNumber}>{t('book.exported', { date: day(exported) })}</div>
    </header>
  )
}

/** The table of contents: each part's chapters, then the appendices. */
function Contents(props: { course: CourseDetail; parts: ReturnType<typeof parts>; numbers: Map<number, number>; notebook: boolean }) {
  const { t } = useTranslation()
  const { course } = props
  return (
    <nav className="flex flex-col gap-4 py-6 print:break-before-page [&_a]:text-inherit [&_a]:no-underline [&_ol]:m-0 [&_ol]:mt-2 [&_ol]:flex [&_ol]:list-decimal [&_ol]:flex-col [&_ol]:gap-2 [&_ol]:ps-6 [&_ul]:m-0 [&_ul]:mt-2 [&_ul]:flex [&_ul]:list-disc [&_ul]:flex-col [&_ul]:gap-2 [&_ul]:ps-6">
      <h2 className={h2}>{t('book.contents')}</h2>
      {props.parts.map((part, i) => (
        <div key={i}>
          {part.title && (
            <div className={cn(bookNumber, 'text-primary')} dir="auto">
              {part.title}
            </div>
          )}
          <ol>
            {part.lessons.map((l) => (
              <li key={l.id} value={props.numbers.get(l.id)}>
                <a href={`#book-lesson-${l.id}`} onClick={jump(`book-lesson-${l.id}`)} dir="auto">
                  {lessonTitle(l, t)}
                </a>
              </li>
            ))}
          </ol>
        </div>
      ))}
      {(course.capstones.length > 0 || props.notebook) && (
        <ul>
          {course.capstones.length > 0 && (
            <li>
              <a href="#book-projects" onClick={jump('book-projects')}>
                {t('book.projects')}
              </a>
            </li>
          )}
          {props.notebook && (
            <li>
              <a href="#book-notebook" onClick={jump('book-notebook')}>
                {t('review.errorNotebook')}
              </a>
            </li>
          )}
        </ul>
      )}
    </nav>
  )
}

/** The course map: each module's units with how far the learner got. */
function BookMap({ course }: { course: CourseDetail }) {
  const { t } = useTranslation()
  return (
    <section className="flex flex-col gap-4 py-6 print:break-before-page print:[&:is(nav+*)]:break-before-auto">
      <h2 className={h2}>{t('map.label')}</h2>
      {[...new Set(course.concepts.map((c) => c.module))].map((module) => (
        <div key={module}>
          <h3 className="m-0 text-base font-medium" dir="auto">{module}</h3>
          <ul className="m-0 mt-2 flex list-disc flex-col gap-2 ps-6">
            {course.concepts
              .filter((c) => c.module === module)
              .map((c) => (
                <li key={c.id} className="flex justify-between gap-4 border-b border-dotted border-rule-strong">
                  <span dir="auto">{c.kind === 'practice' ? practiceTitle(c.title, t) : c.title}</span>
                  <span className={muted}>{conceptStatus(c, course.lessons.some((l) => l.concept_id === c.id), t)}</span>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </section>
  )
}

async function downloadPdf(courseId: number, topic: string) {
  const res = await fetch(`/api/courses/${courseId}/book.pdf?theme=${document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'}`)
  if (!res.ok) throw await failure(res)
  const link = document.createElement('a')
  link.href = URL.createObjectURL(await res.blob())
  link.download = `${topic}.pdf`
  link.click()
  // Revoking at once can cancel the download before the browser has read the blob.
  setTimeout(() => URL.revokeObjectURL(link.href), 60_000)
}

/** A whole course laid out as a book. The server prints this same page to a PDF, so the file has the site's theme and type;
 * without the PDF extra the browser's print dialog does it. */
/** Everything the book prints, fetched in one go, with the page titled after the course while it is open. */
function useBookData(courseId: number) {
  const [loaded, setLoaded] = useState<{ course: CourseDetail; entries: Entry[]; files: Files } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    // The book shows only once everything is in: the server prints the page as soon as the cover appears.
    async function load() {
      const [course, entries] = await Promise.all([api<CourseDetail>(`/api/courses/${courseId}`), api<Entry[]>(`/api/courses/${courseId}/errors`)])
      const exercises = course.lessons.flatMap((l) => l.blocks.filter((b) => b.kind === 'exercise'))
      const files = await Promise.all(exercises.map((b) => api<ExerciseFile[]>(`/api/blocks/${b.id}/files`).then((f) => [b.id, f] as const)))
      setLoaded({ course, entries, files: new Map(files) })
    }
    load().catch((e: Error) => setError(e.message))
  }, [courseId])
  const course = loaded?.course

  // The print dialog proposes the page title as the file name.
  useEffect(() => {
    if (!course) return
    const before = document.title
    document.title = course.topic
    return () => {
      document.title = before
    }
  }, [course])

  return { loaded, error, setError }
}

function BookBar(props: { course: CourseDetail; pdf: boolean; preparing: boolean; onDownload: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-4 print:hidden">
      <a className={buttonVariants({ variant: 'outline' })} href={`#/course/${props.course.id}`}>{t('book.back')}</a>
      <span className="grow text-sm text-muted-foreground">{!props.pdf && t('book.saveHint')}</span>
      {props.pdf ? (
        <Button type="button" disabled={props.preparing} onClick={props.onDownload}>
          <Swap labels={[t('book.download'), t('book.preparing')]} at={props.preparing ? 1 : 0} />
        </Button>
      ) : (
        <Button type="button" onClick={() => window.print()}>
          {t('book.save')}
        </Button>
      )}
    </div>
  )
}

function Projects({ capstones }: { capstones: CourseDetail['capstones'] }) {
  const { t } = useTranslation()
  return (
    <article id="book-projects" className="book-chapter flex flex-col gap-4 print:block print:break-before-page print:[&>*+*]:mt-4">
      <header className={chapterHead}>
        <span className={cn(bookNumber, 'text-primary')}>{t('book.appendix')}</span>
        <h2 className={h2}>{t('book.projects')}</h2>
      </header>
      {capstones.map((k) => (
        <Card key={k.id} label={<span dir="auto">{k.module}</span>}>
          <h3 dir="auto">{k.title}</h3>
          <Markdown>{k.brief}</Markdown>
          <ul className="m-0 flex flex-col gap-2 ps-6">
            {k.milestones.map((m) => (
              <li key={m.id} className={m.done ? "list-['●__']" : "list-['○__']"}>
                <strong dir="auto">{m.concept}</strong> <span dir="auto">{m.deliverable}</span>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </article>
  )
}

export function Book({ courseId, learner, pdf, sketched }: { courseId: number; learner: string; pdf: boolean; sketched: boolean }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const { loaded, error, setError } = useBookData(courseId)
  const [preparing, setPreparing] = useState(false)
  const [exported] = useState(() => new Date().toISOString())

  if (!loaded) return <main className={page}>{error && <div className={errorBox}>{error}</div>}</main>
  const { course, entries, files } = loaded

  async function download(topic: string) {
    setPreparing(true)
    setError('')
    await downloadPdf(courseId, topic)
      .catch((err: Error) => setError(err.message))
      .finally(() => setPreparing(false))
  }

  const all = parts(course, t)
  const numbers = new Map(all.flatMap((p) => p.lessons).map((l, i) => [l.id, i + 1]))
  return (
    <main className="book mx-auto flex w-full max-w-[820px] flex-col gap-4 px-6 pt-6 pb-16 print:block print:max-w-none print:p-0 print:text-[10.5pt] print:[&>*+*]:mt-4">
      <style key={theme}>{pageStyle(course.topic)}</style>
      <BookBar course={course} pdf={pdf} preparing={preparing} onDownload={() => download(course.topic)} />
      {error && <div className={errorBox}>{error}</div>}

      <Cover course={course} learner={learner} exported={exported} />

      <Contents course={course} parts={all} numbers={numbers} notebook={entries.length > 0} />

      {course.concepts.length > 0 && <BookMap course={course} />}

      {all.map((part, i) => (
        <section key={i} className="flex flex-col gap-4 print:block print:[&>*+*]:mt-4">
          {part.title && (
            <header className="flex flex-col items-center gap-4 pt-16 pb-6 text-center print:break-before-page print:pt-[90mm]">
              <span className={rule} />
              <h2 className={cn(h2, 'text-3xl')} dir="auto">{part.title}</h2>
            </header>
          )}
          {part.lessons.map((l) => (
            <Chapter key={l.id} n={numbers.get(l.id)!} lesson={l} course={course} files={files} learner={learner} sketched={sketched} />
          ))}
        </section>
      ))}

      {course.capstones.length > 0 && <Projects capstones={course.capstones} />}

      {entries.length > 0 && <Notebook entries={entries} />}
    </main>
  )
}
