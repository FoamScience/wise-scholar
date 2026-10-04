import { useTranslation } from 'react-i18next'

export type NetworkData = {
  command: string
  status: 'asked' | 'running' | 'allowed' | 'refused'
  result: { exit_code: number | null; output: string } | null
}

/** The tutor's request to run one command with internet: the learner reads the command and decides. */
export function NetworkCard(props: { id: number; reason: string; data: unknown; disabled: boolean; onDecide?: (allow: boolean) => void }) {
  const { t } = useTranslation()
  const d = props.data as NetworkData
  return (
    <section id={`block-${props.id}`} className="block network">
      <div className="label">
        {t('network.label')}
        {d.status === 'allowed' && <span className="chip">{t('network.allowed')}</span>}
        {d.status === 'refused' && <span className="chip warn">{t('network.refused')}</span>}
      </div>
      <div dir="auto">{props.reason}</div>
      <pre>
        <code>$ {d.command}</code>
      </pre>
      {d.status === 'asked' && props.onDecide && (
        <>
          <div className="small">{t('network.explain')}</div>
          <div className="row">
            <button type="button" className="btn" disabled={props.disabled} onClick={() => props.onDecide?.(false)}>
              {t('network.refuse')}
            </button>
            <button type="button" className="btn primary" disabled={props.disabled} onClick={() => props.onDecide?.(true)}>
              {t('network.allow')}
            </button>
          </div>
        </>
      )}
      {d.status === 'running' && <div className="muted">{t('network.running')}</div>}
      {d.result && (
        <div className="file">
          <div className="file-head">
            <span className="label">{d.result.exit_code === null ? t('network.stopped') : t('network.exit', { code: d.result.exit_code })}</span>
          </div>
          <pre className={d.result.exit_code === 0 ? '' : 'failed'}>{d.result.output || t('exercise.noOutput')}</pre>
        </div>
      )}
    </section>
  )
}
