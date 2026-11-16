import { diffWords } from 'diff'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Md'
import { Button } from '@/components/ui/button'

/** The learner's text against its correction, word by word; a toggle shows the clean corrected text instead. */
export function Correction({ attempt, corrected }: { attempt: string; corrected: string }) {
  const { t } = useTranslation()
  const [clean, setClean] = useState(false)
  const parts = diffWords(attempt, corrected)
  const changed = parts.some((p) => p.added || p.removed)
  return (
    <div>
      {clean || !changed ? (
        <Markdown>{corrected}</Markdown>
      ) : (
        <p className="mt-0 mb-2 whitespace-pre-wrap" dir="auto">
          {parts.map((p, i) =>
            p.removed ? (
              <del key={i} className="text-warm line-through decoration-2">
                {p.value}
              </del>
            ) : p.added ? (
              <ins key={i} className="text-accent-foreground underline decoration-2 underline-offset-3">
                {p.value}
              </ins>
            ) : (
              <span key={i}>{p.value}</span>
            ),
          )}
        </p>
      )}
      {changed && (
        <Button type="button" variant="ghost" className="text-ink-2 in-[.book]:hidden" onClick={() => setClean(!clean)}>
          {clean ? t('notebook.showChanges') : t('notebook.showClean')}
        </Button>
      )}
      {!changed && <div className="text-sm text-muted-foreground">{t('notebook.noChanges')}</div>}
    </div>
  )
}
