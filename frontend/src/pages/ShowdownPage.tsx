import { useState, useEffect, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Trophy, BookOpen, TrendingUp, TrendingDown, Activity, Eye, Zap, Radio } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts'

type OpenPos = {
  entry_date: string; exit_date: string; ticker: string; sector: string;
  side: string; confidence: number; expected_move: number | null;
  notional: number; days_held: number;
}
type ClosedTrade = {
  date: string; exit_date: string; ticker: string; sector: string; side: string;
  return_pct: number; pnl: number; win: boolean;
}
type PendingSignal = {
  ticker: string; earnings_date: string; side: string; confidence: number;
  expected_move: number | null; sector: string; days_until: number;
}
type Strategy = {
  code: string; name: string; emoji: string; tagline: string;
  citation: string; color: string; description: string;
  final_equity: number; total_return: number; trades: number; wins: number;
  win_rate: number; sharpe: number; max_drawdown: number;
  equity_curve: { date: string; equity: number }[];
  recent_closes: ClosedTrade[];
  currently_open: OpenPos[];
  pending_signals: PendingSignal[];
}
type FeedEvent = {
  type: string; timestamp: string; strategy: string;
  ticker: string; side: string; return_pct?: number; win?: boolean;
}
type Showdown = {
  strategies: Strategy[]; events: number; initial_capital: number;
  launch_date: string; end_date: string; as_of: string;
  live_feed: FeedEvent[]; days_since_launch: number;
}

const RANK_EMOJI = ['🥇', '🥈', '🥉', '4.', '5.']
const fmtPct = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const fmt$ = (v: number) => `$${(v / 1000).toFixed(1)}k`
const sparkPath = (vals: number[], w: number, h: number) => {
  if (vals.length < 2) return ''
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const range = mx - mn || 1
  return vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w
    const y = h - ((v - mn) / range) * h
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
}

