type ProbabilityBarProps = {
  label: string
  value: number
}

export function ProbabilityBar({ label, value }: ProbabilityBarProps) {
  return (
    <div className="probability-row">
      <div className="probability-label">{label}</div>
      <div className="probability-track">
        <div className="probability-fill" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
      </div>
      <div className="probability-value">{(value * 100).toFixed(1)}%</div>
    </div>
  )
}
