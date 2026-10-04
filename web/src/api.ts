import { serverMessage } from './i18n'

/** The error a failed response carries: the server's detail in the interface language, else the status text. */
export async function failure(res: Response): Promise<Error> {
  const detail = (await res.json().catch(() => null))?.detail
  return new Error(typeof detail === 'string' ? serverMessage(detail) : res.statusText)
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await failure(res)
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}
