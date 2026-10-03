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
import { common } from 'lowlight'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import type { PluggableList } from 'unified'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

// lowlight's common set plus the languages a tutor is likely to teach that it leaves out.
const languages = { ...common, clojure, dart, elixir, elm, erlang, fortran, haskell, julia, latex, ocaml, scala, scheme }

export const remarkPlugins: PluggableList = [remarkGfm, remarkMath]
export const rehypePlugins: PluggableList = [rehypeKatex, [rehypeHighlight, { languages, plainText: ['mermaid'] }]]
