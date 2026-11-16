import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

/** The profile's casts as a podcast feed address, for a podcast app to subscribe to. */
export function CastFeed(props: { profile: number }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const url = `${location.origin}/api/profiles/${props.profile}/casts.rss`
  return (
    <section className="block space-y-3 border-t border-border pt-6">
      <div className="text-sm leading-snug font-medium text-ink-2">{t('feed.heading')}</div>
      <div className="flex flex-wrap items-center gap-3">
        <code dir="ltr">{url}</code>
        <Button type="button" variant="outline" onClick={() => navigator.clipboard.writeText(url).then(() => setCopied(true), () => {})}>
          {copied ? t('feed.copied') : t('feed.copy')}
        </Button>
      </div>
      <div className="text-sm text-muted-foreground">{t('feed.help')}</div>
    </section>
  )
}
