import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, BarChart3, Grid3x3, Target, TrendingUp } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { PerformanceResponse } from '../types'
import { StatCard } from '../components/ui/StatCard'
import { Badge } from '../components/ui/Badge'

function accuracyColor(acc: number | null | undefined): string {
  if (acc == null) return 'var(--text-tertiary)'
  if (acc >= 0.65) return 'var(--up)'
  if (acc >= 0.5) return 'var(--accent-cyan)'
  if (acc >= 0.4) return 'var(--accent-amber)'
  return 'var(--down)'
}

function heatmapBg(acc: number | null | undefined): string {
  if (acc == null) return 'transparent'
  const v = acc
  if (v >= 0.65) return `rgba(52, 211, 153, ${Math.min(v * 0.5, 0.4)})`
  if (v >= 0.5) return `rgba(56, 189, 248, ${Math.min(v * 0.4, 0.3)})`
  if (v >= 0.4) return `rgba(251, 191, 36, ${Math.min(v * 0.35, 0.25)})`
  return `rgba(251, 113, 133, ${Math.min((0.5 - v) * 0.6, 0.3)})`
}

export function PerformanceTrackerPage() {
  const [data, setData] = useState<PerformanceResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getPerformance().then(setData).catch((e: Error) => setError(e.message))
  }, [])

  const sortedSectors = useMemo(() => {
    if (!data) return []
    return [...data.by_sector].sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0))
  }, [data])

  const generalRow = useMemo(() => sortedSectors.find((s) => s.sector === 'general') ?? null, [sortedSectors])
  const bestRow = useMemo(() => sortedSectors.find((s) => s.sector !== 'general') ?? null, [sortedSectors])
  const worstRow = useMemo(
    () => [...sortedSectors].reverse().find((s) => s.sector !== 'general') ?? null,
    [sortedSectors],
  )

  const topFeatures = useMemo(() => {
    if (!data) return []
    return [...data.feature_importance].slice(0, 12).sort((a, b) => a.importance - b.importance)
  }, [data])

  const cmTotals = useMemo(() => {
    if (!data) return { total: 0 }
    const total = data.confusion_matrix.flat().reduce((acc, v) => acc + v, 0)
    return { total }
  }, [data])

  if (error) return <div className="empty-state">{error}</div>
  if (!data) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div className="shimmer" style={{ height: 100 }} />
        <div className="shimmer" style={{ height: 300 }} />
        <div className="shimmer" style={{ height: 400 }} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <h1 className="hero-headline">Model Performance Tracker</h1>
        <p className="hero-sub">
          Sector-level accuracy, confusion matrix, and SHAP feature attribution ·
          Model version <span className="mono" style={{ color: 'var(--accent-cyan)' }}>{data.model_version ?? '—'}</span>
        </p>
      </motion.div>

      <div className="grid grid-4">
        <StatCard
          label="Overall Accuracy"
          value={generalRow?.accuracy != null ? `${(generalRow.accuracy * 100).toFixed(1)}%` : '—'}
          helper={generalRow ? `F1: ${((generalRow.f1_weighted ?? 0) * 100).toFixed(1)}%` : undefined}
          accent="cyan"
          delay={0.05}
        />
        <StatCard
          label="Best Sector"
          value={bestRow?.sector ?? '—'}
          helper={bestRow?.accuracy != null ? `${(bestRow.accuracy * 100).toFixed(1)}% accuracy` : undefined}
          accent="emerald"
          delay={0.1}
        />
        <StatCard
          label="Worst Sector"
          value={worstRow?.sector ?? '—'}
          helper={worstRow?.accuracy != null ? `${(worstRow.accuracy * 100).toFixed(1)}% accuracy` : undefined}
          accent="rose"
          delay={0.15}
        />
        <StatCard
          label="Total Samples"
          value={cmTotals.total.toLocaleString()}
          helper={`${data.by_sector.length} sectors evaluated`}
          accent="purple"
          delay={0.2}
        />
      </div>

      <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }} style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '1.25rem 1.5rem 1rem' }}>
          <h3 className="card-title"><Grid3x3 size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Per-Sector Performance · Accuracy Heatmap</h3>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Sector</th>
              <th style={{ textAlign: 'right' }}>Accuracy</th>
              <th style={{ textAlign: 'right' }}>Precision</th>
              <th style={{ textAlign: 'right' }}>Recall</th>
              <th style={{ textAlign: 'right' }}>F1</th>
              <th style={{ textAlign: 'right' }}>MAE</th>
              <th style={{ textAlign: 'right' }}>Sharpe</th>
            </tr>
          </thead>
          <tbody>
            {sortedSectors.map((s, i) => (
              <motion.tr
                key={s.sector}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.3 + i * 0.04 }}
                style={{ background: heatmapBg(s.accuracy), cursor: 'default' }}
              >
                <td style={{ fontWeight: 600 }}>
                  {s.sector === 'general' ? <Badge variant="accent">General</Badge> : s.sector}
                </td>
                <td className="mono" style={{ textAlign: 'right', fontWeight: 700, color: accuracyColor(s.accuracy) }}>
                  {s.accuracy != null ? `${(s.accuracy * 100).toFixed(1)}%` : '—'}
                </td>
                <td className="mono" style={{ textAlign: 'right' }}>{s.precision_weighted != null ? `${(s.precision_weighted * 100).toFixed(1)}%` : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{s.recall_weighted != null ? `${(s.recall_weighted * 100).toFixed(1)}%` : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{s.f1_weighted != null ? `${(s.f1_weighted * 100).toFixed(1)}%` : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{s.mae != null ? s.mae.toFixed(3) : '—'}</td>
                <td className="mono" style={{ textAlign: 'right', color: (s.sharpe_ratio ?? 0) > 0 ? 'var(--up)' : 'var(--down)' }}>
                  {s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : '—'}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </motion.div>

      <div className="grid grid-2">
        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
          <div className="card-header">
            <h3 className="card-title"><BarChart3 size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Top Feature Importance · SHAP</h3>
          </div>
          <div style={{ height: 380 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topFeatures} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="rgba(148,163,214,0.08)" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#6b7593', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="feature"
                  tick={{ fill: '#a8b3d1', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                  axisLine={false}
                  tickLine={false}
                  width={150}
                />
                <Tooltip
                  contentStyle={{ background: '#0f1524', border: '1px solid rgba(148,163,214,0.2)', borderRadius: 10, fontSize: 12 }}
                  formatter={(v: number) => [v.toFixed(4), 'Importance']}
                />
                <Bar dataKey="importance" radius={[0, 6, 6, 0]}>
                  {topFeatures.map((_, i) => (
                    <Cell key={i} fill={`hsl(${195 - i * 5}, 70%, ${55 + i}%)`} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 }}>
          <div className="card-header">
            <h3 className="card-title"><Target size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />Confusion Matrix</h3>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '80px repeat(3, 1fr)', gap: 2, marginTop: '0.5rem' }}>
            <div></div>
            {['↑ UP', '→ FLAT', '↓ DOWN'].map((lbl) => (
              <div key={lbl} className="tertiary" style={{ textAlign: 'center', fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.08em', padding: '0.5rem 0' }}>
                Pred {lbl}
              </div>
            ))}
            {['UP', 'FLAT', 'DOWN'].map((actual, i) => {
              const rowSum = data.confusion_matrix[i]?.reduce((a, b) => a + b, 0) ?? 1
              return (
                <div key={actual} style={{ display: 'contents' }}>
                  <div className="tertiary" style={{ fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.08em', padding: '0.85rem 0', textAlign: 'right', paddingRight: '0.75rem' }}>
                    Actual {actual}
                  </div>
                  {data.confusion_matrix[i]?.map((v, j) => {
                    const pct = rowSum > 0 ? v / rowSum : 0
                    const isCorrect = i === j
                    return (
                      <motion.div
                        key={j}
                        initial={{ scale: 0.85, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ delay: 0.5 + (i * 3 + j) * 0.04 }}
                        style={{
                          padding: '1rem',
                          background: isCorrect
                            ? `rgba(52, 211, 153, ${0.12 + pct * 0.3})`
                            : `rgba(251, 113, 133, ${0.05 + pct * 0.2})`,
                          border: `1px solid ${isCorrect ? 'rgba(52,211,153,0.3)' : 'var(--border)'}`,
                          borderRadius: 8,
                          textAlign: 'center',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          minHeight: 70,
                        }}
                      >
                        <div className="mono" style={{ fontSize: '1.25rem', fontWeight: 700, color: isCorrect ? 'var(--up)' : 'var(--text-secondary)' }}>
                          {v}
                        </div>
                        <div className="tertiary" style={{ fontSize: '0.7rem', marginTop: 4 }}>
                          {(pct * 100).toFixed(0)}%
                        </div>
                      </motion.div>
                    )
                  })}
                </div>
              )
            })}
          </div>
          <div className="tertiary" style={{ fontSize: '0.75rem', marginTop: '1rem', textAlign: 'center' }}>
            Rows = actual direction · Columns = predicted direction · Greener = more correct
          </div>
        </motion.div>
      </div>

      <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>
        <Activity size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
        Trained on walk-forward splits · 35-feature ensemble (XGBoost + LightGBM + LogReg) · FinBERT + 10-Q MD&A
      </div>
    </div>
  )
}
