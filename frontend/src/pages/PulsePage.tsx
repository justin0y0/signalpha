import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { motion } from 'framer-motion'
import { Activity, Flame, Zap, TrendingUp, TrendingDown, Radio, Gauge } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

type Ticker = {
  ticker: string; sector: string; price: number; rsi: number; vol_z: number;
  dist_ma: number; intraday_ret: number; ret_5m: number; gap_pct: number;
  spark: number[]; last_ts: string;
}
type Signal = {
  ticker: string; sector: string; type: string; type_label: string;
  emoji: string; side: string; color: string; price: number; rsi: number;
  vol_z: number; intraday_ret: number; timestamp: string;
}
type Sector = { sector: string; avg_ret: number; count: number }
type Trade = {
  ticker: string; side: string; type: string;
  entry_time: string; exit_time: string;
  entry_price: number; exit_price: number;
  pnl: number; return_pct: number; win: boolean;
}
type Portfolio = {
  final_equity: number; total_return: number; trades: number; wins: number;
  win_rate: number; sharpe: number;
  equity_curve: { ts: string; equity: number }[];
  trade_log: Trade[];
}
type PulseData = {
  tickers: Ticker[]; signals: Signal[]; sectors: Sector[];
  market: { avg_return: number; breadth: number; avg_vol_z: number; avg_rsi: number; n_tickers: number };
  portfolio: Portfolio; as_of: string;
}

