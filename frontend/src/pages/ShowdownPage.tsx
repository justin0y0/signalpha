import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Trophy, BookOpen, TrendingUp, TrendingDown, Activity, Eye, Zap, Radio,
  Cpu, Target, Clock, AlertCircle,
} from 'lucide-react'
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
  report_time: string; fires_at: string; fires_at_clock: string;
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
type NextSig = (PendingSignal & {
  strategy: string; strategy_emoji: string; strategy_name: string; strategy_color: string;
}) | null
type Showdown = {
  strategies: Strategy[]; events: number; initial_capital: number;
  launch_date: string; end_date: string; as_of: string;
  live_feed: FeedEvent[]; days_since_launch: number; next_signal: NextSig;
}

const fmtPct = (v: number, d = 2) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const fmtDollar = (v: number) => `$${Math.round(v).toLocaleString()}`

// Smoothly counts up to target number (for LCD-style displays)
function useCountUp(target: number, duration = 800): number {
  const [value, setValue] = useState(target)
  const prevRef = useRef(target)
  useEffect(() => {
    const start = prevRef.current
    const delta = target - start
    if (Math.abs(delta) < 0.001) { setValue(target); return }
    const t0 = performance.now()
    let raf = 0
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      setValue(start + delta * eased)
      if (p < 1) raf = requestAnimationFrame(step)
      else prevRef.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return value
}

function sparkPath(vals: number[], w: number, h: number): string {
  if (vals.length < 2) return ''
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const range = mx - mn || 1
  return vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w
    const y = h - ((v - mn) / range) * h
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
}

function fmtCountdown(ms: number): string {
  if (ms <= 0) return 'FIRING NOW'
  const s = Math.floor(ms / 1000)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (d > 0) return `${d}d ${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m`
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
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
      setData(await r.json())
    } finally { setLoading(false) }
  }, [launchDate, today])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
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

  const countdownMs = useMemo(() => {
    if (!data?.next_signal) return null
    return new Date(data.next_signal.fires_at).getTime() - now.getTime()
  }, [data, now])

  if (loading || !data) return (
    <div className="mc-loading">
      <div className="mc-loading__scan" />
      <div className="mc-loading__text">INITIALIZING MISSION CONTROL</div>
      <div className="mc-loading__sub">Loading 5 trading agents…</div>
    </div>
  )

  return (
    <div className="mc-page">
      {/* ═══ MISSION CONTROL HERO ═══ */}
      <div className="mc-hero">
        <div className="mc-hero__scanlines" />
        <div className="mc-hero__grid" />
        <div className="mc-hero__content">
          <div className="mc-hero__top">
            <div className="mc-status">
              <span className="mc-status__dot" />
              <span className="mc-status__txt">LIVE</span>
            </div>
            <div className="mc-clock">
              <Clock size={14} />
              <span className="mc-clock__time">{now.toLocaleTimeString('en-US', { hour12: false })}</span>
              <span className="mc-clock__tz">ET</span>
            </div>
            <div className="mc-system">
              SYSTEM · DAY {data.days_since_launch} · {data.events} EVENTS PROCESSED
            </div>
          </div>
          <div className="mc-hero__main">
            <div>
              <div className="mc-hero__eyebrow">SIGNALPHA MISSION CONTROL</div>
              <h1 className="mc-hero__title">5 Bots · 5 Strategies · 1 Battle</h1>
            </div>
            {data.next_signal && countdownMs !== null && (
              <div className="mc-next" style={{ borderColor: data.next_signal.strategy_color }}>
                <div className="mc-next__label">NEXT SIGNAL FIRES IN</div>
                <div className="mc-next__time mono" style={{ color: data.next_signal.strategy_color }}>
                  {fmtCountdown(countdownMs)}
                </div>
                <div className="mc-next__detail">
                  <span className="mc-next__emoji">{data.next_signal.strategy_emoji}</span>
                  <span style={{ color: data.next_signal.strategy_color, fontWeight: 700 }}>
                    {data.next_signal.strategy_name}
                  </span>
                  →
                  <span style={{ color: data.next_signal.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700 }}>
                    {data.next_signal.side === 'LONG' ? '↑ LONG' : '↓ SHORT'}
                  </span>
                  <span className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>{data.next_signal.ticker}</span>
                  <span className="mc-next__when">
                    {data.next_signal.earnings_date.slice(5)} @ {data.next_signal.fires_at_clock}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ SCROLLING TICKER TAPE ═══ */}
      {data.live_feed.length > 0 && (
        <div className="mc-tape-wrap">
          <div className="mc-tape">
            <div className="mc-tape__scroll">
              {[...data.live_feed, ...data.live_feed].map((e, i) => {
                const strat = data.strategies.find(s => s.code === e.strategy)
                if (!strat) return null
                return (
                  <span key={i} className="mc-tape__item">
                    <span className="mc-tape__t mono">{e.timestamp.slice(5, 10)}</span>
                    <span className="mc-tape__s" style={{ color: strat.color }}>{strat.emoji} {strat.name}</span>
                    <span className="mc-tape__a">
                      {e.type === 'open' ? '→ OPEN' : '✓ CLOSE'}
                    </span>
                    <span style={{ color: e.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700 }}>
                      {e.side}
                    </span>
                    <span className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>{e.ticker}</span>
                    {e.return_pct !== undefined && (
                      <span className="mono" style={{ color: (e.return_pct ?? 0) >= 0 ? '#4ade80' : '#f87171', fontWeight: 700 }}>
                        {(e.return_pct ?? 0) >= 0 ? '+' : ''}{e.return_pct?.toFixed(2)}%
                      </span>
                    )}
                    <span className="mc-tape__div">•</span>
                  </span>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* ═══ 5 BIG BOARDS ═══ */}
      <div className="mc-boards">
        {data.strategies.map((s, i) => {
          const equity = s.equity_curve.map(p => p.equity)
          const isActive = selectedStrat === s.code
          const isLeader = i === 0
          return (
            <BigBoard key={s.code} strategy={s} equity={equity}
              rank={i + 1} isActive={isActive} isLeader={isLeader}
              onClick={() => setSelectedStrat(isActive ? null : s.code)} />
          )
        })}
      </div>

      {/* ═══ RACE CHART ═══ */}
      <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
        <div className="mc-panel__title">
          <Activity size={14} /> RACE CHART
          <span className="mc-panel__sub">cumulative return since {data.launch_date}</span>
        </div>
        <div style={{ height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={mergedCurve} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(56,189,248,0.06)" />
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
                    <div className="mc-tt">
                      <div className="mc-tt__date mono">{label}</div>
                      {sorted.map((p: any) => {
                        const st = data.strategies.find(x => x.code === p.dataKey)
                        if (!st) return null
                        return (
                          <div key={p.dataKey} className="mc-tt__row">
                            <span>{st.emoji} {st.name}</span>
                            <b style={{ color: p.value >= 0 ? st.color : '#f87171' }}>
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
                  strokeWidth={selectedStrat === null || selectedStrat === s.code ? 2.5 : 0.6}
                  strokeOpacity={selectedStrat === null || selectedStrat === s.code ? 1 : 0.18}
                  dot={false} animationDuration={1200} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </motion.div>

      {/* ═══ SIGNAL CALENDAR ═══ */}
      <SignalCalendar data={data} />

      {/* ═══ EVENT LOG ═══ */}
      <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
        <div className="mc-panel__title">
          <Radio size={14} /> EVENT LOG
          <span className="mc-panel__sub">last 30 trade events with precise timestamps</span>
        </div>
        <div className="mc-log">
          {data.live_feed.map((e, i) => {
            const strat = data.strategies.find(s => s.code === e.strategy)
            if (!strat) return null
            return (
              <motion.div key={i} className="mc-log__row"
                initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.015 }}>
                <span className="mc-log__time mono">{e.timestamp.slice(0, 10)} {e.type === 'open' ? '09:30' : '16:00'} ET</span>
                <span className="mc-log__strat" style={{ color: strat.color }}>
                  {strat.emoji} {strat.name}
                </span>
                <span className="mc-log__verb" style={{ color: e.type === 'open' ? '#38bdf8' : '#a78bfa' }}>
                  {e.type === 'open' ? 'OPENED' : 'CLOSED'}
                </span>
                <span style={{ color: e.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700, fontSize: '0.7rem' }}>
                  {e.side === 'LONG' ? '↑ LONG' : '↓ SHORT'}
                </span>
                <span className="mono mc-log__tk">{e.ticker}</span>
                {e.return_pct !== undefined && (
                  <span className="mono mc-log__ret" style={{ color: (e.return_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                    {(e.return_pct ?? 0) >= 0 ? '+' : ''}{e.return_pct?.toFixed(2)}%
                  </span>
                )}
              </motion.div>
            )
          })}
        </div>
      </motion.div>
    </div>
  )
}


function BigBoard({ strategy: s, equity, rank, isActive, isLeader, onClick }: {
  strategy: Strategy; equity: number[]; rank: number;
  isActive: boolean; isLeader: boolean; onClick: () => void;
}) {
  const ret = useCountUp(s.total_return * 100)
  const equityUSD = useCountUp(s.final_equity)
  return (
    <motion.button
      className={`mc-board ${isActive ? 'mc-board--active' : ''} ${isLeader ? 'mc-board--leader' : ''}`}
      onClick={onClick}
      layout
      initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.08 + rank * 0.04 }}
      style={{ '--strat-color': s.color } as React.CSSProperties}
    >
      <div className="mc-board__top">
        <div className="mc-board__rank">#{rank}</div>
        <div className="mc-board__name-wrap">
          <span className="mc-board__emoji">{s.emoji}</span>
          <div>
            <div className="mc-board__name">{s.name}</div>
            <div className="mc-board__tag">{s.tagline}</div>
          </div>
        </div>
        {isLeader && <div className="mc-board__leader-badge">LEADER</div>}
      </div>

      <div className="mc-board__lcd">
        <div className="mc-board__lcd-bg" />
        <div className={`mc-board__lcd-num mono ${ret >= 0 ? 'up' : 'down'}`}>
          {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
        </div>
        <div className="mc-board__lcd-sub mono">{fmtDollar(equityUSD)}</div>
      </div>

      <svg className="mc-board__spark" viewBox="0 0 100 30" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`grad-${s.code}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={s.color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={s.color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={sparkPath(equity, 100, 30)} fill="none" stroke={s.color} strokeWidth="1.6" />
        <path d={`${sparkPath(equity, 100, 30)} L 100 30 L 0 30 Z`} fill={`url(#grad-${s.code})`} />
      </svg>

      <div className="mc-board__metrics">
        <div className="mc-board__metric">
          <div className="mc-board__metric-l">SHARPE</div>
          <div className="mc-board__metric-v mono">{s.sharpe.toFixed(2)}</div>
        </div>
        <div className="mc-board__metric">
          <div className="mc-board__metric-l">OPEN</div>
          <div className="mc-board__metric-v mono">{s.currently_open.length}</div>
        </div>
        <div className="mc-board__metric">
          <div className="mc-board__metric-l">TRADES</div>
          <div className="mc-board__metric-v mono">{s.trades}</div>
        </div>
        <div className="mc-board__metric">
          <div className="mc-board__metric-l">WIN %</div>
          <div className="mc-board__metric-v mono">{(s.win_rate * 100).toFixed(0)}%</div>
        </div>
      </div>

      {s.currently_open.length > 0 && (
        <div className="mc-board__chips">
          {s.currently_open.slice(0, 4).map((p, i) => (
            <span key={i} className="mc-chip">
              <span style={{ color: p.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700 }}>
                {p.side === 'LONG' ? '↑' : '↓'}
              </span>
              <span className="mono">{p.ticker}</span>
              <span className="mc-chip__d">d+{p.days_held}</span>
            </span>
          ))}
          {s.currently_open.length > 4 && (
            <span className="mc-chip mc-chip--more">+{s.currently_open.length - 4}</span>
          )}
        </div>
      )}
    </motion.button>
  )
}


function SignalCalendar({ data }: { data: Showdown }) {
  // Group pending signals by date
  const byDate = new Map<string, { date: string; signals: (PendingSignal & { strategy: Strategy })[] }>()
  data.strategies.forEach(s => {
    s.pending_signals.forEach(p => {
      const key = p.earnings_date
      if (!byDate.has(key)) byDate.set(key, { date: key, signals: [] })
      byDate.get(key)!.signals.push({ ...p, strategy: s })
    })
  })
  const days = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date))

  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
      <div className="mc-panel__title">
        <Target size={14} /> SIGNAL CALENDAR
        <span className="mc-panel__sub">next 14 days · which strategies will fire on which earnings</span>
      </div>
      {days.length === 0 ? (
        <div className="mc-empty">No pending signals. All strategies sitting in cash.</div>
      ) : (
        <div className="mc-cal">
          {days.slice(0, 14).map((d) => {
            // Group same-ticker signals
            const byTicker = new Map<string, (PendingSignal & { strategy: Strategy })[]>()
            d.signals.forEach(sig => {
              if (!byTicker.has(sig.ticker)) byTicker.set(sig.ticker, [])
              byTicker.get(sig.ticker)!.push(sig)
            })
            return (
              <div key={d.date} className="mc-cal__day">
                <div className="mc-cal__date mono">{d.date.slice(5)}</div>
                <div className="mc-cal__tickers">
                  {Array.from(byTicker.entries()).map(([ticker, sigs]) => (
                    <div key={ticker} className="mc-cal__tk-row">
                      <span className="mc-cal__tk mono">{ticker}</span>
                      <span className="mc-cal__rt mono">{sigs[0].report_time}</span>
                      <span className="mc-cal__sd" style={{ color: sigs[0].side === 'LONG' ? '#4ade80' : '#f87171' }}>
                        {sigs[0].side === 'LONG' ? '↑' : '↓'}
                      </span>
                      <span className="mc-cal__clock mono">@{sigs[0].fires_at_clock}</span>
                      <div className="mc-cal__bots">
                        {sigs.map(sig => (
                          <span key={sig.strategy.code} title={`${sig.strategy.name} (${sig.confidence}% conf)`}
                            style={{ color: sig.strategy.color }}>
                            {sig.strategy.emoji}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </motion.div>
  )
}
