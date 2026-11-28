import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Completion, ExerciseFile } from './course'
import type { Editor } from './editor'
import { sameText, toDisk } from './editorSync'
import type { DiffSummary } from './editorSync'
import { Button } from '@/components/ui/button'
import { cn } from 'cn'

const SAVE_AFTER_MS = 800

type Saved = { saved: true } | { saved: false; content: string }

/** What an incoming disk text means for the open document: take it as the saved copy, replace the document with it, or flag a conflict. */
function reconcile(doc: string, content: string, onDisk: string, conflicted: boolean): 'adopt' | 'replace' | 'conflict' {
  if (sameText(doc, content)) return 'adopt'
  return sameText(doc, onDisk) && !conflicted ? 'replace' : 'conflict'
}

function StatusLine(props: { status: '' | 'saving' | 'saved'; failed: string }) {
  const { t } = useTranslation()
  const { status, failed } = props
  if (!status && !failed) return null
  return (
    <div className={cn('px-4 py-1 text-sm text-muted-foreground', failed && 'rounded-md bg-warm-tint')} role="status">
      {failed || (status === 'saving' ? t('exercise.saving') : t('exercise.saved'))}
    </div>
  )
}

function ConflictBar(props: { onUseDisk: () => void; onKeepMine: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-2" role="alert">
      <span className="grow">{t('exercise.conflict')}</span>
      <Button type="button" variant="outline" onClick={props.onUseDisk}>
        {t('exercise.useDisk')}
      </Button>
      <Button type="button" variant="outline" onClick={props.onKeepMine}>
        {t('exercise.keepMine')}
      </Button>
    </div>
  )
}

export function FileEditor(props: {
  blockId: number
  file: ExerciseFile
  completions: Completion[]
  original: string | null
  onDiff: (summary: DiffSummary) => void
  onDiffFailed: () => void
  onSaving: () => void
  register: (flush: () => Promise<boolean>) => () => void
}) {
  const { blockId, file, original } = props
  const path = file.path
  const content = file.content ?? ''
  const host = useRef<HTMLDivElement>(null)
  const editor = useRef<Editor | null>(null)
  const onDisk = useRef(content)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const queue = useRef<Promise<boolean>>(Promise.resolve(true))
  const conflict = useRef<string | null>(null)
  const latest = useRef(props)
  const [disk, setDisk] = useState<string | null>(null)
  const [status, setStatus] = useState<'' | 'saving' | 'saved'>('')
  const [failed, setFailed] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [unloadable, setUnloadable] = useState(false)

  useEffect(() => {
    latest.current = props
  })

  function showConflict(text: string | null) {
    conflict.current = text
    setDisk(text)
  }

  async function save(): Promise<boolean> {
    const doc = editor.current?.text()
    if (doc === undefined || conflict.current !== null) return conflict.current === null
    if (sameText(doc, onDisk.current)) return true
    const text = toDisk(doc, onDisk.current)
    latest.current.onSaving()
    setStatus('saving')
    setFailed('')
    try {
      const result = await api<Saved>(`/api/blocks/${blockId}/files`, { path, content: text, base: onDisk.current })
      latest.current.onSaving()
      if (!result.saved) {
        setStatus('')
        showConflict(result.content)
        return false
      }
      onDisk.current = text
      setStatus('saved')
      return true
    } catch (err) {
      latest.current.onSaving()
      setStatus('')
      setFailed((err as Error).message)
      return false
    }
  }

  function flush() {
    clearTimeout(timer.current)
    queue.current = queue.current.then(save)
    return queue.current
  }

  useEffect(() => {
    let gone = false
    import('./editor').then(({ createEditor }) => {
      if (gone || !host.current) return
      editor.current = createEditor({
        parent: host.current,
        text: onDisk.current,
        path,
        label: path,
        completions: latest.current.completions,
        readOnly: latest.current.file.online,
        onDiff: (summary) => latest.current.onDiff(summary),
        onChange: () => {
          clearTimeout(timer.current)
          timer.current = setTimeout(flush, SAVE_AFTER_MS)
        },
      })
      setLoaded(true)
    }, () => !gone && setUnloadable(true))
    const unregister = latest.current.register(flush)
    return () => {
      gone = true
      unregister()
      const open = editor.current
      flush().finally(() => {
        open?.destroy()
        if (editor.current === open) editor.current = null
      })
    }
  }, [path]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const open = editor.current
    if (!open) {
      onDisk.current = content
      return
    }
    if (sameText(content, onDisk.current)) return
    const doc = open.text()
    const action = reconcile(doc, content, onDisk.current, conflict.current !== null)
    if (action === 'adopt') {
      onDisk.current = content
      showConflict(null)
    } else if (action === 'replace') {
      onDisk.current = content
      open.setText(content)
      setStatus('')
    } else {
      showConflict(content)
    }
  }, [content])

  useEffect(() => {
    editor.current?.setReadOnly(file.online)
  }, [file.online])

  useEffect(() => {
    if (loaded) editor.current?.setDiff(original).catch(() => latest.current.onDiffFailed())
    else if (unloadable && original !== null) latest.current.onDiffFailed()
  }, [loaded, unloadable, original])

  return (
    <>
      {!loaded && <pre className="m-0 max-h-[420px] overflow-auto rounded-none">{content}</pre>}
      <div ref={host} className="code-editor" dir="ltr" />
      <StatusLine status={status} failed={failed} />
      {disk !== null && (
        <ConflictBar
          onUseDisk={() => {
            onDisk.current = disk
            showConflict(null)
            editor.current?.setText(disk)
          }}
          onKeepMine={() => {
            onDisk.current = disk
            showConflict(null)
            flush()
          }}
        />
      )}
    </>
  )
}
