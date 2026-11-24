import { isValidElement, useMemo } from 'react'
import type { ComponentProps, ComponentType, ReactNode } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import Mermaid from './Mermaid'
import { boardLink } from './ink'
import { pinPlot } from './parts'
import { inlineRemarkPlugins, rehypePlugins, remarkPlugins } from './markdown'
import { rehypeWords } from './wordStates'

function Code(props: ComponentProps<'code'>) {
  const { className, children, node: _, ...rest } = props as ComponentProps<'code'> & { node?: unknown }
  if (className?.includes('language-mermaid')) return <Mermaid code={String(children).replace(/\n$/, '')} />
  return (
    <code className={className} {...rest}>
      {children}
    </code>
  )
}

// A diagram is drawn in place of its code block, so it does not sit in a code box.
function Pre(props: ComponentProps<'pre'>) {
  const { children, node: _, ...rest } = props as ComponentProps<'pre'> & { node?: unknown }
  if (isValidElement<{ className?: string }>(children) && children.props.className?.includes('language-mermaid')) return children
  return <pre {...rest}>{children}</pre>
}

// Figures in a hand-out travel as inline SVG data URLs; everything else keeps react-markdown's safe list.
function imageOrSafe(url: string): string {
  return url.startsWith('data:image/svg+xml;base64,') ? url : defaultUrlTransform(url)
}

// `[term](#part-id)` names a part of a figure in the lesson: the term and the part light up together (see parts.ts).
function Link(props: ComponentProps<'a'>) {
  const { href, children, node: _, ...rest } = props as ComponentProps<'a'> & { node?: unknown }
  const point = href?.match(/^#plot-(\d+)-x=(-?[\d.]+(?:e[-+]?\d+)?)$/i)
  if (point)
    return (
      <button type="button" className="term" onClick={() => pinPlot(Number(point[1]), Number(point[2]))}>
        {children}
      </button>
    )
  // `[the sum](#board-12-main.sum)` names an element (or a mark) of board block 12: see InkBoard.tsx.
  const board = boardLink(href)
  if (board)
    return (
      <span className="term" role="button" data-board={board.block} data-board-ref={board.ref} tabIndex={0}>
        {children}
      </span>
    )
  const part = href?.match(/^#part-([-\w]+)$/)?.[1]
  if (part)
    return (
      <span className="term" data-ref={part} tabIndex={0}>
        {children}
      </span>
    )
  return (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}

function Table(props: ComponentProps<'table'>) {
  const { node: _, ...rest } = props as ComponentProps<'table'> & { node?: unknown }
  return (
    <div className="max-w-full overflow-x-auto">
      <table {...rest} />
    </div>
  )
}

// Typography's own quote marks double the ones the tutor writes; right-to-left scripts have no italic to slant.
const PROSE =
  'prose prose-ws max-w-none text-[length:inherit] leading-[inherit] prose-headings:font-heading prose-headings:font-semibold prose-h2:mt-6 prose-h2:mb-2 prose-h2:text-lg prose-h3:text-base prose-p:my-4 prose-code:font-normal prose-code:before:content-none prose-code:after:content-none prose-pre:my-2 prose-pre:rounded-md prose-table:my-2 prose-table:w-full [&_blockquote]:[quotes:none] [&_:where(blockquote,em,i):dir(rtl)]:not-italic'

const COMPONENTS = { code: Code, pre: Pre, a: Link, table: Table }
type WordOf = ComponentType<{ word: string; sentence: string }>

/** words draws each word of a text in lang, which makes it tappable. */
export default function Markdown({ children, words }: { children: string; words?: { lang: string; as: WordOf } }) {
  const lang = words?.lang
  // words are wrapped before math is typeset, as direction is: math is still a code element then
  const plugins = useMemo(() => (lang === undefined ? rehypePlugins : [[rehypeWords, { lang }] as [typeof rehypeWords, { lang: string }], ...rehypePlugins]), [lang])
  const components = words ? ({ ...COMPONENTS, 'tap-word': words.as } as typeof COMPONENTS) : COMPONENTS
  return (
    <div className={PROSE}>
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={plugins} components={components} urlTransform={imageOrSafe}>
        {children}
      </ReactMarkdown>
    </div>
  )
}

function Bare({ children }: { children?: ReactNode }) {
  return <>{children}</>
}

/** Math and inline marks for text that sits inside a heading, a button, a chip or a sentence. */
export function InlineMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={inlineRemarkPlugins} rehypePlugins={rehypePlugins} components={{ code: Code, a: Link, p: Bare }} urlTransform={imageOrSafe}>
      {children}
    </ReactMarkdown>
  )
}

/** An answer as given. Typed text stays verbatim, so `a*b*c` keeps its stars, unless it holds math; a picked option is the tutor's text. */
export function AnswerText({ text, picked }: { text: string; picked?: boolean }) {
  return <span dir="auto">{picked || /\$[^$\n]+\$/.test(text) ? <InlineMarkdown>{text}</InlineMarkdown> : text}</span>
}