export function ShowdownPage() {
  const [data, setData] = useState<Showdown | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedStrat, setSelectedStrat] = useState<string | null>(null)
  const [now, setNow] = useState(new Date())

  const launchDate = useMemo(() => {
    const d = new Date()
    d.setDate(d.getDate() - 90)
    return d.toISOString().slice(0, 10)
  }, [])
  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/v1/showdown?start_date=${launchDate}&end_date=${today}`)
      const d = await r.json()
      setData(d)
    } finally {
      setLoading(false)
    }
  }, [launchDate, today])

  useEffect(() => { load() }, [load])
  // Tick every second for "as of" display
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  // Auto-refresh data every 60s
  useEffect(() => {
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [load])

  const mergedCurve = useMemo(() => {
    if (!data?.strategies.length) return []
    const byDate = new Map<string, any>()
    data.strategies.forEach(s => {
      s.equity_curve.forEach(p => {
        const r = byDate.get(p.date) || { date: p.date }
        r[s.code] = (p.equity / data.initial_capital - 1) * 100
        byDate.set(p.date, r)
      })
    })
    return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date))
  }, [data])

  const allOpenPositions = useMemo(() => {
    if (!data) return []
    const items: (OpenPos & { stratCode: string; stratEmoji: string; stratColor: string; stratName: string })[] = []
    data.strategies.forEach(s => {
      s.currently_open.forEach(p => items.push({
        ...p, stratCode: s.code, stratEmoji: s.emoji, stratColor: s.color, stratName: s.name,
      }))
    })
    return items
      .filter(p => !selectedStrat || p.stratCode === selectedStrat)
      .sort((a, b) => b.entry_date.localeCompare(a.entry_date))
  }, [data, selectedStrat])

  const allPending = useMemo(() => {
    if (!data) return []
    const items: (PendingSignal & { stratCode: string; stratEmoji: string; stratColor: string; stratName: string })[] = []
    data.strategies.forEach(s => {
      s.pending_signals.forEach(p => items.push({
        ...p, stratCode: s.code, stratEmoji: s.emoji, stratColor: s.color, stratName: s.name,
      }))
    })
    return items
      .filter(p => !selectedStrat || p.stratCode === selectedStrat)
      .sort((a, b) => a.earnings_date.localeCompare(b.earnings_date))
      .slice(0, 20)
  }, [data, selectedStrat])

  if (loading || !data) return (
    <div className="sw-loading">
      <div className="sw-loading__spinner" />
      <div>Loading live showdown…</div>
    </div>
  )

  return (
    <div className="sw-page">
      {/* Hero */}
      <motion.div className="sw-hero-live" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <div className="sw-hero-live__top">
          <div className="sw-live-badge">
            <span className="sw-live-dot" />LIVE
          </div>
          <div className="sw-hero-live__meta">
            Day <b>{data.days_since_launch}</b> since launch ({data.launch_date}) ·
            Updated <b className="mono">{now.toLocaleTimeString('en-US', { hour12: false })}</b> ·
            Auto-refresh 60s
          </div>
        </div>
        <h1 className="sw-hero-live__title">Strategy Showdown · Live Trading Floor</h1>
        <p className="sw-hero-live__sub">
          5 trading bots running on the same earnings event stream. Each launched with $1M.
          Watch open positions update, pending signals fire, and the leaderboard reshuffle as new earnings drop.
        </p>
      </motion.div>

      {/* Leaderboard with sparklines */}
      <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="sw-card__title">
          <Trophy size={14} />Leaderboard
          <span className="sw-card__sub">{data.events.toLocaleString()} events processed · click any row to filter all panels</span>
        </div>
        <div className="sw-board">
          {data.strategies.map((s, i) => {
            const equity = s.equity_curve.map(p => p.equity)
            return (
              <motion.button key={s.code}
                className={`sw-row ${selectedStrat === s.code ? 'sw-row--active' : ''}`}
                onClick={() => setSelectedStrat(selectedStrat === s.code ? null : s.code)}
                layout
                initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06 }}
                style={{ borderLeft: `3px solid ${s.color}` }}>
                <div className="sw-row__rank">{RANK_EMOJI[i]}</div>
                <div className="sw-row__emoji">{s.emoji}</div>
                <div className="sw-row__name">
                  <div className="sw-row__nameMain">{s.name}</div>
                  <div className="sw-row__tagline">{s.tagline}</div>
                </div>
                <svg className="sw-row__spark" viewBox="0 0 100 24" preserveAspectRatio="none">
                  <path d={sparkPath(equity, 100, 24)} fill="none" stroke={s.color} strokeWidth="1.4" />
                </svg>
                <div className="sw-row__stat">
                  <div className="sw-row__label">Return</div>
                  <div className="sw-row__val" style={{ color: s.total_return >= 0 ? s.color : '#f87171' }}>
                    {fmtPct(s.total_return)}
                  </div>
                </div>
                <div className="sw-row__stat">
                  <div className="sw-row__label">Sharpe</div>
                  <div className="sw-row__val mono">{s.sharpe.toFixed(2)}</div>
                </div>
                <div className="sw-row__stat">
                  <div className="sw-row__label">Open</div>
                  <div className="sw-row__val mono">{s.currently_open.length}</div>
                </div>
                <div className="sw-row__stat">
                  <div className="sw-row__label">Trades</div>
                  <div className="sw-row__val mono">{s.trades}</div>
                </div>
                <div className="sw-row__stat">
                  <div className="sw-row__label">Win %</div>
                  <div className="sw-row__val mono">{(s.win_rate * 100).toFixed(0)}%</div>
                </div>
              </motion.button>
            )
          })}
        </div>
      </motion.div>

      {/* Live feed */}
      {data.live_feed.length > 0 && (
        <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <div className="sw-card__title">
            <Radio size={14} />Live Feed
            <span className="sw-card__sub">recent trade events across all strategies · last 14 days</span>
          </div>
          <div className="sw-feed">
            {data.live_feed.map((e, i) => {
              const strat = data.strategies.find(s => s.code === e.strategy)
              if (!strat) return null
              return (
                <motion.div key={i} className="sw-feed__row"
                  initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.02 }}>
                  <span className="sw-feed__time mono">{e.timestamp.slice(5, 10)}</span>
                  <span className="sw-feed__strat" style={{ color: strat.color }}>
                    {strat.emoji} {strat.name}
                  </span>
                  <span className="sw-feed__action">
                    {e.type === 'open' ? '→ opened' : '✓ closed'}
                  </span>
                  <span className="sw-feed__side" style={{ color: e.side === 'LONG' ? '#4ade80' : '#f87171' }}>
                    {e.side === 'LONG' ? '↑' : '↓'} {e.side}
                  </span>
                  <span className="sw-feed__ticker mono">{e.ticker}</span>
                  {e.return_pct !== undefined && (
                    <span className="sw-feed__return mono" style={{ color: (e.return_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                      {(e.return_pct ?? 0) >= 0 ? '+' : ''}{e.return_pct?.toFixed(2)}%
                    </span>
                  )}
                </motion.div>
              )
            })}
          </div>
        </motion.div>
      )}

      {/* Race chart */}
      <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <div className="sw-card__title">
          <Activity size={14} />Race Chart
          <span className="sw-card__sub">cumulative return since launch · {selectedStrat ? 'filtered' : 'all 5'}</span>
        </div>
        <div style={{ height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={mergedCurve} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false}
                tickFormatter={v => v.slice(5)} minTickGap={50} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false}
                tickFormatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`} />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 3" />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const sorted = [...payload].sort((a: any, b: any) => (b.value ?? 0) - (a.value ?? 0))
                  return (
                    <div className="sw-tt">
                      <div className="sw-tt__date">{label}</div>
                      {sorted.map((p: any) => {
                        const s = data.strategies.find(x => x.code === p.dataKey)
                        if (!s) return null
                        return (
                          <div key={p.dataKey} className="sw-tt__row">
                            <span>{s.emoji} {s.name}</span>
                            <b style={{ color: p.value >= 0 ? s.color : '#f87171' }}>
                              {p.value >= 0 ? '+' : ''}{p.value.toFixed(2)}%
                            </b>
                          </div>
                        )
                      })}
                    </div>
                  )
                }}
              />
              {data.strategies.map(s => (
                <Line key={s.code} type="monotone" dataKey={s.code}
                  stroke={s.color}
                  strokeWidth={selectedStrat === null || selectedStrat === s.code ? 2.2 : 0.5}
                  strokeOpacity={selectedStrat === null || selectedStrat === s.code ? 1 : 0.2}
                  dot={false} animationDuration={1200} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </motion.div>

      {/* Two columns: Open positions | Pending signals */}
      <div className="sw-grid-2">
        <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <div className="sw-card__title">
            <Eye size={14} />Currently Open Positions
            <span className="sw-card__sub">{allOpenPositions.length} live across {selectedStrat ? '1' : '5'} strategies</span>
          </div>
          {allOpenPositions.length === 0 ? (
            <div className="sw-empty">No open positions right now. Waiting for next earnings event.</div>
          ) : (
            <div className="sw-list">
              {allOpenPositions.map((p, i) => (
                <div key={i} className="sw-pos">
                  <span className="sw-pos__strat" style={{ borderColor: p.stratColor, color: p.stratColor }}>
                    {p.stratEmoji} {p.stratName}
                  </span>
                  <span className="sw-pos__ticker mono">{p.ticker}</span>
                  <span className="sw-pos__side" style={{ color: p.side === 'LONG' ? '#4ade80' : '#f87171' }}>
                    {p.side === 'LONG' ? <TrendingUp size={11} /> : <TrendingDown size={11} />} {p.side}
                  </span>
                  <span className="sw-pos__notional mono">{fmt$(p.notional)}</span>
                  <span className="sw-pos__conf">
                    {p.confidence ? `${p.confidence.toFixed(0)}% conf` : '—'}
                  </span>
                  <span className="sw-pos__days mono">d+{p.days_held}</span>
                  <span className="sw-pos__exit">exits {p.exit_date.slice(5)}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>

        <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <div className="sw-card__title">
            <Zap size={14} />Watchlist · Pending Signals
            <span className="sw-card__sub">upcoming earnings each strategy is targeting · next 14 days</span>
          </div>
          {allPending.length === 0 ? (
            <div className="sw-empty">No pending signals. Strategies are sitting in cash.</div>
          ) : (
            <div className="sw-list">
              {allPending.map((p, i) => (
                <div key={i} className="sw-pending">
                  <span className="sw-pending__strat" style={{ borderColor: p.stratColor, color: p.stratColor }}>
                    {p.stratEmoji} {p.stratName}
                  </span>
                  <span className="sw-pending__ticker mono">{p.ticker}</span>
                  <span className="sw-pending__side" style={{ color: p.side === 'LONG' ? '#4ade80' : '#f87171' }}>
                    {p.side === 'LONG' ? '↑' : '↓'} {p.side}
                  </span>
                  <span className="sw-pending__conf">{p.confidence.toFixed(0)}%</span>
                  {p.expected_move !== null && (
                    <span className="sw-pending__em mono">±{p.expected_move.toFixed(1)}%</span>
                  )}
                  <span className="sw-pending__when">
                    {p.days_until === 0 ? 'TODAY' : `in ${p.days_until}d`}
                    <span className="sw-pending__date"> · {p.earnings_date.slice(5)}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </div>

      {/* Strategy cards */}
      <div className="sw-cards">
        {data.strategies.map((s, i) => (
          <motion.div key={s.code} className="sw-cardlet"
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35 + i * 0.05 }}
            style={{ borderTop: `3px solid ${s.color}` }}>
            <div className="sw-cardlet__head">
              <span className="sw-cardlet__emoji">{s.emoji}</span>
              <div>
                <div className="sw-cardlet__name">{s.name}</div>
                <div className="sw-cardlet__tag">{s.tagline}</div>
              </div>
            </div>
            <p className="sw-cardlet__desc">{s.description}</p>
            <div className="sw-cardlet__stats">
              <div><span>Return</span><b style={{ color: s.total_return >= 0 ? s.color : '#f87171' }}>{fmtPct(s.total_return)}</b></div>
              <div><span>Sharpe</span><b>{s.sharpe.toFixed(2)}</b></div>
              <div><span>Trades</span><b>{s.trades}</b></div>
              <div><span>Win</span><b>{(s.win_rate * 100).toFixed(0)}%</b></div>
            </div>
            <div className="sw-cardlet__cite"><BookOpen size={11} /> {s.citation}</div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
