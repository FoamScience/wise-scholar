import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { NetworkCard } from './Network'
import { api, failure } from './api'
import { parts, timeline } from './chapters'
import { challengeLabel, lessonTitle } from './course'
import type { Block, ChallengeData, Concept, CourseDetail, ExerciseData, ExerciseFile, Lesson, QuestionData, SpeakingData } from './course'
import { Correction } from './Diff'
import type { Entry } from './Errors'
import type { FigureData } from './Figure'
import { HintList, Ladder } from './Ladder'
import { day, lookup, percent } from './i18n'
import { TIER_WORDS } from './Language'
import type { ReadingData, VocabData } from './Language'
import Logo from './Logo'
import { PlotCard } from './PlotCard'
import type { PodcastData } from './Podcast'
import { QuizResult } from './Quiz'
import { ScopeCard } from './Scope'
import type { Graded, QuizData } from './Quiz'
import { textDirection } from './text'
import { useTheme } from './theme'

type Files = Map<number, ExerciseFile[]>

function conceptStatus(concept: Concept, started: boolean, t: TFunction): string {
  if (concept.known) return t('map.placedOut')
  if (!started) return t('map.notStarted')
  return concept.mastery === null ? t('map.started') : t('map.mastery', { n: Math.round(concept.mastery * 3) })
}

function Card(props: { label: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`block ${props.className ?? ''}`}>
      <div className="label">{props.label}</div>
      {props.children}
    </section>
  )
}

