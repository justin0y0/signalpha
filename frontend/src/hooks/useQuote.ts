import { useEffect, useState } from 'react'
import { api, type QuoteResponse } from '../api/client'

export function useQuote(ticker: string | undefined, intervalMs = 60_000) {
  const [data, setData] = useState<QuoteResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ticker) return
    let cancelled = false
    let timerId: ReturnType<typeof setTimeout>

    const fetchNow = async () => {
      setLoading(true)
      try {
        const q = await api.getQuote(ticker)
        if (!cancelled) {
          setData(q)
          setError(null)
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'quote error')
      } finally {
        if (!cancelled) setLoading(false)
        if (!cancelled) timerId = setTimeout(fetchNow, intervalMs)
      }
    }
    fetchNow()
    return () => {
      cancelled = true
      clearTimeout(timerId)
    }
  }, [ticker, intervalMs])

  return { data, loading, error }
}
