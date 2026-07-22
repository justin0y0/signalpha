import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, TrendingUp, TrendingDown, Check, AlertTriangle } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { StockLogo } from './StockLogo'
import { useT } from '../i18n'

interface Props { ticker: string | null; onClose: () => void }
interface Detail {
  ticker: string
  in_universe: boolean
  pulse: any
  active_signal: any
  earnings_history: any[]
  price_series: number[]
}

type EBProps = { children: React.ReactNode; fallback: React.ReactNode }
type EBState = { hasError: boolean; msg: string }
class ErrorBoundary extends React.Component<EBProps, EBState> {
  constructor(props: EBProps) { super(props); this.state = { hasError: false, msg: '' } }
  static getDerivedStateFromError(err: any) { return { hasError: true, msg: String((err && err.message) || err) } }
  componentDidCatch(err: any) { console.error('TickerDetailModal Body crashed:', err) }
  render() {
    if (this.state.hasError) return <div className="tdp-loading"><div>Error: {this.state.msg.slice(0, 80)}</div></div>
    return this.props.children
  }
}

function fmt(v: any, digits = 2, prefix = ''): string {
  if (v === null || v === undefined || typeof v !== 'number' || isNaN(v)) return '—'
  return prefix + v.toFixed(digits)
}
function fmtSigned(v: any, digits = 2): string {
  if (v === null || v === undefined || typeof v !== 'number' || isNaN(v)) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(digits)
}