function useCountUp(target: number, duration = 700): number {
  const [v, setV] = useState(target)
  const prev = useRef(target)
  useEffect(() => {
    const t0 = performance.now(), start = prev.current, delta = target - start
    if (Math.abs(delta) < 0.001) { setV(target); return }
    let raf = 0
    const step = (n: number) => {
      const p = Math.min(1, (n - t0) / duration)
      setV(start + delta * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(step)
      else prev.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return v
}

function spark(vals: number[], w: number, h: number): string {
  if (vals.length < 2) return ''
  const mn = Math.min(...vals), mx = Math.max(...vals), r = mx - mn || 1
  return vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${((i / (vals.length - 1)) * w).toFixed(1)} ${(h - ((v - mn) / r) * h).toFixed(1)}`).join(' ')
}

export function PulsePage() {
  const [data, setData] = useState<PulseData | null>(null)
  const [loading, setLoading] = useState(true)
  const [now, setNow] = useState(new Date())

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/pulse')
      setData(await r.json())
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [load])

  if (loading || !data) return (
    <div className="mc-loading">
      <div className="mc-loading__scan" />
      <div className="mc-loading__text">SCANNING MARKET</div>
      <div className="mc-loading__sub">Fetching 5-min bars for {30} tickers…</div>
    </div>
  )

  return (
    <div className="mc-page">
      <PulseHero data={data} now={now} />
      <MarketGauges data={data} />
      <SignalFeed signals={data.signals} />
      <HeatMap tickers={data.tickers} />
      <PortfolioPanel portfolio={data.portfolio} />
      <SectorBars sectors={data.sectors} />
    </div>
  )
}


function PulseHero({ data, now }: { data: PulseData; now: Date }) {
  const sigCount = data.signals.length
  return (
    <div className="mc-hero">
      <div className="mc-hero__scanlines" />
      <div className="mc-hero__grid" />
      <div className="mc-hero__content">
        <div className="mc-hero__top">
          <div className="mc-status"><span className="mc-status__dot" /><span className="mc-status__txt">SCANNING</span></div>
          <div className="mc-clock"><span className="mc-clock__time">{now.toLocaleTimeString('en-US', { hour12: false })}</span><span className="mc-clock__tz">ET</span></div>
          <div className="mc-system">PULSE · {data.market.n_tickers} TICKERS · 5-MIN BARS · {sigCount} ACTIVE SIGNALS</div>
        </div>
        <div className="mc-hero__main">
          <div>
            <div className="mc-hero__eyebrow">REAL-TIME MARKET PULSE</div>
            <h1 className="mc-hero__title">Continuous Anomaly Scanner</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', margin: '0.4rem 0 0', maxWidth: 700 }}>
              5 technical signal types running on top-30 S&P 500 names. Refreshes every minute. Trades simulated on $1M book with 1-hour holding periods.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}


function MarketGauges({ data }: { data: PulseData }) {
  const m = data.market
  const breadthPct = m.breadth * 100
  return (
    <div className="pulse-gauges">
      <Gauge1 label="MARKET" value={`${m.avg_return >= 0 ? '+' : ''}${(m.avg_return * 100).toFixed(2)}%`}
        accent={m.avg_return >= 0 ? '#4ade80' : '#f87171'} sub="avg intraday return" />
      <Gauge1 label="BREADTH" value={`${breadthPct.toFixed(0)}%`}
        accent={breadthPct >= 50 ? '#4ade80' : '#f87171'} sub={`${Math.round(breadthPct / 100 * m.n_tickers)}/${m.n_tickers} advancing`} />
      <Gauge1 label="VOLUME" value={`${m.avg_vol_z >= 0 ? '+' : ''}${m.avg_vol_z.toFixed(1)}σ`}
        accent={m.avg_vol_z > 1 ? '#fbbf24' : '#38bdf8'} sub="z-score vs 60-bar avg" />
      <Gauge1 label="AVG RSI" value={m.avg_rsi.toFixed(1)}
        accent={m.avg_rsi > 70 ? '#f87171' : m.avg_rsi < 30 ? '#4ade80' : '#38bdf8'} sub="market-wide 14-period" />
      <Gauge1 label="SIGNALS" value={data.signals.length.toString()}
        accent="#a78bfa" sub="firing right now" />
    </div>
  )
}

function Gauge1({ label, value, accent, sub }: { label: string; value: string; accent: string; sub: string }) {
  return (
    <div className="pulse-gauge" style={{ '--accent': accent } as React.CSSProperties}>
      <div className="pulse-gauge__label">{label}</div>
      <div className="pulse-gauge__value mono" style={{ color: accent }}>{value}</div>
      <div className="pulse-gauge__sub">{sub}</div>
      <div className="pulse-gauge__bar" />
    </div>
  )
}


function SignalFeed({ signals }: { signals: Signal[] }) {
  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="mc-panel__title">
        <Zap size={14} /> ACTIVE SIGNALS
        <span className="mc-panel__sub">live anomalies firing on current bar · {signals.length} total</span>
      </div>
      {signals.length === 0 ? (
        <div className="mc-empty">Market is quiet. No signals firing right now.</div>
      ) : (
        <div className="pulse-signals">
          {signals.slice(0, 24).map((s, i) => (
            <motion.div key={i} className="pulse-signal"
              initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.03 }}
              style={{ borderColor: s.color, boxShadow: `0 0 20px -8px ${s.color}` }}>
              <div className="pulse-signal__top">
                <span className="pulse-signal__emoji">{s.emoji}</span>
                <span className="pulse-signal__type" style={{ color: s.color }}>{s.type_label}</span>
              </div>
              <div className="pulse-signal__ticker mono">{s.ticker}</div>
              <div className="pulse-signal__price mono">${s.price.toFixed(2)}</div>
              <div className="pulse-signal__action">
                <span style={{ color: s.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 800 }}>
                  {s.side === 'LONG' ? <TrendingUp size={11} /> : <TrendingDown size={11} />} {s.side}
                </span>
                <span className="pulse-signal__ret mono" style={{ color: s.intraday_ret >= 0 ? '#4ade80' : '#f87171' }}>
                  {s.intraday_ret >= 0 ? '+' : ''}{(s.intraday_ret * 100).toFixed(2)}%
                </span>
              </div>
              <div className="pulse-signal__meta mono">
                RSI {s.rsi.toFixed(0)} · VOL {s.vol_z.toFixed(1)}σ
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  )
}


function HeatMap({ tickers }: { tickers: Ticker[] }) {
  const cellColor = (ret: number) => {
    const intensity = Math.min(1, Math.abs(ret) / 0.04)
    if (ret > 0) return `rgba(74, 222, 128, ${0.1 + intensity * 0.55})`
    return `rgba(248, 113, 113, ${0.1 + intensity * 0.55})`
  }
  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
      <div className="mc-panel__title">
        <Flame size={14} /> HEAT MAP
        <span className="mc-panel__sub">intraday performance · cell brightness = magnitude · click for details</span>
      </div>
      <div className="pulse-heat">
        {tickers.map((t, i) => (
          <motion.div key={t.ticker} className="pulse-heat__cell"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.015 }}
            style={{ background: cellColor(t.intraday_ret) }}>
            <div className="pulse-heat__ticker mono">{t.ticker}</div>
            <div className="pulse-heat__pct mono" style={{ color: t.intraday_ret >= 0 ? '#4ade80' : '#f87171' }}>
              {t.intraday_ret >= 0 ? '+' : ''}{(t.intraday_ret * 100).toFixed(2)}%
            </div>
            <svg className="pulse-heat__spark" viewBox="0 0 60 16" preserveAspectRatio="none">
              <path d={spark(t.spark, 60, 16)} fill="none"
                stroke={t.intraday_ret >= 0 ? '#4ade80' : '#f87171'} strokeWidth="1" />
            </svg>
            <div className="pulse-heat__meta mono">
              <span>${t.price.toFixed(2)}</span>
              <span style={{ color: t.rsi > 70 ? '#f87171' : t.rsi < 30 ? '#4ade80' : 'var(--text-tertiary)' }}>
                RSI {t.rsi.toFixed(0)}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}


function PortfolioPanel({ portfolio: p }: { portfolio: Portfolio }) {
  const eq = useCountUp(p.final_equity, 900)
  const ret = useCountUp(p.total_return * 100, 900)
  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
      <div className="mc-panel__title">
        <Activity size={14} /> SCANNER PORTFOLIO
        <span className="mc-panel__sub">$1M virtual book trading every signal · 1-hour hold · last 5 days</span>
      </div>
      <div className="pulse-port">
        <div className="pulse-port__lcd">
          <div className="pulse-port__lcd-label">EQUITY</div>
          <div className="pulse-port__lcd-val mono" style={{ color: p.total_return >= 0 ? '#4ade80' : '#f87171' }}>
            ${Math.round(eq).toLocaleString()}
          </div>
          <div className={`pulse-port__ret mono ${p.total_return >= 0 ? 'up' : 'down'}`}>
            {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
          </div>
        </div>
        <div className="pulse-port__stats">
          <div><span>TRADES</span><b className="mono">{p.trades}</b></div>
          <div><span>WIN RATE</span><b className="mono">{(p.win_rate * 100).toFixed(0)}%</b></div>
          <div><span>SHARPE</span><b className="mono">{p.sharpe.toFixed(2)}</b></div>
          <div><span>WINS</span><b className="mono">{p.wins}</b></div>
        </div>
        <div className="pulse-port__curve">
          {p.equity_curve.length > 1 && (
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={p.equity_curve} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <XAxis dataKey="ts" hide />
                <YAxis hide domain={['dataMin', 'dataMax']} />
                <ReferenceLine y={1_000_000} stroke="rgba(255,255,255,0.15)" strokeDasharray="3 3" />
                <Tooltip
                  content={({ active, payload }) => active && payload?.length ? (
                    <div className="mc-tt"><b className="mono">${Math.round(payload[0].value as number).toLocaleString()}</b></div>
                  ) : null}
                />
                <Line type="monotone" dataKey="equity" stroke={p.total_return >= 0 ? '#4ade80' : '#f87171'}
                  strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {p.trade_log.length > 0 && (
        <div className="pulse-trades">
          <div style={{ fontSize: '0.65rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', color: 'var(--text-tertiary)', margin: '0.5rem 0' }}>RECENT TRADES</div>
          <div className="mc-log">
            {p.trade_log.map((t, i) => (
              <div key={i} className="mc-log__row">
                <span className="mc-log__time mono">{t.exit_time.slice(5, 16).replace('T', ' ')}</span>
                <span className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>{t.ticker}</span>
                <span style={{ color: t.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700, fontSize: '0.7rem' }}>{t.side}</span>
                <span className="mono" style={{ fontSize: '0.66rem', color: 'var(--text-tertiary)' }}>{t.type.replace('_', ' ')}</span>
                <span className="mono" style={{ color: t.win ? '#4ade80' : '#f87171', fontWeight: 700, textAlign: 'right' }}>
                  {t.pnl >= 0 ? '+' : ''}${Math.round(t.pnl).toLocaleString()}
                </span>
                <span className="mono" style={{ color: t.win ? '#4ade80' : '#f87171', textAlign: 'right' }}>
                  {(t.return_pct * 100).toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}


function SectorBars({ sectors }: { sectors: Sector[] }) {
  const maxAbs = Math.max(...sectors.map(s => Math.abs(s.avg_ret)), 0.005)
  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
      <div className="mc-panel__title">
        <Gauge size={14} /> SECTOR ROTATION
        <span className="mc-panel__sub">average intraday return by sector</span>
      </div>
      <div className="pulse-sectors">
        {sectors.map((s, i) => {
          const isUp = s.avg_ret >= 0
          const w = (Math.abs(s.avg_ret) / maxAbs) * 50
          return (
            <motion.div key={s.sector} className="pulse-sector"
              initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}>
              <div className="pulse-sector__name">{s.sector}</div>
              <div className="pulse-sector__bar-wrap">
                <div className="pulse-sector__center" />
                <div className="pulse-sector__bar"
                  style={{
                    background: isUp ? '#4ade80' : '#f87171',
                    width: `${w}%`,
                    [isUp ? 'left' : 'right']: '50%',
                  }}/>
              </div>
              <div className="pulse-sector__val mono" style={{ color: isUp ? '#4ade80' : '#f87171' }}>
                {isUp ? '+' : ''}{(s.avg_ret * 100).toFixed(2)}%
              </div>
              <div className="pulse-sector__count mono">{s.count}</div>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
