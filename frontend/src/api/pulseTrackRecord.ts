/**
 * One shared fetch for /pulse/track-record.
 *
 * The Pulse page mounts three components that each want this payload (the summary
 * strip, the trade log, the disclaimer line) and each polled it on its own, so every
 * load and every minute after it fired three identical requests. Calls inside the same
 * 30 s window now share one in-flight promise.
 */
const TTL_MS = 30_000
let cached: { at: number; p: Promise<any | null> } | null = null

export function fetchPulseTrackRecord(): Promise<any | null> {
  const now = Date.now()
  if (cached && now - cached.at < TTL_MS) return cached.p
  const p = fetch('/api/v1/pulse/track-record')
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
  cached = { at: now, p }
  return p
}
