import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Calendar, Search, TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import type { CalendarEvent, CalendarResponse } from '../types'
import { DirectionBadge } from '../components/ui/DirectionBadge'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'

const SECTORS = ['All', 'Technology', 'Financial Services', 'Healthcare', 'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Energy', 'Communication Services']

function formatDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function daysUntil(iso: string): number {
  const d = new Date(iso)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  d.setHours(0, 0, 0, 0)
  return Math.ceil((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

export function EarningsCalendarPage() {
  const navigate = useNavigate()
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState('All')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const params = new URLSearchParams()
        params.set('days_forward', '90')
        params.set('days_back', '30')
        const res: CalendarResponse = await api.getCalendar(params)
        setEvents(res.items)
        setTotal(res.total)
        setError(null)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'failed to load calendar')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (sector !== 'All' && e.sector !== sector) return false
      if (query && !(
        e.ticker.toLowerCase().includes(query.toLowerCase()) ||
        (e.company_name ?? '').toLowerCase().includes(query.toLowerCase())
      )) return false
      return true
    })
  }, [events, query, sector])

  const stats = useMemo(() => {
    const withPrediction = events.filter((e) => e.has_prediction).length
    const upcoming7 = events.filter((e) => {
      const du = daysUntil(e.earnings_date)
      return du >= 0 && du <= 7
    }).length
    const upDirs = events.filter((e) => e.direction === 'UP').length
    return { withPrediction, upcoming7, upDirs }
  }, [events])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <h1 className="hero-headline">Earnings Intelligence Calendar</h1>
        <p className="hero-sub">
          ML-powered earnings predictions across {total} tracked events.
          Click any ticker for deep analysis and live quote.
        </p>
      </motion.div>

      <div className="grid grid-4">
        <StatCard
          label="Tracked Events"
          value={total.toLocaleString()}
          helper="rolling 120-day window"
          accent="cyan"
          delay={0.05}
        />
        <StatCard
          label="Next 7 Days"
          value={stats.upcoming7}
          helper="upcoming reports"
          accent="purple"
          delay={0.1}
        />
        <StatCard
          label="With ML Prediction"
          value={stats.withPrediction}
          helper={`${Math.round((stats.withPrediction / Math.max(total, 1)) * 100)}% coverage`}
          accent="emerald"
          delay={0.15}
        />
        <StatCard
          label="Bullish Signals"
          value={stats.upDirs}
          helper="predicted UP direction"
          accent="cyan"
          delay={0.2}
        />
      </div>

      <motion.div
        className="card"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.25 }}
      >
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: '2 1 260px' }}>
            <label className="field-label">Search</label>
            <div style={{ position: 'relative' }}>
              <Search size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }} />
              <input
                className="input"
                style={{ paddingLeft: '2.3rem' }}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ticker or company…"
              />
            </div>
          </div>
          <div style={{ flex: '1 1 200px' }}>
            <label className="field-label">Sector</label>
            <select className="select" value={sector} onChange={(e) => setSector(e.target.value)}>
              {SECTORS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div style={{ marginLeft: 'auto' }}>
            <Badge variant="live">Live data</Badge>
          </div>
        </div>
      </motion.div>

      <motion.div
        className="card"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.3 }}
        style={{ padding: 0, overflow: 'hidden' }}
      >
        {loading ? (
          <div style={{ padding: '2rem' }}>
            <div className="shimmer" style={{ height: 40, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 40, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 40 }} />
          </div>
        ) : error ? (
          <div className="empty-state">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">No events match your filters.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Company</th>
                <th>Sector</th>
                <th>Earnings Date</th>
                <th>Prediction</th>
                <th style={{ textAlign: 'right' }}>Expected Move</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, i) => {
                const du = daysUntil(e.earnings_date)
                const duLabel = du === 0 ? 'Today' : du > 0 ? `in ${du}d` : `${-du}d ago`
                return (
                  <motion.tr
                    key={`${e.ticker}-${e.earnings_date}`}
                    onClick={() => navigate(`/predict/${e.ticker}?earnings_date=${e.earnings_date}`)}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.2, delay: Math.min(i * 0.015, 0.4) }}
                  >
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '-0.01em' }}>
                      {e.ticker}
                    </td>
                    <td className="muted" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {e.company_name ?? '—'}
                    </td>
                    <td>
                      {e.sector ? <Badge variant="default">{e.sector}</Badge> : <span className="tertiary">—</span>}
                    </td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span className="mono">{formatDate(e.earnings_date)}</span>
                        <span className="tertiary" style={{ fontSize: '0.75rem' }}>{duLabel}</span>
                      </div>
                    </td>
                    <td>
                      <DirectionBadge direction={e.direction} confidence={e.confidence_score} />
                    </td>
                    <td className="mono" style={{ textAlign: 'right' }}>
                      {e.expected_move_pct != null ? `±${(e.expected_move_pct * 100).toFixed(2)}%` : <span className="tertiary">—</span>}
                    </td>
                    <td className="tertiary">
                      <TrendingUp size={14} />
                    </td>
                  </motion.tr>
                )
              })}
            </tbody>
          </table>
        )}
      </motion.div>

      <div className="tertiary" style={{ fontSize: '0.8rem', textAlign: 'center', padding: '1rem 0' }}>
        <Calendar size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
        Showing {filtered.length} of {events.length} events · Model v20260423233729 · FinBERT + 10-Q MD&A enabled
      </div>
    </div>
  )
}
