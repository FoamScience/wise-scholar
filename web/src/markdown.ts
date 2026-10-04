import clojure from 'highlight.js/lib/languages/clojure'
import dart from 'highlight.js/lib/languages/dart'
import elixir from 'highlight.js/lib/languages/elixir'
import elm from 'highlight.js/lib/languages/elm'
import erlang from 'highlight.js/lib/languages/erlang'
import fortran from 'highlight.js/lib/languages/fortran'
import haskell from 'highlight.js/lib/languages/haskell'
import julia from 'highlight.js/lib/languages/julia'
import latex from 'highlight.js/lib/languages/latex'
import ocaml from 'highlight.js/lib/languages/ocaml'
import scala from 'highlight.js/lib/languages/scala'
import scheme from 'highlight.js/lib/languages/scheme'
import type { ElementContent, Root } from 'hast'
import { common } from 'lowlight'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import type { PluggableList } from 'unified'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { textDirection } from './text'

// lowlight's common set plus the languages a tutor is likely to teach that it leaves out.
const languages = { ...common, clojure, dart, elixir, elm, erlang, fortran, haskell, julia, latex, ocaml, scala, scheme }

export const remarkPlugins: PluggableList = [remarkGfm, remarkMath]

/** A node's text without its code and math, which do not say what language the block is written in. */
function prose(node: ElementContent): string {
  if (node.type === 'text') return node.value
  if (node.type !== 'element' || node.tagName === 'code') return ''
  return node.children.map(prose).join('')
}

/** Gives each top-level block the direction most of its letters are written in, whatever direction the page has. */
function rehypeDirection() {
  return (tree: Root) => {
    for (const node of tree.children) {
      if (node.type !== 'element' || node.tagName === 'pre') continue
      const dir = textDirection(prose(node))
      if (dir) node.properties.dir = dir
    }
  }
}

// Direction runs first: math is still a code element then, so it is left out of the count.
export const rehypePlugins: PluggableList = [rehypeDirection, rehypeKatex, [rehypeHighlight, { languages, plainText: ['mermaid'] }]]
