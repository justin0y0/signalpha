export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div className="card">{label}</div>
}
