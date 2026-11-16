import { cn } from 'cn'

/** Labels stacked in one cell so a button keeps its width when its label changes; the shown one crossfades in. */
export function Swap({ labels, at }: { labels: string[]; at: number }) {
  return (
    <span className="inline-grid">
      {labels.map((label, i) => (
        <span key={i} className={cn('col-start-1 row-start-1 transition-[opacity,visibility] duration-[var(--dur-short)] ease-[var(--ease-out)]', i !== at && 'invisible opacity-0')}>
          {label}
        </span>
      ))}
    </span>
  )
}
