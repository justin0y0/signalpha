export function ErrorState({ message }: { message: string }) {
  return <div className="card error-card">{message}</div>
}
