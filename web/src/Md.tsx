import type { ComponentProps } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import Mermaid from './Mermaid'
import { rehypePlugins, remarkPlugins } from './markdown'

function Code(props: ComponentProps<'code'>) {
  const { className, children, ...rest } = props
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
