import type { BacktestResponse, CalendarResponse, PerformanceResponse, PredictionResponse } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export type QuoteResponse = {
  ticker: string
  price: number
  previous_close: number
  change: number
  change_pct: number
  sparkline: number[]
  as_of: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(errorText || `Request failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  getCalendar: (search: URLSearchParams) => request<CalendarResponse>(`/calendar?${search.toString()}`),
  getPrediction: (ticker: string, earningsDate?: string) => {
    const params = new URLSearchParams()
    if (earningsDate) params.set('earnings_date', earningsDate)
    return request<PredictionResponse>(`/predict/${ticker}?${params.toString()}`)
  },
  getFeatures: (ticker: string, earningsDate?: string) => {
    const params = new URLSearchParams()
    if (earningsDate) params.set('earnings_date', earningsDate)
    return request<Record<string, unknown>>(`/features/${ticker}?${params.toString()}`)
  },
  runBacktest: (payload: { ticker?: string; sector?: string; start_date: string; end_date: string; probability_threshold: number }) =>
    request<BacktestResponse>('/backtest', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getPerformance: () => request<PerformanceResponse>('/performance'),
  getQuote: (ticker: string) => request<QuoteResponse>(`/quote/${ticker}`),
}