export function TickerDetailModal({ ticker, onClose }: Props) {
  const { t } = useT()
  const [data, setData] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!ticker) { setData(null); return }
    setLoading(true)
    fetch(`/api/v1/pulse/ticker/${ticker}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [ticker])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <AnimatePresence>
      {ticker && (
        <>
          <motion.div className="tdp-scrim"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose} />
          <motion.aside className="tdp-panel"
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 32, stiffness: 320 }}>
            <button className="tdp-close" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
            {loading && !data && (
              <div className="tdp-loading">Loading {ticker}…</div>
            )}
            {!loading && !data && (
              <div className="tdp-loading">
                <div>Failed to load {ticker}</div>
                <div style={{ fontSize: '0.7rem', marginTop: '0.5rem', color: 'var(--text-tertiary)' }}>
                  Press Esc or click outside to close
                </div>
              </div>
            )}
            {data && (
              <ErrorBoundary fallback={<div className="tdp-loading">{t('render.error')}</div>}>
                <Body data={data} />
              </ErrorBoundary>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function Body({ data }: { data: Detail }) {
  const { t } = useT()
  const p = data?.pulse || null
  const sig = data?.active_signal || null
  const earnings = Array.isArray(data?.earnings_history) ? data.earnings_history : []
  const spark = Array.isArray(data?.price_series)
    ? data.price_series.map((v: number, i: number) => ({ i, v }))
    : []
  const sparkChange = spark.length > 1 && spark[0].v > 0
    ? (spark[spark.length - 1].v / spark[0].v - 1)
    : 0

  return (
    <div className="tdp-body">
      <div className="tdp-head">
        <div className="tdp-head__logo">
          <StockLogo ticker={data.ticker || '?'} size={56} />
        </div>
        <div className="tdp-head__id">
          <div className="tdp-head__ticker">{data.ticker || '?'}</div>
          <div className="tdp-head__meta">
            {p ? (
              <>
                <span className="tdp-head__price">{fmt(p.price, 2, '$')}</span>
                {p.sector && (
                  <span className="tdp-head__sector" style={{ color: '#a78bfa' }}>{p.sector}</span>
                )}
                {p.session && typeof p.session === 'string' && p.session !== 'market' && (
                  <span className="tdp-head__session">{p.session.replace('_', '-').toUpperCase()}</span>
                )}
              </>
            ) : (
              <span>{t('ticker.notInUniverse')}</span>
            )}
          </div>
        </div>
      </div>

      {sig && (
        <motion.div className="tdp-card tdp-card--signal"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          style={{ borderColor: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
          <div className="tdp-card__top">
            <span className="tdp-label">ACTIVE SIGNAL · {
              sig.primary === 'AL_REVERSION' ? 'Avellaneda-Lee'
              : sig.primary === 'GAO_MOMENTUM' ? 'Gao 2018'
              : sig.primary === 'CONNORS' ? 'Connors RSI(2)'
              : (sig.primary || '—')
            }</span>
            <span className="tdp-side" style={{ color: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
              {sig.side === 'LONG' ? <TrendingUp size={14} /> : <TrendingDown size={14} />} {sig.side}
            </span>
          </div>
          <div className="tdp-bigscore" style={{ color: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
            {fmtSigned(sig.score, 2)}
          </div>
          <div className="tdp-card__row">
            <span>Size · <b>${(sig.suggested_size || 0).toLocaleString()}</b></span>
            <span>P(win) · <b>{((sig.estimated_prob || 0) * 100).toFixed(0)}%</b></span>
          </div>
        </motion.div>
      )}

      {spark.length > 5 && (
        <motion.div className="tdp-card"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <div className="tdp-card__top">
            <span className="tdp-label">PRICE · LAST 5 DAYS</span>
            <span style={{ fontSize: '0.78rem', color: sparkChange >= 0 ? '#4ade80' : '#f87171', fontWeight: 700 }}>
              {sparkChange >= 0 ? '+' : ''}{(sparkChange * 100).toFixed(2)}%
            </span>
          </div>
          <div style={{ height: 90, marginTop: '0.4rem' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={spark}>
                <YAxis hide domain={['dataMin', 'dataMax']} />
                <Tooltip content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="mc-tt"><b className="mono">${(payload[0].value as number).toFixed(2)}</b></div>
                  ) : null
                } />
                <Line type="monotone" dataKey="v"
                  stroke={sparkChange >= 0 ? '#4ade80' : '#f87171'}
                  strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      )}

      {p && (
        <motion.div className="tdp-card"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <div className="tdp-label">PULSE SIGNALS</div>
          <div className="tdp-grid">
            <Stat label="s-score" value={fmtSigned(p.s_score, 2)}
              color={typeof p.s_score === 'number' && Math.abs(p.s_score) > 1.25 ? (p.s_score > 0 ? '#f87171' : '#4ade80') : undefined} />
            <Stat label="Half-life" value={typeof p.half_life_bars === 'number' ? `${p.half_life_bars.toFixed(0)} bars` : '—'} />
            <Stat label="beta market" value={fmt(p.beta_market, 2)} />
            <Stat label="beta sector" value={fmt(p.beta_sector, 2)} />
            <Stat label="RSI(2)" value={fmt(p.rsi2, 0)}
              color={typeof p.rsi2 === 'number' && p.rsi2 > 90 ? '#f87171' : typeof p.rsi2 === 'number' && p.rsi2 < 10 ? '#4ade80' : undefined} />
            <Stat label="ATR(20)" value={fmt(p.atr20, 2, '$')} />
            <Stat label="Vol z" value={fmtSigned(p.vol_z, 1) + 'σ'}
              color={typeof p.vol_z === 'number' && Math.abs(p.vol_z) > 2 ? '#fbbf24' : undefined} />
            <Stat label="Regime" value={p.regime_up ? 'Above 200' : 'Below 200'}
              color={p.regime_up ? '#4ade80' : '#f87171'} />
          </div>
        </motion.div>
      )}

      {sig && Array.isArray(sig.factors) && sig.factors.length > 0 && (
        <motion.div className="tdp-card"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <div className="tdp-label">SIGNAL ATTRIBUTION</div>
          <div className="tdp-factors">
            {sig.factors.map((f: any, i: number) => (
              <div key={i} className="tdp-factor">
                <span>{(f && f.label) || '—'}</span>
                <b style={{ color: (f && f.value) >= 0 ? '#4ade80' : '#f87171', fontFamily: 'var(--font-mono)' }}>
                  {fmtSigned(f && f.value, 2)}
                </b>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      <motion.div className="tdp-card"
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <div className="tdp-label">EARNINGS HISTORY · LAST 6</div>
        {earnings.length === 0 ? (
          <div className="tdp-empty">No earnings history for {data.ticker} in our database.</div>
        ) : (
          <div className="tdp-eh">
            {earnings.map((e: any, i: number) => (
              <div key={i} className="tdp-eh__row">
                <div className="tdp-eh__period mono">{(e && e.period) || '—'}</div>
                <div className="tdp-eh__pred">
                  <div className="tdp-eh__plabel">PRED</div>
                  <div className="tdp-eh__pval" style={{
                    color: e && e.predicted_label === 'UP' ? '#4ade80' :
                           e && e.predicted_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)'
                  }}>{(e && e.predicted_label) || '—'}</div>
                </div>
                <div className="tdp-eh__act">
                  <div className="tdp-eh__plabel">ACTUAL</div>
                  <div className="tdp-eh__pval" style={{
                    color: e && e.actual_label === 'UP' ? '#4ade80' :
                           e && e.actual_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)'
                  }}>
                    {e && !e.is_past
                      ? <span style={{ color: '#fbbf24' }}>PENDING</span>
                      : ((e && e.actual_label) || '—')}
                  </div>
                </div>
                <div className="tdp-eh__move mono" style={{
                  color: !e || e.actual_move_pct == null ? 'var(--text-tertiary)' :
                         e.actual_move_pct > 0 ? '#4ade80' : '#f87171'
                }}>
                  {e && typeof e.actual_move_pct === 'number'
                    ? `${e.actual_move_pct >= 0 ? '+' : ''}${(e.actual_move_pct * 100).toFixed(2)}%`
                    : '—'}
                </div>
                <div className="tdp-eh__win">
                  {!e || e.win == null
                    ? <span style={{ color: 'var(--text-tertiary)' }}>—</span>
                    : e.win
                      ? <Check size={16} color="#4ade80" />
                      : <AlertTriangle size={16} color="#f87171" />}
                </div>
              </div>
            ))}
          </div>
        )}
      </motion.div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="tdp-stat">
      <div className="tdp-stat__l">{label}</div>
      <div className="tdp-stat__v mono" style={{ color }}>{value}</div>
    </div>
  )
}
