import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Completion, ExerciseFile } from './course'
import type { Editor } from './editor'
import { sameText, toDisk } from './editorSync'

const SAVE_AFTER_MS = 800

type Saved = { saved: true } | { saved: false; content: string }

export function FileEditor(props: {
  blockId: number
  file: ExerciseFile
  completions: Completion[]
  onSaving: () => void
  register: (flush: () => Promise<boolean>) => () => void
}) {
  const { t } = useTranslation()
  const { blockId, file } = props
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
        onChange: () => {
          clearTimeout(timer.current)
          timer.current = setTimeout(flush, SAVE_AFTER_MS)
        },
      })
      setLoaded(true)
    }, () => {})
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
    if (sameText(doc, content)) {
      onDisk.current = content
      showConflict(null)
    } else if (sameText(doc, onDisk.current) && conflict.current === null) {
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

  return (
    <>
      {!loaded && <pre>{content}</pre>}
      <div ref={host} className="code-editor" />
      {(status || failed) && (
        <div className={failed ? 'error small' : 'small muted'} role="status">
          {failed || (status === 'saving' ? t('exercise.saving') : t('exercise.saved'))}
        </div>
      )}
      {disk !== null && (
        <div className="row file-conflict" role="alert">
          <span className="grow">{t('exercise.conflict')}</span>
          <button
            type="button"
            className="btn"
            onClick={() => {
              onDisk.current = disk
              showConflict(null)
              editor.current?.setText(disk)
            }}
          >
            {t('exercise.useDisk')}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              onDisk.current = disk
              showConflict(null)
              flush()
            }}
          >
            {t('exercise.keepMine')}
          </button>
        </div>
      )}
    </>
  )
}
