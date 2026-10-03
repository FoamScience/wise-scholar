import type { ComponentProps } from 'react'
import ReactMarkdown from 'react-markdown'
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

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={{ code: Code }}>
      {children}
    </ReactMarkdown>
  )
}
