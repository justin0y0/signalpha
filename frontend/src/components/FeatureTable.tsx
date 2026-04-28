type Props = {
  data: Record<string, unknown>
}

export function FeatureTable({ data }: Props) {
  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="card table-card">
      <h3>Raw and engineered features</h3>
      <div className="feature-grid">
        {entries.map(([key, value]) => (
          <div className="feature-row" key={key}>
            <div className="feature-key">{key}</div>
            <div className="feature-value">{value == null ? '—' : String(value)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
