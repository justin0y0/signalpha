import { useEffect, useState } from 'react'

/** /api/v1/direction, fetched once per page load and shared by every reader. */
let pending: Promise<any> | null = null

export function loadDirection(): Promise<any> {
  if (!pending) pending = fetch('/api/v1/direction').then((r) => (r.ok ? r.json() : Promise.reject(r.status))).catch((e) => { pending = null; throw e })
  return pending
}

export function useDirection<T = any>(): { data: T | null; error: boolean } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true
    loadDirection().then((d) => { if (alive) setData(d) }).catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [])
  return { data, error }
}