function QuizBlock({ block }: { block: Block }) {
  const { t } = useTranslation()
  const d = block.data as QuizData
  return (
    <Card label={d.pretest ? t('quiz.pretest') : t('quiz.quickCheck')} className="quiz">
      <Markdown>{block.markdown}</Markdown>
      {d.kind === 'choice' && (
        <ul className="book-options" dir={textDirection(d.options.join(' '))}>
          {d.options.map((o) => (
            <li key={o} className={o === d.answer ? 'picked' : undefined}>
              <Markdown>{o}</Markdown>
            </li>
          ))}
        </ul>
      )}
      {d.answer === null ? (
        <div className="muted">{t('book.unanswered')}</div>
      ) : d.correct === undefined ? (
        <div className="attempt">
          <span className="label">{t('quiz.grading', { percent: percent(d.confidence!) })}</span>
          <span dir={textDirection(d.answer)}>{d.answer}</span>
        </div>
      ) : (
        <QuizResult answer={d.answer} confidence={d.confidence!} result={d as Graded} feedback={d.feedback} />
      )}
    </Card>
  )
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
        <dl className="book-glossary">
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
      {files.map((f) => (
        <div key={f.path} className="file">
          <div className="file-head">
            <code>{f.path}</code>
          </div>
          {f.content === null ? (
            <pre>{t('exercise.missing')}</pre>
          ) : (
            <div className="file-body">
              <Markdown>{`\`\`\`\`${f.path.split('.').pop() ?? ''}\n${f.content}\n\`\`\`\``}</Markdown>
            </div>
          )}
        </div>
      ))}
      <code>$ {d.run}</code>
      {d.last_run && (
        <div className="file">
          <div className="file-head">
            <span className="label">
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

function BookBlock({ block, files }: { block: Block; files: Files }) {
  const { t } = useTranslation()
  const solvedChip = (d: ChallengeData) => d.solved && <span className="chip">{d.writing ? t('common.done') : t('common.solved')}</span>

  if (block.kind === 'quiz') return <QuizBlock block={block} />
  if (block.kind === 'reading') return <ReadingBlock block={block} />
  if (block.kind === 'exercise') return <ExerciseBlock block={block} files={files.get(block.id) ?? []} />
  if (block.kind === 'plot') return <PlotCard id={block.id} title={block.markdown} data={block.data} />
  if (block.kind === 'network') return <NetworkCard id={block.id} reason={block.markdown} data={block.data} disabled />
  if (block.kind === 'question') {
    const d = block.data as QuestionData
    return (
      <Card label={t('card.question')} className="question">
        <h3 dir="auto">{block.markdown}</h3>
        {d.answer === null ? (
          <div className="muted">{t('book.unanswered')}</div>
        ) : (
          <span className="chip" dir="auto">
            {d.answer}
          </span>
        )}
      </Card>
    )
  }
  if (block.kind === 'challenge') {
    const d = block.data as ChallengeData
    return (
      <Card
        label={
          <>
            {challengeLabel(d, false, t)}
            {solvedChip(d)}
          </>
        }
        className="challenge"
      >
        <Markdown>{block.markdown}</Markdown>
        <Ladder data={d} />
      </Card>
    )
  }
  if (block.kind === 'speaking') {
    const d = block.data as SpeakingData
    return (
      <Card
        label={
          <>
            {d.speaking === 'shadow' ? t('speaking.shadow') : t('speaking.read')}
            {solvedChip(d)}
          </>
        }
        className="challenge"
      >
        <p className="spoken-text" lang={d.lang} dir="auto">
          {block.markdown}
        </p>
        {d.scores.map((a, i) => (
          <div key={i} className="attempt">
            <span className="label">{t('speaking.attemptScore', { n: i + 1, score: percent(a.score) })}</span>
            {a.heard !== null && <span lang={d.lang} dir="auto">{a.heard}</span>}
          </div>
        ))}
        <HintList data={d} />
      </Card>
    )
  }
  if (block.kind === 'vocab') {
    const d = block.data as VocabData
    return (
      <Card label={t('card.vocab')}>
        {d.rounds.map((r) => (
          <div key={r.tier}>{t('vocab.round', { n: r.tier * TIER_WORDS, known: r.known.length, total: r.words.length })}</div>
        ))}
        {d.tier && (
          <div>
            {t('vocab.yours')} <span className="chip">{t('vocab.tier', { tier: d.tier })}</span> {t('vocab.working', { n: d.tier * TIER_WORDS })}
          </div>
        )}
      </Card>
    )
  }
  if (block.kind === 'podcast') {
    const d = block.data as PodcastData
    return (
      <Card label={`${d.cues.length ? t('cast.quiz') : t('cast.recap')} · ${t('cast.transcript')}`}>
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
  if (block.kind === 'figure') {
    const d = block.data as FigureData
    return (
      <Card label={t('block.figure')} className="figure">
        <div className="figure-box" role="img" aria-label={d.alt} dangerouslySetInnerHTML={{ __html: d.svg }} />
        {block.markdown && <div className="caption">{block.markdown}</div>}
      </Card>
    )
  }
  if (block.kind === 'placement')
    return (
      <Card
        label={
          <>
            {t('block.placementResult')} <span className="chip">{(block.data as { level: string }).level}</span>
          </>
        }
      >
        <Markdown>{block.markdown}</Markdown>
      </Card>
    )
  return (
    <Card label={lookup(`block.${block.kind}`, block.kind)}>
      <Markdown>{block.markdown}</Markdown>
    </Card>
  )
}

function Plan({ course }: { course: CourseDetail }) {
  const { t } = useTranslation()
  return (
    <Card label={t('plan.heading')}>
      <ol className="book-plan">
        {course.ranking.map((r) => (
          <li key={r.mechanism}>
            <strong>{lookup(`playbooks.${r.mechanism}.title`, r.title)}</strong>
            {r.mechanism === course.mechanism && <span className="chip">{t('book.chosen')}</span>}
            <div dir="auto">{r.rationale}</div>
            <div className="muted">{lookup(`playbooks.${r.mechanism}.summary`, r.summary)}</div>
            <div className="evidence">
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

function Chapter(props: { n: number; lesson: Lesson; course: CourseDetail; files: Files; learner: string }) {
  const { t } = useTranslation()
  const { lesson, course } = props
  const lastPlacement = course.lessons.filter((l) => l.phase === 'placement').at(-1)
  return (
    <article id={`book-lesson-${lesson.id}`} className="book-chapter">
      <header className="book-chapter-head">
        <span className="book-number">{t('book.chapter', { n: props.n })}</span>
        <h2 dir="auto">{lessonTitle(lesson, t)}</h2>
      </header>
      {lesson.phase === 'interview' && <ScopeCard course={course} />}
      {timeline(lesson).map((item) =>
        'block' in item ? (
          <BookBlock key={`b${item.block.id}`} block={item.block} files={props.files} />
        ) : (
          <div key={`m${item.message.id}`} className={`book-turn ${item.message.role}`}>
            <span className="label">{item.message.role === 'learner' ? props.learner : t('chat.tutor')}</span>
            {item.message.role === 'learner' ? (
              <div className="bubble learner">
                <span dir={textDirection(item.message.text)}>{item.message.text}</span>
              </div>
            ) : (
              <div className="bubble">
                <Markdown>{item.message.text}</Markdown>
              </div>
            )}
          </div>
        ),
      )}
      {lesson.phase === 'interview' && course.ranking.length > 0 && <Plan course={course} />}
      {lesson.id === lastPlacement?.id && course.placement && !lesson.blocks.some((b) => b.kind === 'placement') && (
        <Card
          label={
            <>
              {t('block.placementResult')} <span className="chip">{course.level}</span>
            </>
          }
        >
          <Markdown>{course.placement}</Markdown>
        </Card>
      )}
    </article>
  )
}

function Notebook({ entries }: { entries: Entry[] }) {
  const { t } = useTranslation()
  return (
    <article id="book-notebook" className="book-chapter">
      <header className="book-chapter-head">
        <span className="book-number">{t('book.appendix')}</span>
        <h2>{t('review.errorNotebook')}</h2>
      </header>
      {entries.map((e) => (
        <Card
          key={e.id}
          label={
            <>
              {e.kind === 'writing' ? t('common.correctedText') : t('notebook.confidentMiss')} · {day(e.created)}
              {e.pinned ? <span className="chip">{t('notebook.pinned')}</span> : null}
              {e.resolved ? <span className="chip">{t('notebook.resolve')}</span> : null}
            </>
          }
          className="entry"
        >
          {e.kind === 'quiz' && <Markdown>{e.prompt}</Markdown>}
          <div className="attempt">
            <span className="label">{e.kind === 'writing' ? t('notebook.youWrote') : t('notebook.youSaid')}</span>
            <span dir={textDirection(e.said)}>{e.said}</span>
          </div>
          <div className="solution">
            <div className="label">{e.kind === 'writing' ? t('notebook.corrected') : t('notebook.rightAnswer')}</div>
            {e.kind === 'writing' ? <Correction attempt={e.said} corrected={e.correct} /> : <Markdown>{e.correct}</Markdown>}
            {e.explanation && <Markdown>{e.explanation}</Markdown>}
          </div>
          {e.note && (
            <div className="hint">
              <div className="label">{t('book.yourNote')}</div>
              <span dir={textDirection(e.note)}>{e.note}</span>
            </div>
          )}
        </Card>
      ))}
    </article>
  )
}

/** Running head and page number sit in the page margins, which only take literal values: read them from the live theme. */
function pageStyle(topic: string): string {
  const css = getComputedStyle(document.documentElement)
  const text = `font-family: ${css.getPropertyValue('--mono')}; font-size: 8pt; color: ${css.getPropertyValue('--muted')};`
  // A CSS string: anything outside letters, digits and spaces goes in as a hex escape.
  const quoted = `"${topic.replace(/[^\p{L}\p{N} ]/gu, (c) => `\\${c.codePointAt(0)!.toString(16)} `)}"`
  return `@page { background: ${css.getPropertyValue('--ground')}; @top-center { content: ${quoted}; ${text} } @bottom-center { content: counter(page); ${text} } }
@page :first { margin: 0; @top-center { content: none } @bottom-center { content: none } }`
}

/** A whole course laid out as a book. The server prints this same page to a PDF, so the file has the site's theme and type;
 * without the PDF extra the browser's print dialog does it. */
export function Book({ courseId, learner, pdf }: { courseId: number; learner: string; pdf: boolean }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const [loaded, setLoaded] = useState<{ course: CourseDetail; entries: Entry[]; files: Files } | null>(null)
  const [error, setError] = useState('')
  const [preparing, setPreparing] = useState(false)
  const [exported] = useState(() => new Date().toISOString())

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

  if (!loaded || !course) return <main className="home">{error && <div className="error">{error}</div>}</main>
  const { entries, files } = loaded

  async function download(topic: string) {
    setPreparing(true)
    setError('')
    try {
      const res = await fetch(`/api/courses/${courseId}/book.pdf?theme=${document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'}`)
      if (!res.ok) throw await failure(res)
      const link = document.createElement('a')
      link.href = URL.createObjectURL(await res.blob())
      link.download = `${topic}.pdf`
      link.click()
      // Revoking at once can cancel the download before the browser has read the blob.
      setTimeout(() => URL.revokeObjectURL(link.href), 60_000)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPreparing(false)
    }
  }

  const all = parts(course, t)
  const numbers = new Map(all.flatMap((p) => p.lessons).map((l, i) => [l.id, i + 1]))
  const jump = (id: string) => (e: { preventDefault: () => void }) => {
    e.preventDefault()
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <main className="book">
      <style key={theme}>{pageStyle(course.topic)}</style>
      <div className="book-bar">
        <a href={`#/course/${course.id}`}>{t('book.back')}</a>
        <span className="grow small">{!pdf && t('book.saveHint')}</span>
        {pdf ? (
          <button type="button" className="btn primary" disabled={preparing} onClick={() => download(course.topic)}>
            {preparing ? t('book.preparing') : t('book.download')}
          </button>
        ) : (
          <button type="button" className="btn primary" onClick={() => window.print()}>
            {t('book.save')}
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}

      <header className="book-cover">
        <Logo size={56} />
        <span className="book-number">{t('book.kicker')}</span>
        <h1 dir="auto">{course.topic}</h1>
        <span className="book-rule" />
        {course.mechanism && <div className="book-subtitle">{lookup(`playbooks.${course.mechanism}.title`, course.mechanism)}</div>}
        <div className="grow" />
        <div>
          {learner}
          {course.level && ` · ${t('map.level')} ${course.level}`}
        </div>
        <div className="book-number">{t('book.exported', { date: day(exported) })}</div>
      </header>

      <nav className="book-contents">
        <h2>{t('book.contents')}</h2>
        {all.map((part, i) => (
          <div key={i}>
            {part.title && (
              <div className="book-number" dir="auto">
                {part.title}
              </div>
            )}
            <ol>
              {part.lessons.map((l) => (
                <li key={l.id} value={numbers.get(l.id)}>
                  <a href={`#book-lesson-${l.id}`} onClick={jump(`book-lesson-${l.id}`)} dir="auto">
                    {lessonTitle(l, t)}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        ))}
        {(course.capstones.length > 0 || entries.length > 0) && (
          <ul>
            {course.capstones.length > 0 && (
              <li>
                <a href="#book-projects" onClick={jump('book-projects')}>
                  {t('book.projects')}
                </a>
              </li>
            )}
            {entries.length > 0 && (
              <li>
                <a href="#book-notebook" onClick={jump('book-notebook')}>
                  {t('review.errorNotebook')}
                </a>
              </li>
            )}
          </ul>
        )}
      </nav>

      {course.concepts.length > 0 && (
        <section className="book-map">
          <h2>{t('map.label')}</h2>
          {[...new Set(course.concepts.map((c) => c.module))].map((module) => (
            <div key={module}>
              <h3 dir="auto">{module}</h3>
              <ul>
                {course.concepts
                  .filter((c) => c.module === module)
                  .map((c) => (
                    <li key={c.id}>
                      <span dir="auto">{c.title}</span>
                      <span className="muted">{conceptStatus(c, course.lessons.some((l) => l.concept_id === c.id), t)}</span>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </section>
      )}

      {all.map((part, i) => (
        <section key={i} className="book-part">
          {part.title && (
            <header className="book-part-head">
              <span className="book-rule" />
              <h2 dir="auto">{part.title}</h2>
            </header>
          )}
          {part.lessons.map((l) => (
            <Chapter key={l.id} n={numbers.get(l.id)!} lesson={l} course={course} files={files} learner={learner} />
          ))}
        </section>
      ))}

      {course.capstones.length > 0 && (
        <article id="book-projects" className="book-chapter">
          <header className="book-chapter-head">
            <span className="book-number">{t('book.appendix')}</span>
            <h2>{t('book.projects')}</h2>
          </header>
          {course.capstones.map((k) => (
            <Card key={k.id} label={<span dir="auto">{k.module}</span>}>
              <h3 dir="auto">{k.title}</h3>
              <Markdown>{k.brief}</Markdown>
              <ul className="book-milestones">
                {k.milestones.map((m) => (
                  <li key={m.id} className={m.done ? 'done' : undefined}>
                    <strong dir="auto">{m.concept}</strong> <span dir="auto">{m.deliverable}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </article>
      )}

      {entries.length > 0 && <Notebook entries={entries} />}
    </main>
  )
}
