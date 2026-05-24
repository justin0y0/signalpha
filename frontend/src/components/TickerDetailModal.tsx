import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, TrendingUp, TrendingDown, Check, AlertTriangle, ExternalLink } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { StockLogo } from './StockLogo'

interface Props { ticker: string | null; onClose: () => void }
interface Detail {
  ticker: string; in_universe: boolean
  pulse: any; active_signal: any
  earnings_history: any[]; price_series: number[]
}

export function TickerDetailModal({ ticker, onClose }: Props) {
  const [data, setData] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!ticker) { setData(null); return }
    setLoading(true)
    fetch(`/api/v1/pulse/ticker/${ticker}`)
      .then(r => r.json()).then(setData).catch(() => setData(null))
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
          <motion.div
            className="tdp-scrim"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose} />
          <motion.aside
            className="tdp-panel"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 32, stiffness: 320 }}>
            <button className="tdp-close" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
            {loading && !data && <div className="tdp-loading">Loading {ticker}…</div>}
            {data && <Body data={data} />}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function Body({ data }: { data: Detail }) {
  const p = data.pulse
  const sig = data.active_signal
  const spark = (data.price_series || []).map((v, i) => ({ i, v }))
  const sparkMin = spark.length ? Math.min(...spark.map(s => s.v)) : 0
  const sparkMax = spark.length ? Math.max(...spark.map(s => s.v)) : 0
  const sparkChange = spark.length > 1 ? (spark[spark.length-1].v / spark[0].v - 1) : 0

  return (
    <div className="tdp-body">
      {/* Header */}
      <div className="tdp-head">
        <div className="tdp-head__logo">
          <StockLogo ticker={data.ticker} size={56} />
        </div>
        <div className="tdp-head__id">
          <div className="tdp-head__ticker">{data.ticker}</div>
          <div className="tdp-head__meta">
            {p ? (
              <>
                <span className="tdp-head__price">${p.price.toFixed(2)}</span>
                <span className="tdp-head__sector" style={{ color: '#a78bfa' }}>{p.sector}</span>
                {p.session && p.session !== 'market' && (
                  <span className="tdp-head__session">{p.session.replace('_','-').toUpperCase()}</span>
                )}
              </>
            ) : <span>Not in active universe</span>}
          </div>
        </div>
      </div>

      {sig && (
        <motion.div
          className="tdp-card tdp-card--signal"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          style={{ borderColor: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
          <div className="tdp-card__top">
            <span className="tdp-label">ACTIVE SIGNAL · {sig.primary === 'AL_REVERSION' ? 'Avellaneda-Lee' : sig.primary === 'GAO_MOMENTUM' ? 'Gao 2018' : sig.primary === 'CONNORS' ? 'Connors RSI(2)' : sig.primary}</span>
            <span className="tdp-side" style={{ color: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
              {sig.side === 'LONG' ? <TrendingUp size={14} /> : <TrendingDown size={14} />} {sig.side}
            </span>
          </div>
          <div className="tdp-bigscore" style={{ color: sig.side === 'LONG' ? '#4ade80' : '#f87171' }}>
            {sig.score >= 0 ? '+' : ''}{sig.score.toFixed(2)}
          </div>
          <div className="tdp-card__row">
            <span>Suggested size · <b>${sig.suggested_size?.toLocaleString() || 0}</b></span>
            <span>Est P(win) · <b>{((sig.estimated_prob || 0) * 100).toFixed(0)}%</b></span>
          </div>
        </motion.div>
      )}

      {spark.length > 5 && (
        <motion.div
          className="tdp-card"
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
                <YAxis hide domain={[sparkMin * 0.998, sparkMax * 1.002]} />
                <Tooltip content={({ active, payload }) => active && payload?.length ? (
                  <div className="mc-tt"><b className="mono">${(payload[0].value as number).toFixed(2)}</b></div>
                ) : null} />
                <Line type="monotone" dataKey="v"
                  stroke={sparkChange >= 0 ? '#4ade80' : '#f87171'}
                  strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      )}

      {p && p.s_score !== null && (
        <motion.div
          className="tdp-card"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <div className="tdp-label">PULSE SIGNALS</div>
          <div className="tdp-grid">
            <Stat label="s-score" value={p.s_score >= 0 ? `+${p.s_score.toFixed(2)}` : p.s_score.toFixed(2)}
              color={Math.abs(p.s_score) > 1.25 ? (p.s_score > 0 ? '#f87171' : '#4ade80') : undefined} />
            <Stat label="Half-life" value={p.half_life_bars ? `${p.half_life_bars.toFixed(0)} bars` : '—'} />
            <Stat label="β market" value={p.beta_market !== null ? p.beta_market.toFixed(2) : '—'} />
            <Stat label="β sector" value={p.beta_sector !== null ? p.beta_sector.toFixed(2) : '—'} />
            <Stat label="RSI(2)" value={p.rsi2.toFixed(0)}
              color={p.rsi2 > 90 ? '#f87171' : p.rsi2 < 10 ? '#4ade80' : undefined} />
            <Stat label="ATR(20)" value={`$${p.atr20.toFixed(2)}`} />
            <Stat label="Vol z" value={`${p.vol_z >= 0 ? '+' : ''}${p.vol_z.toFixed(1)}σ`}
              color={Math.abs(p.vol_z) > 2 ? '#fbbf24' : undefined} />
            <Stat label="Regime" value={p.regime_up ? '↑ Above 200' : '↓ Below 200'}
              color={p.regime_up ? '#4ade80' : '#f87171'} />
          </div>
        </motion.div>
      )}

      {sig?.factors?.length > 0 && (
        <motion.div className="tdp-card"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <div className="tdp-label">SIGNAL ATTRIBUTION</div>
          <div className="tdp-factors">
            {sig.factors.map((f: any, i: number) => (
              <div key={i} className="tdp-factor">
                <span>{f.label}</span>
                <b style={{ color: f.value >= 0 ? '#4ade80' : '#f87171', fontFamily: 'var(--font-mono)' }}>
                  {f.value >= 0 ? '+' : ''}{f.value.toFixed(2)}
                </b>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      <motion.div className="tdp-card"
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <div className="tdp-label">EARNINGS HISTORY · LAST 6</div>
        {data.earnings_history.length === 0 ? (
          <div className="tdp-empty">No earnings history in our database for {data.ticker}.</div>
        ) : (
          <div className="tdp-eh">
            {data.earnings_history.map((e: any, i: number) => (
              <div key={i} className="tdp-eh__row">
                <div className="tdp-eh__period mono">{e.period || '—'}</div>
                <div className="tdp-eh__pred">
                  <div className="tdp-eh__plabel">PRED</div>
                  <div className="tdp-eh__pval" style={{
                    color: e.predicted_label === 'UP' ? '#4ade80' :
                           e.predicted_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)'
                  }}>{e.predicted_label || '—'}</div>
                </div>
                <div className="tdp-eh__act">
                  <div className="tdp-eh__plabel">ACTUAL</div>
                  <div className="tdp-eh__pval" style={{
                    color: e.actual_label === 'UP' ? '#4ade80' :
                           e.actual_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)'
                  }}>{!e.is_past ? <span style={{color:'#fbbf24'}}>PENDING</span> : (e.actual_label || '—')}</div>
                </div>
                <div className="tdp-eh__move mono" style={{
                  color: e.actual_move_pct === null ? 'var(--text-tertiary)' :
                         e.actual_move_pct > 0 ? '#4ade80' : '#f87171'
                }}>
                  {e.actual_move_pct !== null
                    ? `${e.actual_move_pct >= 0 ? '+' : ''}${(e.actual_move_pct*100).toFixed(2)}%` : '—'}
                </div>
                <div className="tdp-eh__win">
                  {e.win === null ? <span style={{color:'var(--text-tertiary)'}}>—</span> :
                   e.win ? <Check size={16} color="#4ade80" /> : <AlertTriangle size={16} color="#f87171" />}
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
