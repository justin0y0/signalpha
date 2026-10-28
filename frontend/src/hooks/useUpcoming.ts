import { useEffect, useState } from 'react'
import type { CalendarEvent } from '../types'

/**
 * Reports in the next three weeks (the tape's horizon), fetched once and shared by the
 * tape and the command palette.
 */
let cache: Promise<CalendarEvent[]> | null = null

export function loadUpcoming(): Promise<CalendarEvent[]> {
  if (!cache) {
    cache = fetch('/api/v1/calendar?days_forward=21&days_back=0')
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => (d.items ?? []) as CalendarEvent[])
      .catch(() => { cache = null; return [] })
  }
  return cache
}

export function useUpcoming(): CalendarEvent[] {
  const [items, setItems] = useState<CalendarEvent[]>([])
  useEffect(() => { let alive = true; loadUpcoming().then((x) => { if (alive) setItems(x) }); return () => { alive = false } }, [])
  return items
}
