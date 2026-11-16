import i18n, { serverMessage } from './i18n'

/** The error a failed response carries: the server's detail in the interface language, else the status text. */
export async function failure(res: Response): Promise<Error> {
  const detail = (await res.json().catch(() => null))?.detail
  return new Error(typeof detail === 'string' ? serverMessage(detail) : res.statusText)
}

export async function api<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  // every change goes to the server; offline it would fail with the browser's own fetch error
  if (method !== 'GET' && !navigator.onLine) throw new Error(i18n.t('offline.needsConnection'))
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await failure(res)
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export async function transcribe(clip: Blob, lang?: string): Promise<string> {
  const form = new FormData()
  form.append('audio', clip, 'clip.webm')
  const res = await fetch(`/api/stt${lang ? `?lang=${encodeURIComponent(lang)}` : ''}`, { method: 'POST', body: form })
  if (!res.ok) throw await failure(res)
  return (await res.json()).text
}
