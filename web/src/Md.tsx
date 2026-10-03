import ReactMarkdown from 'react-markdown'
import { rehypePlugins, remarkPlugins } from './markdown'
import 'katex/dist/katex.min.css'

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
      {children}
    </ReactMarkdown>
  )
}
