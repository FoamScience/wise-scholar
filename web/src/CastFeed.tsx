import { useState } from 'react'
import { useTranslation } from 'react-i18next'

/** The profile's casts as a podcast feed address, for a podcast app to subscribe to. */
export function CastFeed(props: { profile: number }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const url = `${location.origin}/api/profiles/${props.profile}/casts.rss`
  return (
    <section className="block stack">
      <div className="label">{t('feed.heading')}</div>
      <div className="row">
        <code dir="ltr">{url}</code>
        <button type="button" className="btn" onClick={() => navigator.clipboard.writeText(url).then(() => setCopied(true), () => {})}>
          {copied ? t('feed.copied') : t('feed.copy')}
        </button>
      </div>
      <div className="small">{t('feed.help')}</div>
    </section>
  )
}
