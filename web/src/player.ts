import { useEffect, useRef, useState } from 'react'
import { failure } from './api'
import i18n from './i18n'

const SLOW_RATE = 0.8

/** Plays sentences one after another through the local voice, or the browser voice when speech is off. */
export function usePlayer(lang: string, local: boolean) {
  const [current, setCurrent] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const [error, setError] = useState('')
  const audio = useRef<HTMLAudioElement | null>(null)
  const slowRef = useRef(false)
  const run = useRef(0)

  function stop() {
    run.current += 1
    audio.current?.pause()
    audio.current = null
    speechSynthesis.cancel()
    setCurrent(null)
  }

  useEffect(() => stop, [])

  function setSlowRate(on: boolean) {
    slowRef.current = on
    setSlow(on)
    if (audio.current) audio.current.playbackRate = on ? SLOW_RATE : 1
  }

  async function play(sentences: string[]) {
    stop()
    const mine = run.current
    setError('')
    const url = (s: string) => `/api/tts?lang=${encodeURIComponent(lang)}&text=${encodeURIComponent(s)}`
    for (let i = 0; i < sentences.length && run.current === mine; i++) {
      setCurrent(sentences[i])
      if (local) {
        if (i + 1 < sentences.length) fetch(url(sentences[i + 1])).catch(() => {})
        const res = await fetch(url(sentences[i])).catch(() => null)
        if (run.current !== mine) return
        if (!res?.ok) {
          setError(res ? (await failure(res)).message : i18n.t('speaking.voiceSilent'))
          break
        }
        const src = URL.createObjectURL(await res.blob())
        const clip = new Audio(src)
        clip.playbackRate = slowRef.current ? SLOW_RATE : 1
        audio.current = clip
        await new Promise<void>((done) => {
          clip.onended = () => done()
          clip.onerror = () => done()
          clip.play().catch(() => done())
        })
        URL.revokeObjectURL(src)
      } else {
        await new Promise<void>((done) => {
          const u = new SpeechSynthesisUtterance(sentences[i])
          u.lang = lang
          u.rate = slowRef.current ? SLOW_RATE : 1
          u.onend = () => done()
          u.onerror = () => done()
          speechSynthesis.speak(u)
        })
      }
    }
    if (run.current === mine) setCurrent(null)
  }

  return { current, slow, setSlow: setSlowRate, error, play, stop }
}
