import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import 'katex/dist/katex.min.css'
import App from './App.tsx'

// Production only: in development a cached copy would hide the edits being made. Without HTTPS (other than
// localhost) the browser refuses it and the app works as before, online only.
if (import.meta.env.PROD && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
