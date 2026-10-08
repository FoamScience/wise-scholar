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

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={{ code: Code }} urlTransform={imageOrSafe}>
      {children}
    </ReactMarkdown>
  )
}
