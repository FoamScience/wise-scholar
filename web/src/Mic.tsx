import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

/** Push-to-talk: records while pressed, sends the clip to the recogniser, hands back the transcript. */
export function Mic(props: { onClip: (clip: Blob) => Promise<void>; onError: (message: string) => void; label?: string; disabled?: boolean; limit?: number }) {
  const { t } = useTranslation()
  const [recording, setRecording] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const timer = useRef<number | undefined>(undefined)

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = []
      const rec = new MediaRecorder(stream)
      rec.ondataavailable = (e) => chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        props.onClip(new Blob(chunks, { type: rec.mimeType })).catch((err: Error) => props.onError(err.message))
      }
      rec.start()
      recorder.current = rec
      setRecording(true)
      if (props.limit) timer.current = window.setTimeout(stop, props.limit * 1000)
    } catch (err) {
      props.onError((err as Error).message)
    }
  }

  function stop() {
    window.clearTimeout(timer.current)
    recorder.current?.stop()
    recorder.current = null
    setRecording(false)
  }

  return (
    <button
      type="button"
      className={recording ? 'btn recording' : 'btn'}
      disabled={props.disabled && !recording}
      aria-label={recording ? t('speaking.stopRecording') : (props.label ?? t('speaking.speakMessage'))}
      title={recording ? t('speaking.stopRecording') : (props.label ?? t('speaking.speakMessage'))}
      onClick={recording ? stop : start}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
      {recording ? ` ${t('common.stop')}` : props.label ? ` ${props.label}` : ''}
    </button>
  )
}
