/** Labels stacked in one cell so a button keeps its width when its label changes; the shown one crossfades in. */
export function Swap({ labels, at }: { labels: string[]; at: number }) {
  return (
    <span className="swap">
      {labels.map((label, i) => (
        <span key={i} className={i === at ? 'on' : undefined}>
          {label}
        </span>
      ))}
    </span>
  )
}
