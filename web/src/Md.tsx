import type { ComponentProps, ReactNode } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import Mermaid from './Mermaid'
import { inlineRemarkPlugins, rehypePlugins, remarkPlugins } from './markdown'

function Code(props: ComponentProps<'code'>) {
  const { className, children, node: _, ...rest } = props as ComponentProps<'code'> & { node?: unknown }
  if (className?.includes('language-mermaid')) return <Mermaid code={String(children).replace(/\n$/, '')} />
  return (
    <code className={className} {...rest}>
      {children}
    </code>
  )
}

// Figures in a hand-out travel as inline SVG data URLs; everything else keeps react-markdown's safe list.
function imageOrSafe(url: string): string {
  return url.startsWith('data:image/svg+xml;base64,') ? url : defaultUrlTransform(url)
}

// `[term](#part-id)` names a part of a figure in the lesson: the term and the part light up together (see parts.ts).
function Link(props: ComponentProps<'a'>) {
  const { href, children, node: _, ...rest } = props as ComponentProps<'a'> & { node?: unknown }
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

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={{ code: Code, a: Link }} urlTransform={imageOrSafe}>
      {children}
    </ReactMarkdown>
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
