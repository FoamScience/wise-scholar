import { diffWords } from 'diff'
import { useState } from 'react'
import Markdown from './Md'

/** The learner's text against its correction, word by word; a toggle shows the clean corrected text instead. */
export function Correction({ attempt, corrected }: { attempt: string; corrected: string }) {
  const [clean, setClean] = useState(false)
  const parts = diffWords(attempt, corrected)
  const changed = parts.some((p) => p.added || p.removed)
  return (
    <div className="correction">
      {clean || !changed ? (
        <Markdown>{corrected}</Markdown>
      ) : (
        <p className="word-diff">
          {parts.map((p, i) =>
            p.removed ? (
              <del key={i}>{p.value}</del>
            ) : p.added ? (
              <ins key={i}>{p.value}</ins>
            ) : (
              <span key={i}>{p.value}</span>
            ),
          )}
        </p>
      )}
      {changed && (
        <button type="button" className="link" onClick={() => setClean(!clean)}>
          {clean ? 'Show the changes' : 'Show the clean text'}
        </button>
      )}
      {!changed && <div className="small">No changes: your text already matched.</div>}
    </div>
  )
}
