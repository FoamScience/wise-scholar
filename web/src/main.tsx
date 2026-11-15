import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import 'katex/dist/katex.min.css'
import App from './App.tsx'
import { linkParts } from './parts'

// Production only: in development a cached copy would hide the edits being made. Without HTTPS (other than
// localhost) the browser refuses it and the app works as before, online only.
if (import.meta.env.PROD && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {})

// a page left open across a rebuild asks for chunks the server no longer has; the new build has them. Once a minute
// at most, so a chunk that is missing for another reason (offline) does not reload the page in a loop.
window.addEventListener('vite:preloadError', () => {
  const last = Number(sessionStorage.getItem('reloadedForBuild') ?? 0)
  if (Date.now() - last < 60_000) return
  sessionStorage.setItem('reloadedForBuild', String(Date.now()))
  location.reload()
})

linkParts()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
