import { useState } from 'react'
import { motion } from 'framer-motion'
import { Play, TrendingUp, Award, AlertCircle } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { BacktestResponse } from '../types'
import { StatCard } from '../components/ui/StatCard'
import { Badge } from '../components/ui/Badge'

const SECTORS = ['', 'Technology', 'Financial Services', 'Healthcare', 'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Energy', 'Communication Services']

export function BacktestingPage() {
  const [ticker, setTicker] = useState('')
  const [sector, setSector] = useState('')
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState('2026-04-01')
  const [threshold, setThreshold] = useState(0.55)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      const r = await api.runBacktest({
        ticker: ticker || undefined,
        sector: sector || undefined,
        start_date: startDate,
        end_date: endDate,
        probability_threshold: threshold,
      })
      setResult(r)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Backtest failed')
    } finally {
      setRunning(false)
    }
  }

  const equityData = result?.equity_curve.map((p) => {
    const d = new Date(p.date)
    return {
      date: d.toLocaleDateString('en-US', { year: '2-digit', month: 'short' }),
      equity: p.equity,
    }
  }) ?? []

  const finalReturn = equityData.length > 0 ? (equityData[equityData.length - 1].equity - 1) * 100 : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <h1 className="hero-headline">Strategy Backtesting</h1>
        <p className="hero-sub">
          Simulate the ML model's predictive edge on historical earnings events. Adjust filters and probability threshold to explore risk-return tradeoffs.
        </p>
      </motion.div>

      <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <div className="card-header">
          <h3 className="card-title">Backtest Configuration</h3>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
          <div>
            <label className="field-label">Ticker (optional)</label>
            <input className="input" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" />
          </div>
          <div>
            <label className="field-label">Sector (optional)</label>
            <select className="select" value={sector} onChange={(e) => setSector(e.target.value)}>
              {SECTORS.map((s) => <option key={s} value={s}>{s || 'All Sectors'}</option>)}
            </select>
          </div>
          <div>
            <label className="field-label">Start Date</label>
            <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="field-label">End Date</label>
            <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Confidence Threshold</label>
            <input className="input" type="number" min="0" max="1" step="0.05" value={threshold} onChange={(e) => setThreshold(parseFloat(e.target.value))} />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary" onClick={run} disabled={running} style={{ width: '100%', justifyContent: 'center' }}>
              {running ? 'Running…' : (<><Play size={14} />Run Backtest</>)}
            </button>
          </div>
        </div>
      </motion.div>

      {error && (
        <motion.div className="card" initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ borderColor: 'var(--down)', display: 'flex', alignItems: 'center', gap: 12 }}>
          <AlertCircle size={16} className="down" />
          <span>{error}</span>
        </motion.div>
      )}

      {result && (
        <>
          <div className="grid grid-4">
            <StatCard
              label="Total Samples"
              value={result.total_samples.toLocaleString()}
              helper="trades evaluated"
              accent="cyan"
              delay={0.05}
            />
            <StatCard
              label="Accuracy"
              value={`${(result.accuracy * 100).toFixed(1)}%`}
              helper={`F1: ${(result.f1_weighted * 100).toFixed(1)}%`}
              accent={result.accuracy >= 0.55 ? 'emerald' : result.accuracy >= 0.4 ? 'cyan' : 'rose'}
              delay={0.1}
            />
            <StatCard
              label="Sharpe Ratio"
              value={result.sharpe_ratio.toFixed(2)}
              helper="risk-adjusted return"
              accent={result.sharpe_ratio > 1 ? 'emerald' : result.sharpe_ratio > 0 ? 'cyan' : 'rose'}
              delay={0.15}
            />
            <StatCard
              label="Strategy Return"
              value={`${finalReturn >= 0 ? '+' : ''}${finalReturn.toFixed(2)}%`}
              helper="cumulative"
              accent={finalReturn >= 0 ? 'emerald' : 'rose'}
              delay={0.2}
            />
          </div>

          <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
            <div className="card-header">
              <h3 className="card-title"><TrendingUp size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Equity Curve</h3>
              <Badge variant={finalReturn >= 0 ? 'up' : 'down'}>
                {finalReturn >= 0 ? '+' : ''}{finalReturn.toFixed(2)}%
              </Badge>
            </div>
            {equityData.length > 0 ? (
              <div style={{ height: 340 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityData}>
                    <defs>
                      <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={finalReturn >= 0 ? '#34d399' : '#fb7185'} stopOpacity={0.4} />
                        <stop offset="100%" stopColor={finalReturn >= 0 ? '#34d399' : '#fb7185'} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="2 4" stroke="rgba(148,163,214,0.08)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: '#6b7593', fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      minTickGap={40}
                    />
                    <YAxis
                      domain={['auto', 'auto']}
                      tick={{ fill: '#6b7593', fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v) => {
                        if (v >= 1000) return `${(v/1000).toFixed(0)}kx`
                        if (v >= 100) return `${v.toFixed(0)}x`
                        if (v >= 2) return `${v.toFixed(1)}x`
                        return `${((v - 1) * 100).toFixed(0)}%`
                      }}
                    />
                    <Tooltip
                      contentStyle={{ background: '#0f1524', border: '1px solid rgba(148,163,214,0.2)', borderRadius: 10, fontSize: 12 }}
                      formatter={(v: number) => {
                        if (v >= 2) return [`${v.toFixed(2)}x capital`, 'Equity']
                        return [`${((v - 1) * 100).toFixed(2)}%`, 'Return']
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="equity"
                      stroke={finalReturn >= 0 ? '#34d399' : '#fb7185'}
                      strokeWidth={2}
                      fill="url(#equityGrad)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="empty-state">No equity curve data</div>
            )}
          </motion.div>

          <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <div className="card-header">
              <h3 className="card-title"><Award size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Performance Metrics</h3>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
              {[
                { label: 'Precision', val: result.precision_weighted, pct: true },
                { label: 'Recall', val: result.recall_weighted, pct: true },
                { label: 'F1 Score', val: result.f1_weighted, pct: true },
                { label: 'MAE', val: result.mae ?? 0, pct: false },
                { label: 'RMSE', val: result.rmse ?? 0, pct: false },
              ].map((m) => (
                <div key={m.label} style={{ padding: '0.85rem', background: 'var(--bg-2)', borderRadius: 10, border: '1px solid var(--border)' }}>
                  <div className="tertiary" style={{ fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>{m.label}</div>
                  <div className="mono" style={{ fontSize: '1.3rem', fontWeight: 700, marginTop: 4 }}>
                    {m.pct ? `${(m.val * 100).toFixed(1)}%` : m.val.toFixed(4)}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </>
      )}

      {!result && !error && (
        <div className="empty-state" style={{ padding: '4rem 1rem' }}>
          <Play size={32} style={{ opacity: 0.4, marginBottom: 12 }} />
          <p>Configure parameters above and click Run Backtest to simulate the strategy.</p>
        </div>
      )}
    </div>
  )
}
