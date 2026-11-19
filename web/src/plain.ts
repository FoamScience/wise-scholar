// the server's MARK (wise_scholar/search.py) around matched words
const OPEN = '\ue000'
const CLOSE = '\ue001'
const SYMBOLS: Record<string, string> = { approx: '≈', ge: '≥', le: '≤', times: '×', cdot: '·', sigma: 'σ' }

/** Text without its Markdown and LaTeX marks, for a one-line mention. */
export function plain(markdown: string): string {
  return markdown
    .replace(/\\(?:text|mathrm|mathbf|operatorname)\{([^}]*)\}?/g, '$1')
    .replace(/\\([a-zA-Z]+)/g, (_, name: string) => SYMBOLS[name] ?? name)
    .replace(/\\([^a-zA-Z\s])/g, '$1')
    .replace(/[$*`#>{}]+/g, '')
    .replace(new RegExp(`(?<![\\w${OPEN}${CLOSE}])_+|_+(?![\\w${OPEN}${CLOSE}])`, 'g'), '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** A search snippet's [piece, matched] parts stripped of marks as one text, so a mark may open in one piece and close in another. */
export function plainParts(parts: [string, boolean][]): [string, boolean][] {
  const marked = plain(parts.map(([piece, matched]) => (matched ? `${OPEN}${piece}${CLOSE}` : piece)).join(''))
  return marked
    .split(new RegExp(`${OPEN}(.*?)${CLOSE}`, 's'))
    .map((piece, i): [string, boolean] => [piece, i % 2 === 1])
    .filter(([piece]) => piece)
}
