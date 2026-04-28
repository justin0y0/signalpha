import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Activity, Target, Gauge, Layers } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { PredictionResponse } from '../types'
import { DirectionBadge } from '../components/ui/DirectionBadge'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { PriceTicker } from '../components/ui/PriceTicker'

function formatPct(v: number | null | undefined, signed = false) {
  if (v == null) return '—'
  const n = (v * 100).toFixed(2)
  return signed && v > 0 ? `+${n}%` : `${n}%`
}

function daysUntil(iso: string): number {
  const d = new Date(iso)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  d.setHours(0, 0, 0, 0)
  return Math.ceil((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

export function PredictionDeepDivePage() {
  const { ticker = '' } = useParams<{ ticker: string }>()
  const [search] = useSearchParams()
  const earningsDate = search.get('earnings_date') ?? undefined
  const [data, setData] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ticker) return
    const load = async () => {
      try {
        const r = await api.getPrediction(ticker, earningsDate)
        setData(r)
        setError(null)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'failed')
      }
    }
    load()
  }, [ticker, earningsDate])

  const convergenceData = useMemo(() => {
    if (!data?.convergence_band) return []
    const { lower, upper, current_price, horizon_days } = data.convergence_band
    if (lower == null || upper == null) return []
    const current = current_price ?? (lower + upper) / 2
    const days = horizon_days || 20
    const arr = []
    for (let i = 1; i <= days; i++) {
      const t = i / days
      arr.push({
        day: `T+${i}`,
        lower: current + (lower - current) * t,
        upper: current + (upper - current) * t,
      })
    }
    return arr
  }, [data])

  const probData = useMemo(() => {
    if (!data) return []
    return [
      { label: 'UP', value: data.direction_probabilities.up, color: 'var(--up)' },
      { label: 'FLAT', value: data.direction_probabilities.flat, color: 'var(--flat)' },
      { label: 'DOWN', value: data.direction_probabilities.down, color: 'var(--down)' },
    ]
  }, [data])

  const historicalData = useMemo(() => {
    if (!data?.historical_reactions) return []
    return data.historical_reactions.slice(-8).map((r) => ({
      date: r.earnings_date?.slice(5) ?? '—',
      reaction: r.reaction_pct != null ? r.reaction_pct * 100 : 0,
      beat: r.beat_miss ?? 'n/a',
    }))
  }, [data])

  if (error) {
    return (
      <div className="empty-state">
        <p>{error}</p>
        <Link to="/" className="btn" style={{ marginTop: '1rem' }}><ArrowLeft size={14} /> Back to Calendar</Link>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div className="shimmer" style={{ height: 140 }} />
        <div className="grid grid-4">
          <div className="shimmer" style={{ height: 110 }} />
          <div className="shimmer" style={{ height: 110 }} />
          <div className="shimmer" style={{ height: 110 }} />
          <div className="shimmer" style={{ height: 110 }} />
        </div>
        <div className="shimmer" style={{ height: 400 }} />
      </div>
    )
  }

  const du = daysUntil(data.earnings_date)
  const duLabel = du === 0 ? 'Today' : du > 0 ? `in ${du} days` : `${-du} days ago`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <Link to="/" className="btn" style={{ alignSelf: 'flex-start' }}>
        <ArrowLeft size={14} /> Calendar
      </Link>

      {/* === Hero Banner === */}
      <motion.div
        className="ticker-banner"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div style={{ flex: '1 1 320px', position: 'relative', zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.35rem' }}>
            <h1 className="ticker-symbol">{data.ticker}</h1>
            <DirectionBadge direction={data.predicted_direction} confidence={data.confidence_score} />
          </div>
          <p className="ticker-name">{data.company_name ?? '—'}</p>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {data.sector && <Badge variant="accent">{data.sector}</Badge>}
            <span className="countdown-chip">
              📅 {data.earnings_date} · {duLabel}
            </span>
            {data.report_time && <Badge variant="default">{data.report_time}</Badge>}
          </div>
        </div>
        <PriceTicker ticker={data.ticker} />
      </motion.div>

      {/* === Core Prediction Stats === */}
      <div className="grid grid-4">
        <StatCard
          label="Predicted Direction"
          value={data.predicted_direction}
          helper={`${(data.confidence_score * 100).toFixed(1)}% confidence`}
          accent={
            data.predicted_direction === 'UP'
              ? 'emerald'
              : data.predicted_direction === 'DOWN'
              ? 'rose'
              : 'default'
          }
          delay={0.05}
        />
        <StatCard
          label="Expected Move"
          value={<>±{((data.expected_move.point_estimate_pct ?? 0) * 100).toFixed(2)}%</>}
          helper={
            data.expected_move.historical_avg_pct != null
              ? `hist avg ±${(data.expected_move.historical_avg_pct * 100).toFixed(2)}%`
              : undefined
          }
          accent="cyan"
          delay={0.1}
        />
        <StatCard
          label="Convergence Band"
          value={
            data.convergence_band.lower != null && data.convergence_band.upper != null ? (
              <>
                {data.convergence_band.lower.toFixed(2)} → {data.convergence_band.upper.toFixed(2)}
              </>
            ) : (
              '—'
            )
          }
          helper={`${data.convergence_band.horizon_days}-day horizon`}
          accent="purple"
          delay={0.15}
        />
        <StatCard
          label="Data Completeness"
          value={`${(data.data_completeness * 100).toFixed(1)}%`}
          helper={`${data.warnings.length} warning${data.warnings.length === 1 ? '' : 's'}`}
          accent="emerald"
          delay={0.2}
        />
      </div>

      {/* === Direction Probabilities + Model Metadata === */}
      <div className="grid grid-2" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <div className="card-header">
            <h3 className="card-title"><Target size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Direction Probabilities</h3>
          </div>
          {probData.map((p) => (
            <div className="prob-row" key={p.label}>
              <div className="prob-label" style={{ color: p.color }}>{p.label}</div>
              <div className="prob-track">
                <motion.div
                  className="prob-fill"
                  initial={{ width: 0 }}
                  animate={{ width: `${p.value * 100}%` }}
                  transition={{ duration: 0.8, delay: 0.4, ease: 'easeOut' }}
                  style={{ background: `linear-gradient(90deg, ${p.color}, ${p.color})` }}
                />
              </div>
              <div className="prob-value">{(p.value * 100).toFixed(1)}%</div>
            </div>
          ))}
        </motion.div>

        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <div className="card-header">
            <h3 className="card-title"><Gauge size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Model Metadata</h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.85rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">Model Version</span>
              <span className="mono" style={{ fontSize: '0.8rem' }}>{data.model_version ?? '—'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">Feature Coverage</span>
              <span className="mono">{(data.data_completeness * 100).toFixed(1)}%</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">Key Drivers</span>
              <span className="mono">{data.key_drivers.length}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">Similar Cases</span>
              <span className="mono">{data.similar_cases.length}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">Warnings</span>
              <span className="mono">{data.warnings.length}</span>
            </div>
          </div>
        </motion.div>
      </div>

      {/* === Convergence Zone Chart === */}
      <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
        <div className="card-header">
          <h3 className="card-title"><Activity size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Convergence Zone — {data.convergence_band.horizon_days}-day forecast</h3>
        </div>
        <div style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={convergenceData}>
              <defs>
                <linearGradient id="zoneGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(148,163,214,0.08)" />
              <XAxis dataKey="day" tick={{ fill: '#6b7593', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fill: '#6b7593', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => v.toFixed(1)}
              />
              <Tooltip
                contentStyle={{ background: '#0f1524', border: '1px solid rgba(148,163,214,0.2)', borderRadius: 10, fontSize: 12 }}
                labelStyle={{ color: '#a8b3d1' }}
              />
              <Area type="monotone" dataKey="upper" stroke="#38bdf8" strokeWidth={1.5} fill="url(#zoneGrad)" />
              <Area type="monotone" dataKey="lower" stroke="#a78bfa" strokeWidth={1.5} fill="transparent" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </motion.div>

      {/* === Key Drivers === */}
      <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }} style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '1.25rem 1.5rem 1rem' }}>
          <h3 className="card-title"><Layers size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Key Drivers · SHAP Contributions</h3>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th style={{ textAlign: 'right' }}>Value</th>
              <th>Contribution</th>
              <th style={{ width: 100 }}>Direction</th>
            </tr>
          </thead>
          <tbody>
            {data.key_drivers.map((d, i) => {
              const maxAbs = Math.max(...data.key_drivers.map((k) => Math.abs(k.contribution)))
              const pct = (Math.abs(d.contribution) / (maxAbs || 1)) * 100
              const isPositive = d.direction === 'positive'
              return (
                <motion.tr
                  key={d.feature}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.45 + i * 0.05 }}
                  style={{ cursor: 'default' }}
                >
                  <td className="mono" style={{ fontSize: '0.8rem' }}>{d.feature}</td>
                  <td className="mono" style={{ textAlign: 'right', fontSize: '0.8rem' }}>
                    {d.value != null ? d.value.toFixed(4) : '—'}
                  </td>
                  <td style={{ minWidth: 200 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ flex: 1, height: 6, background: 'var(--bg-3)', borderRadius: 999, overflow: 'hidden', position: 'relative' }}>
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 0.6, delay: 0.5 + i * 0.05 }}
                          style={{
                            height: '100%',
                            background: isPositive ? 'linear-gradient(90deg, var(--up), #10b981)' : 'linear-gradient(90deg, var(--down), #e11d48)',
                            borderRadius: 999,
                          }}
                        />
                      </div>
                      <span className="mono" style={{ fontSize: '0.75rem', width: 56, textAlign: 'right' }}>
                        {d.contribution > 0 ? '+' : ''}{d.contribution.toFixed(4)}
                      </span>
                    </div>
                  </td>
                  <td>
                    {isPositive ? <Badge variant="up">positive</Badge> : <Badge variant="down">negative</Badge>}
                  </td>
                </motion.tr>
              )
            })}
          </tbody>
        </table>
      </motion.div>

      {/* === Historical Reactions === */}
      {historicalData.length > 0 && (
        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
          <div className="card-header">
            <h3 className="card-title">Historical Earnings Reactions · Last 8 Quarters</h3>
          </div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={historicalData}>
                <CartesianGrid strokeDasharray="2 4" stroke="rgba(148,163,214,0.08)" />
                <XAxis dataKey="date" tick={{ fill: '#6b7593', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#6b7593', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v.toFixed(0)}%`} />
                <Tooltip
                  contentStyle={{ background: '#0f1524', border: '1px solid rgba(148,163,214,0.2)', borderRadius: 10, fontSize: 12 }}
                  formatter={(v: number) => [`${v.toFixed(2)}%`, 'Reaction']}
                />
                <Bar dataKey="reaction" radius={[6, 6, 0, 0]}>
                  {historicalData.map((entry, idx) => (
                    <Bar
                      key={idx}
                      dataKey="reaction"
                      fill={entry.reaction >= 0 ? 'var(--up)' : 'var(--down)'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      )}

      {/* === Similar Cases === */}
      {data.similar_cases.length > 0 && (
        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.55 }} style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '1.25rem 1.5rem 1rem' }}>
            <h3 className="card-title">Similar Historical Cases · Nearest Neighbors</h3>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Date</th>
                <th>Sector</th>
                <th style={{ textAlign: 'right' }}>Similarity</th>
                <th style={{ textAlign: 'right' }}>T+1</th>
                <th style={{ textAlign: 'right' }}>T+5</th>
                <th style={{ textAlign: 'right' }}>T+20</th>
              </tr>
            </thead>
            <tbody>
              {data.similar_cases.slice(0, 8).map((c) => (
                <tr key={`${c.ticker}-${c.earnings_date}`} style={{ cursor: 'default' }}>
                  <td className="mono" style={{ fontWeight: 700 }}>{c.ticker}</td>
                  <td className="mono">{c.earnings_date}</td>
                  <td><span className="muted">{c.sector ?? '—'}</span></td>
                  <td className="mono" style={{ textAlign: 'right' }}>{(c.similarity * 100).toFixed(1)}%</td>
                  <td className="mono" style={{ textAlign: 'right', color: (c.actual_t1_return ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                    {formatPct(c.actual_t1_return, true)}
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: (c.actual_t5_return ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                    {formatPct(c.actual_t5_return, true)}
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: (c.actual_t20_return ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                    {formatPct(c.actual_t20_return, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>
      )}
    </div>
  )
}
