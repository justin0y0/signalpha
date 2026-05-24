import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, TrendingUp, TrendingDown, Check, AlertTriangle } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip } from 'recharts'
import { StockLogo } from './StockLogo'

interface Props {
  ticker: string | null
  onClose: () => void
}

interface Detail {
  ticker: string
  in_universe: boolean
  pulse: any
  active_signal: any
  earnings_history: Array<{
    scheduled_time: string | null
    period: string | null
    eps_estimate: number | null
    eps_actual: number | null
    predicted_label: string | null
    predicted_prob: number | null
    actual_move_pct: number | null
    actual_label?: string
    win: boolean | null
    is_past: boolean
  }>
  price_series: number[]
}

export function TickerDetailModal({ ticker, onClose }: Props) {
  const [data, setData] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!ticker) { setData(null); return }
    setLoading(true)
    fetch(`/api/v1/pulse/ticker/${ticker}`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [ticker])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <AnimatePresence>
      {ticker && (
        <motion.div
          className="tdm-overlay"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}>
          <motion.div
            className="tdm-modal"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 320 }}
            onClick={e => e.stopPropagation()}>
            <button className="tdm-close" onClick={onClose}><X size={18} /></button>
            {loading && <div className="tdm-loading">Loading {ticker}…</div>}
            {data && <TickerDetailContent data={data} />}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function TickerDetailContent({ data }: { data: Detail }) {
  const p = data.pulse
  const sig = data.active_signal
  const sparkData = (data.price_series || []).map((v, i) => ({ i, v }))

  return (
    <div className="tdm-body">
      <div className="tdm-header">
        <StockLogo ticker={data.ticker} size={56} />
        <div className="tdm-header__text">
          <h2 className="tdm-ticker">{data.ticker}</h2>
          <div className="tdm-meta">
            {p && <>
              <span className="tdm-price mono">${p.price.toFixed(2)}</span>
              <span className="tdm-sep">·</span>
              <span>{p.sector}</span>
              {p.session && p.session !== 'market' && (
                <>
                  <span className="tdm-sep">·</span>
                  <span style={{ color: '#fbbf24' }}>{p.session.replace('_', '-').toUpperCase()}</span>
                </>
              )}
            </>}
            {!data.in_universe && <span>Not in active scan universe</span>}
          </div>
        </div>
        {sig && (
          <div className="tdm-conviction" style={{
            borderColor: sig.side === 'LONG' ? '#4ade80' : '#f87171',
            color: sig.side === 'LONG' ? '#4ade80' : '#f87171',
          }}>
            <div className="tdm-conv__label">CONVICTION</div>
            <div className="tdm-conv__val mono">{sig.score >= 0 ? '+' : ''}{sig.score.toFixed(2)}</div>
            <div className="tdm-conv__side">
              {sig.side === 'LONG' ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {sig.side}
            </div>
          </div>
        )}
      </div>

      {sparkData.length > 5 && (
        <div className="tdm-section">
          <div className="tdm-section__title">PRICE · LAST 5 DAYS</div>
          <div style={{ height: 100 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparkData}>
                <YAxis hide domain={['dataMin', 'dataMax']} />
                <Tooltip
                  content={({ active, payload }) => active && payload?.length ? (
                    <div className="mc-tt"><b className="mono">${(payload[0].value as number).toFixed(2)}</b></div>
                  ) : null} />
                <Line type="monotone" dataKey="v" stroke="#38bdf8" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {p && p.s_score !== null && (
        <div className="tdm-section">
          <div className="tdm-section__title">PULSE SIGNALS</div>
          <div className="tdm-stats-grid">
            <Stat label="s-score" value={p.s_score >= 0 ? `+${p.s_score.toFixed(2)}` : p.s_score.toFixed(2)}
              color={Math.abs(p.s_score) > 1.25 ? (p.s_score > 0 ? '#f87171' : '#4ade80') : 'var(--text-secondary)'} />
            <Stat label="Half-life" value={p.half_life_bars ? `${p.half_life_bars.toFixed(0)} bars` : '—'} />
            <Stat label="β market" value={p.beta_market !== null ? p.beta_market.toFixed(2) : '—'} />
            <Stat label="β sector" value={p.beta_sector !== null ? p.beta_sector.toFixed(2) : '—'} />
            <Stat label="RSI(2)" value={p.rsi2.toFixed(0)}
              color={p.rsi2 > 90 ? '#f87171' : p.rsi2 < 10 ? '#4ade80' : 'var(--text-secondary)'} />
            <Stat label="ATR(20)" value={`$${p.atr20.toFixed(2)}`} />
            <Stat label="Vol z" value={`${p.vol_z >= 0 ? '+' : ''}${p.vol_z.toFixed(1)}σ`}
              color={Math.abs(p.vol_z) > 2 ? '#fbbf24' : 'var(--text-secondary)'} />
            <Stat label="Regime" value={p.regime_up ? '↑ Above 200-SMA' : '↓ Below 200-SMA'}
              color={p.regime_up ? '#4ade80' : '#f87171'} />
          </div>
        </div>
      )}

      {sig && sig.factors && sig.factors.length > 0 && (
        <div className="tdm-section">
          <div className="tdm-section__title">SIGNAL ATTRIBUTION</div>
          <div className="tdm-factors">
            {sig.factors.map((f: any, i: number) => (
              <div key={i} className="tdm-factor">
                <span>{f.label}</span>
                <b className="mono" style={{ color: f.value >= 0 ? '#4ade80' : '#f87171' }}>
                  {f.value >= 0 ? '+' : ''}{f.value.toFixed(2)}
                </b>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="tdm-section">
        <div className="tdm-section__title">EARNINGS HISTORY · LAST 6</div>
        {data.earnings_history.length === 0 ? (
          <div className="tdm-empty">No earnings history available for {data.ticker} in our database.</div>
        ) : (
          <div className="tdm-earnings-table">
            <div className="tdm-eh-head">
              <span>Period</span>
              <span>Date</span>
              <span>EPS Est</span>
              <span>EPS Act</span>
              <span>Predicted</span>
              <span>Actual</span>
              <span style={{ textAlign: 'right' }}>Move</span>
              <span style={{ textAlign: 'center' }}>Win</span>
            </div>
            {data.earnings_history.map((e, i) => (
              <div key={i} className="tdm-eh-row">
                <span className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>{e.period || '—'}</span>
                <span className="mono" style={{ fontSize: '0.7rem' }}>
                  {e.scheduled_time ? e.scheduled_time.slice(0, 10) : '—'}
                </span>
                <span className="mono">{e.eps_estimate !== null ? `$${e.eps_estimate.toFixed(2)}` : '—'}</span>
                <span className="mono">{e.eps_actual !== null ? `$${e.eps_actual.toFixed(2)}` : '—'}</span>
                <span style={{ color: e.predicted_label === 'UP' ? '#4ade80' : e.predicted_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)' }}>
                  {e.predicted_label || '—'}
                  {e.predicted_prob !== null && <span style={{ fontSize: '0.62rem', marginLeft: '0.2rem', color: 'var(--text-tertiary)' }}>
                    {(e.predicted_prob * 100).toFixed(0)}%
                  </span>}
                </span>
                <span style={{
                  color: e.actual_label === 'UP' ? '#4ade80' :
                         e.actual_label === 'DOWN' ? '#f87171' : 'var(--text-tertiary)'
                }}>
                  {!e.is_past ? <span style={{ color: '#fbbf24' }}>UPCOMING</span> : (e.actual_label || '—')}
                </span>
                <span className="mono" style={{
                  textAlign: 'right',
                  color: e.actual_move_pct === null ? 'var(--text-tertiary)' :
                         e.actual_move_pct > 0 ? '#4ade80' : '#f87171'
                }}>
                  {e.actual_move_pct !== null ?
                    `${e.actual_move_pct >= 0 ? '+' : ''}${(e.actual_move_pct * 100).toFixed(2)}%` : '—'}
                </span>
                <span style={{ textAlign: 'center' }}>
                  {e.win === null ? '—' : e.win
                    ? <Check size={14} color="#4ade80" />
                    : <AlertTriangle size={14} color="#f87171" />}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="tdm-stat">
      <div className="tdm-stat__l">{label}</div>
      <div className="tdm-stat__v mono" style={{ color }}>{value}</div>
    </div>
  )
}
