/**
 * Date helpers for the API's date-only fields.
 *
 * `new Date('2026-07-21')` is parsed by JS as UTC midnight. Rendered with
 * `toLocaleDateString` anywhere west of Greenwich that becomes the PREVIOUS day —
 * so in US Pacific the whole earnings calendar showed every event one day early,
 * and the "Today / in 3d" countdown was off by one with it.
 *
 * Use `parseLocalDate` for anything the backend types as DATE (earnings_date,
 * target_exit_date, equity-curve dates). Timestamp columns (TIMESTAMPTZ:
 * executed_at, entry_time, snapshot_at, ...) carry an explicit offset and must go
 * through `new Date()` directly — do NOT route those through here.
 */

/** Parse a `YYYY-MM-DD` string as local midnight instead of UTC midnight. */
export function parseLocalDate(iso: string): Date {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  return new Date(dateOnly ? `${iso}T00:00:00` : iso)
}

/** "Jul 21, 2026" */
export function formatDate(iso: string): string {
  return parseLocalDate(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** "Tue, Jul 21" */
export function formatDateShort(iso: string): string {
  return parseLocalDate(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

/** Whole days from today to `iso`. 0 = today, positive = future. */
export function daysUntil(iso: string): number {
  const d = parseLocalDate(iso)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  d.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}

/** "Today" / "in 3d" / "5d ago" */
export function countdownLabel(iso: string): string {
  const d = daysUntil(iso)
  return d === 0 ? 'Today' : d > 0 ? `in ${d}d` : `${-d}d ago`
}
