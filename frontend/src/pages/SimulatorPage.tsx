import { motion, AnimatePresence } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Award,
  Briefcase,
  Circle,
  CircleDollarSign,
  Clock,
  DollarSign,
  Flame,
  Gauge,
  Layers,
  Pause,
  Play,
  PlayCircle,
  Radar,
  RefreshCw,
  RotateCcw,
  Target,
  TrendingDown,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from 'recharts'

// ============================================================
//  Types (subset — matches v3 backend payload)
// ============================================================

type SimState = {
  snapshot_at: string | null
  cash: number
  positions_value: number
  total_equity: number
  total_return_pct: number
  leverage_used: number
  num_open_positions: number
  num_trades_total: number
  sharpe: number | null
  max_drawdown_pct: number | null
  win_rate: number | null
}

type SimPosition = {
  id: number
  ticker: string
  sector: string | null
  side: 'LONG' | 'SHORT'
  shares: number
  entry_price: number
  entry_date: string
  earnings_date: string
  target_exit_date: string
  leverage: number
  notional_value: number
  margin_used: number
  predicted_direction: 'UP' | 'DOWN'
  confidence: number
  expected_move_pct: number | null
  last_mark_price: number | null
  last_mark_at: string | null
  unrealized_pnl: number
  unrealized_pnl_pct: number
}

type SimTrade = {
  id: number
  ticker: string
  sector: string | null
  side: 'LONG' | 'SHORT'
  action: 'OPEN' | 'CLOSE'
  shares: number
  price: number
  notional: number
  leverage: number
  confidence: number | null
  predicted_direction: 'UP' | 'DOWN' | null
  realized_pnl: number | null
  realized_pnl_pct: number | null
  holding_days: number | null
  exit_reason: string | null
  executed_at: string | null
}

type SimPending = {
  ticker: string
  company_name: string | null
  sector: string | null
  earnings_date: string
  report_time: string | null
  confidence: number
  direction: 'UP' | 'DOWN'
  expected_move_pct: number | null
  already_held: boolean
  tradeable: boolean
  skip_reason: string | null
}

type SimRealised = {
  total_pnl: number
  n_trades: number
  n_winning: number
  n_losing: number
  avg_win: number
  avg_loss: number
  best_trade: number
  worst_trade: number
  recent_closes: {
    ticker: string
    side: 'LONG' | 'SHORT'
    exit_reason: string | null
    realized_pnl: number | null
    realized_pnl_pct: number | null
    holding_days: number | null
    executed_at: string | null
  }[]
}

type SimConfig = {
  initial_capital: number
  confidence_threshold: number
  base_position_pct: number
  max_position_pct: number
  portfolio_leverage_cap: number
  stop_loss_pct: number
  take_profit_pct: number
  holding_days: number
  slippage_bps: number
  last_step_at: string | null
  started_at: string | null
}

type MarketStatus = {
  status: 'OPEN' | 'CLOSED' | 'PRE_MARKET' | 'AFTER_HOURS'
  label: string
  et_time: string
}

type SimDashboard = {
  config: SimConfig
  state: SimState
  positions: SimPosition[]
  trades: SimTrade[]
  equity_curve: { t: string; equity: number }[]
  pending: SimPending[]
  realised: SimRealised
  market_status: MarketStatus
  server_time: string
}

// ============================================================
//  API
// ============================================================

const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL ?? '/api/v1'

async function fetchDashboard(): Promise<SimDashboard> {
  const r = await fetch(`${API_BASE}/simulator/dashboard`)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

async function runStep() {
  const r = await fetch(`${API_BASE}/simulator/run-step`, { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

async function resetSim() {
  const r = await fetch(`${API_BASE}/simulator/reset`, { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
}

// ============================================================
//  Helpers
// ============================================================

const fmtUSD = (n: number, decimals = 0) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: decimals, maximumFractionDigits: decimals })

const fmtNum = (n: number, decimals = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

const fmtPct = (n: number, decimals = 2) => `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const dt = new Date(iso)
  const sec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000))
  if (sec < 5) return 'just now'
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.floor(hr / 24)}d ago`
}

function useTick(intervalMs: number = 1000) {
  const [, set] = useState(0)
  useEffect(() => {
    const id = setInterval(() => set((n) => n + 1), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
}

// Live Eastern-Time clock, computed entirely in the browser so it ticks every
// second without waiting for the backend.
function useETClock(): { time: string; status: 'OPEN' | 'PRE_MARKET' | 'AFTER_HOURS' | 'CLOSED'; label: string } {
  useTick(1000)
  // No useMemo here — useTick triggers a re-render every second, so we just
  // recompute inline on each render. useMemo with [] would freeze at mount.
  const now = new Date()
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    weekday: 'short',
  })
  const parts = fmt.formatToParts(now)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const hh = parseInt(get('hour') || '0', 10)
  const mm = parseInt(get('minute') || '0', 10)
  const ss = get('second')
  const wd = get('weekday')
  const mins = hh * 60 + mm
  const isWeekend = wd === 'Sat' || wd === 'Sun'
  let status: 'OPEN' | 'PRE_MARKET' | 'AFTER_HOURS' | 'CLOSED' = 'CLOSED'
  let label = 'Closed'
  if (isWeekend) {
    status = 'CLOSED'; label = 'Weekend'
  } else if (mins < 4 * 60) {
    status = 'CLOSED'; label = 'Closed'
  } else if (mins < 9 * 60 + 30) {
    status = 'PRE_MARKET'; label = 'Pre-market'
  } else if (mins < 16 * 60) {
    status = 'OPEN'; label = 'Market open'
  } else if (mins < 20 * 60) {
    status = 'AFTER_HOURS'; label = 'After hours'
  }
  return {
    time: `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${ss}`,
    status,
    label,
  }
}

// ============================================================
//  Animated counter
// ============================================================

function MoneyCounter({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const [n, setN] = useState(value)
  const prev = useRef(value)
  useEffect(() => {
    const start = prev.current
    const delta = value - start
    if (Math.abs(delta) < 0.5) {
      setN(value)
      prev.current = value
      return
    }
    const t0 = performance.now()
    const dur = 700
    let raf = 0
    const tick = (now: number) => {
      const e = Math.min(1, (now - t0) / dur)
      const ease = 1 - Math.pow(1 - e, 3)
      setN(start + delta * ease)
      if (e < 1) raf = requestAnimationFrame(tick)
      else prev.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <>{fmtUSD(n, decimals)}</>
}

// ============================================================
//  Bloomberg ticker tape (horizontal marquee)
// ============================================================

function TickerTape({ positions }: { positions: SimPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="sim-tape-bar sim-tape-bar--empty">
        <span className="sim-tape-bar__lead">
          <Radar size={11} /> NO ACTIVE POSITIONS
        </span>
      </div>
    )
  }
  const items = positions.map((p) => ({
    ticker: p.ticker,
    price: p.last_mark_price ?? p.entry_price,
    pct: p.unrealized_pnl_pct ?? 0,
    side: p.side,
  }))
  // Repeat the sequence so the marquee wraps seamlessly
  const seq = [...items, ...items, ...items]
  return (
    <div className="sim-tape-bar">
      <span className="sim-tape-bar__lead">
        <Radar size={11} className="sim-pulse-icon" /> LIVE BOOK
      </span>
      <div className="sim-tape-bar__marquee">
        <div className="sim-tape-bar__track">
          {seq.map((it, i) => (
            <span key={i} className="sim-tape-bar__cell">
              <span className="sim-tape-bar__sym">{it.ticker}</span>
              <span className={`sim-tape-bar__side sim-tape-bar__side--${it.side.toLowerCase()}`}>
                {it.side === 'LONG' ? 'L' : 'S'}
              </span>
              <span className="sim-tape-bar__price mono">${fmtNum(it.price)}</span>
              <span className={`sim-tape-bar__chg ${it.pct >= 0 ? 'pnl-up' : 'pnl-down'} mono`}>
                {fmtPct(it.pct * 100, 2)}
              </span>
              <span className="sim-tape-bar__divider">·</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ============================================================
//  Equity curve — anchored y-axis, reference line at initial
// ============================================================

function EquityCurve({ data, initial }: { data: SimDashboard['equity_curve']; initial: number }) {
  const equities = data.map((p) => p.equity)
  const minE = equities.length ? Math.min(...equities, initial) : initial
  const maxE = equities.length ? Math.max(...equities, initial) : initial
  const halfRange = Math.max(
    Math.abs(maxE - initial),
    Math.abs(minE - initial),
    initial * 0.02,
  ) * 1.4
  const yMin = initial - halfRange
  const yMax = initial + halfRange
  const inProfit = data.length > 0 && data[data.length - 1].equity >= initial
  const chartData = data.map((p, i) => ({
    idx: i,
    equity: p.equity,
    label: new Date(p.t).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    }),
  }))

  return (
    <div className="sim-chart-wrap">
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 8, bottom: 8 }}>
          <defs>
            <linearGradient id="equityGradGreen" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(52, 211, 153, 0.45)" />
              <stop offset="100%" stopColor="rgba(52, 211, 153, 0)" />
            </linearGradient>
            <linearGradient id="equityGradRed" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(248, 113, 113, 0.4)" />
              <stop offset="100%" stopColor="rgba(248, 113, 113, 0)" />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(148,163,214,0.06)" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }}
            stroke="var(--border)" interval="preserveStartEnd" minTickGap={56} />
          <YAxis
            tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }}
            stroke="var(--border)"
            tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
            domain={[yMin, yMax]}
            width={68}
          />
          <ReferenceLine
            y={initial}
            stroke="rgba(148,163,214,0.4)"
            strokeDasharray="4 4"
            label={{
              value: `start ${fmtUSD(initial)}`,
              position: 'insideTopLeft',
              fill: 'var(--text-tertiary)',
              fontSize: 10,
            }}
          />
          <ReTooltip
            contentStyle={{ background: 'rgba(10,14,26,0.92)', border: '1px solid var(--border-strong)', borderRadius: 10, fontSize: 12 }}
            labelStyle={{ color: 'var(--text-tertiary)', fontSize: 11 }}
            formatter={(v: number) => [fmtUSD(v), 'Equity']}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke={inProfit ? 'var(--accent-emerald)' : '#f87171'}
            strokeWidth={2}
            fill={inProfit ? 'url(#equityGradGreen)' : 'url(#equityGradRed)'}
            isAnimationActive
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ============================================================
//  Side badge
// ============================================================

function SideBadge({ side, size = 'md' }: { side: 'LONG' | 'SHORT'; size?: 'sm' | 'md' }) {
  return (
    <span className={`sim-side-badge sim-side-badge--${side.toLowerCase()} sim-side-badge--${size}`}>
      {side === 'LONG' ? <ArrowUp size={size === 'sm' ? 10 : 11} /> : <ArrowDown size={size === 'sm' ? 10 : 11} />}
      {side}
    </span>
  )
}

function skipReasonLabel(reason: string | null): string | null {
  if (!reason) return null
  if (reason === 'today_amc') return 'opens at close'
  if (reason.startsWith('today_BMO')) return 'reported pre-market'
  if (reason.startsWith('today_DMT')) return 'reports during session'
  if (reason.startsWith('today_')) return 'today · skipped'
  if (reason === 'tomorrow') return 'eligible'
  if (reason.startsWith('too_early_')) {
    const n = reason.split('_').pop()
    return `entry T-1 (in ${n})`
  }
  if (reason === 'outcome_already_recorded') return 'already reported'
  if (reason === 'earnings_already_passed') return 'past'
  return reason
}

// ============================================================
//  Main page
// ============================================================

export function SimulatorPage() {
  const [data, setData] = useState<SimDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [running, setRunning] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null)
  const [autoStep, setAutoStep] = useState(true)
  const prevEquity = useRef<number | null>(null)
  const [equityFlash, setEquityFlash] = useState<'up' | 'down' | null>(null)
  const etClock = useETClock()

  useTick(1000)

  const load = useCallback(async (kind: 'initial' | 'refresh' | 'silent' = 'silent') => {
    if (kind === 'initial') setLoading(true)
    if (kind === 'refresh') setRefreshing(true)
    try {
      setError(null)
      const d = await fetchDashboard()
      if (prevEquity.current != null && Math.abs(d.state.total_equity - prevEquity.current) > 0.5) {
        setEquityFlash(d.state.total_equity > prevEquity.current ? 'up' : 'down')
        setTimeout(() => setEquityFlash(null), 1200)
      }
      prevEquity.current = d.state.total_equity
      setData(d)
      setLastFetchedAt(new Date())
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load')
    } finally {
      if (kind === 'initial') setLoading(false)
      if (kind === 'refresh') setTimeout(() => setRefreshing(false), 300)
    }
  }, [])

  // Initial + background refresh every 15s.
  // Also fires immediately when the tab becomes visible again — browsers
  // throttle setInterval in hidden tabs, so without this the data goes stale
  // whenever the user switches away and comes back.
  useEffect(() => {
    load('initial')
    const id = setInterval(() => load('silent'), 15_000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') load('silent')
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [load])

  // Auto-step loop: when enabled, posts /run-step every 60s, then refetches.
  useEffect(() => {
    if (!autoStep) return
    let cancelled = false
    const id = setInterval(async () => {
      if (cancelled) return
      try {
        await runStep()
        await load('silent')
      } catch (e: any) {
        setError(e?.message ?? 'Auto-step failed')
      }
    }, 30_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [autoStep, load])

  const onRunStep = async () => {
    setRunning(true)
    try {
      await runStep()
      await load('refresh')
    } catch (e: any) {
      setError(e?.message ?? 'Run failed')
    } finally {
      setRunning(false)
    }
  }

  const onReset = async () => {
    setResetting(true)
    try {
      await resetSim()
      await load('refresh')
      setConfirmReset(false)
    } catch (e: any) {
      setError(e?.message ?? 'Reset failed')
    } finally {
      setResetting(false)
    }
  }

  if (loading) {
    return (
      <div className="sim-loading">
        <div className="sim-loading__pulse" />
        <div>Booting trading desk…</div>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="sim-loading">
        <div>Failed to load</div>
        {error && <div className="sim-loading__err">{error}</div>}
      </div>
    )
  }

  const { state, positions, trades, equity_curve, pending, config, realised } = data
  const initial = config.initial_capital
  const profit = state.total_equity - initial
  const inProfit = profit >= 0

  return (
    <div className="sim-page">
      <div className="sim-bg" aria-hidden>
        <div className={`sim-bg__orb ${inProfit ? 'sim-bg__orb--green' : 'sim-bg__orb--red'}`} />
        <div className="sim-bg__grid" />
      </div>

      {/* ============ Bloomberg ticker tape ============ */}
      <TickerTape positions={positions} />

      {/* ============ HERO ============ */}
      <section className="sim-hero">
        <div className="sim-hero__left">
          <div className="sim-hero__topline">
            <div className="sim-eyebrow">
              <Activity size={12} />
              <span>Live trading simulator</span>
            </div>
            <div className={`sim-market-badge sim-market-badge--${
              etClock.status === 'OPEN' ? 'open'
                : etClock.status === 'PRE_MARKET' || etClock.status === 'AFTER_HOURS' ? 'extended'
                : 'closed'
            }`}>
              <span className="sim-market-badge__dot" />
              <span className="sim-market-badge__label">{etClock.label.toUpperCase()}</span>
              <span className="sim-market-badge__sep">·</span>
              <span className="sim-market-badge__time mono">NYSE {etClock.time} ET</span>
            </div>
          </div>

          <div className="sim-equity">
            <div className="sim-equity__label">Total portfolio value</div>
            <div className="sim-equity__valuewrap">
              <div className={`sim-equity__rings ${inProfit ? 'sim-equity__rings--green' : 'sim-equity__rings--red'}`}>
                <div className="sim-equity__ring sim-equity__ring--1" />
                <div className="sim-equity__ring sim-equity__ring--2" />
                <div className="sim-equity__ring sim-equity__ring--3" />
              </div>
              <div className={`sim-equity__value ${inProfit ? 'sim-equity__value--up' : 'sim-equity__value--down'} ${
                equityFlash ? `sim-equity__value--flash-${equityFlash}` : ''
              }`}>
                <MoneyCounter value={state.total_equity} decimals={0} />
              </div>
            </div>
            <div className={`sim-equity__delta ${inProfit ? 'sim-equity__delta--up' : 'sim-equity__delta--down'}`}>
              {inProfit ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              <span className="tabular-nums">{fmtUSD(profit)}</span>
              <span className="sim-equity__sep">·</span>
              <span className="tabular-nums">{fmtPct(state.total_return_pct)}</span>
              <span className="sim-equity__base">
                since {fmtUSD(initial)} on {config.started_at ? new Date(config.started_at).toLocaleDateString() : 'inception'}
              </span>
            </div>
          </div>
        </div>

        <div className="sim-hero__right">
          <div className="sim-hero__meta">
            <div className="sim-hero__metarow">
              <span className="sim-hero__metalbl">Last simulation step</span>
              <span className="sim-hero__metaval mono">{state.snapshot_at ? timeAgo(state.snapshot_at) : 'never'}</span>
            </div>
            <div className="sim-hero__metarow">
              <span className="sim-hero__metalbl">Data refreshed</span>
              <span className="sim-hero__metaval mono">{lastFetchedAt ? timeAgo(lastFetchedAt.toISOString()) : '—'}</span>
            </div>
            <div className="sim-hero__metarow">
              <span className="sim-hero__metalbl">Auto-step</span>
              <span className="sim-hero__metaval mono">{autoStep ? 'every 60 sec' : 'paused'}</span>
            </div>
          </div>
          <div className="sim-btn-row">
            <button
              className={`sim-btn ${autoStep ? 'sim-btn--ghost-on' : 'sim-btn--ghost'}`}
              onClick={() => setAutoStep((s) => !s)}
              title="When ON, the simulator runs a step every 60 seconds automatically"
            >
              {autoStep ? <Pause size={14} /> : <Play size={14} />}
              <span>{autoStep ? 'Auto-stepping' : 'Auto-step OFF'}</span>
            </button>
            <button className="sim-btn sim-btn--primary" onClick={onRunStep} disabled={running}>
              {running ? <RefreshCw size={15} className="spin" /> : <PlayCircle size={15} />}
              <span>{running ? 'Running step…' : 'Run next step'}</span>
            </button>
            <button className="sim-btn sim-btn--ghost" onClick={() => load('refresh')} disabled={refreshing}>
              <RefreshCw size={14} className={refreshing ? 'spin' : ''} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </button>
            {!confirmReset ? (
              <button className="sim-btn sim-btn--danger" onClick={() => setConfirmReset(true)}>
                <RotateCcw size={14} /> Reset to ${(initial / 1_000_000).toFixed(0)}M
              </button>
            ) : (
              <div className="sim-confirm">
                <span>Wipe all trades?</span>
                <button className="sim-btn sim-btn--danger sim-btn--small" onClick={onReset} disabled={resetting}>
                  {resetting ? '…' : 'Confirm'}
                </button>
                <button className="sim-btn sim-btn--ghost sim-btn--small" onClick={() => setConfirmReset(false)}>
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      {error && <div className="sim-error">{error}</div>}

      {/* ============ KPI strip ============ */}
      <section className="sim-kpi-strip">
        <Kpi
          icon={Wallet}
          label="Cash available"
          value={fmtUSD(state.cash)}
          tint="cyan"
          sub={`${((state.cash / state.total_equity) * 100).toFixed(1)}% of equity`}
        />
        <Kpi
          icon={Briefcase}
          label="Positions value"
          value={fmtUSD(state.positions_value)}
          tint="purple"
          sub={`${state.num_open_positions} open · ${state.num_trades_total} trades total`}
        />
        <Kpi
          icon={Gauge}
          label="Leverage used"
          value={`${state.leverage_used.toFixed(2)}×`}
          tint={state.leverage_used > 2 ? 'amber' : 'emerald'}
          sub={`cap ${config.portfolio_leverage_cap}× · margin discipline`}
        />
        <Kpi
          icon={Target}
          label="Sharpe (annualised)"
          value={state.sharpe == null ? '—' : state.sharpe.toFixed(2)}
          tint={(state.sharpe ?? 0) > 1 ? 'emerald' : 'cyan'}
          sub={state.win_rate == null ? 'Awaiting trades' : `${(state.win_rate * 100).toFixed(0)}% win rate`}
        />
        <Kpi
          icon={Zap}
          label="Max drawdown"
          value={state.max_drawdown_pct == null ? '—' : `${state.max_drawdown_pct.toFixed(2)}%`}
          tint="amber"
          sub="peak-to-trough"
        />
      </section>

      {/* ============ Equity curve ============ */}
      <section className="sim-card">
        <div className="sim-card__head">
          <div className="sim-card__kicker">
            <TrendingUp size={12} /> Equity curve
          </div>
          <div className="sim-card__title">Portfolio value over time</div>
        </div>
        {equity_curve.length === 0 ? (
          <div className="sim-empty">
            No history yet. Click <strong>Run next step</strong> or enable <strong>Auto-step</strong>.
          </div>
        ) : (
          <EquityCurve data={equity_curve} initial={initial} />
        )}
      </section>

      {/* ============ Realised P&L card ============ */}
      <section className="sim-card sim-card--realised">
        <div className="sim-card__head">
          <div className="sim-card__kicker">
            <CircleDollarSign size={12} /> Closed trades · realised P&amp;L
          </div>
          <div className="sim-card__title">
            {realised.n_trades === 0
              ? 'No closed trades yet'
              : `Net ${realised.total_pnl >= 0 ? 'profit' : 'loss'} from ${realised.n_trades} closed trade${realised.n_trades === 1 ? '' : 's'}`}
          </div>
        </div>

        <div className="sim-realised-grid">
          <div className={`sim-realised-hero ${realised.total_pnl >= 0 ? 'sim-realised-hero--up' : 'sim-realised-hero--down'}`}>
            <div className="sim-realised-hero__label">Total realised P&amp;L</div>
            <div className="sim-realised-hero__value mono">{fmtUSD(realised.total_pnl)}</div>
            <div className="sim-realised-hero__sub">
              {realised.n_trades === 0
                ? 'positions still open'
                : `${realised.n_winning} wins · ${realised.n_losing} losses`}
            </div>
          </div>
          <RealisedStat icon={Award}      label="Avg win"     value={realised.n_winning ? fmtUSD(realised.avg_win) : '—'}     tint="up" />
          <RealisedStat icon={TrendingDown} label="Avg loss"  value={realised.n_losing ? fmtUSD(realised.avg_loss) : '—'}    tint="down" />
          <RealisedStat icon={Flame}      label="Best trade"  value={realised.best_trade ? fmtUSD(realised.best_trade) : '—'}  tint="up" />
          <RealisedStat icon={Flame}      label="Worst trade" value={realised.worst_trade ? fmtUSD(realised.worst_trade) : '—'} tint="down" />
        </div>

        {realised.recent_closes.length > 0 && (
          <div className="sim-realised-list">
            <div className="sim-realised-list__head">Most recent closes</div>
            <div className="sim-realised-list__rows">
              {realised.recent_closes.map((c, i) => {
                const pnlPos = (c.realized_pnl ?? 0) >= 0
                return (
                  <div key={i} className="sim-realised-row">
                    <span className="sim-realised-row__sym mono">{c.ticker}</span>
                    <SideBadge side={c.side} size="sm" />
                    <span className="sim-realised-row__reason">{c.exit_reason}</span>
                    <span className="sim-realised-row__hold">held {c.holding_days ?? 0}d</span>
                    <span className={`sim-realised-row__pnl mono ${pnlPos ? 'pnl-up' : 'pnl-down'}`}>
                      {fmtUSD(c.realized_pnl ?? 0)}
                      <span className="pnl-pct">{fmtPct((c.realized_pnl_pct ?? 0) * 100, 1)}</span>
                    </span>
                    <span className="sim-realised-row__time">
                      {c.executed_at ? new Date(c.executed_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </section>

      {/* ============ Active positions + Trade tape ============ */}
      <div className="sim-2col">
        <section className="sim-card sim-card--positions">
          <div className="sim-card__head">
            <div className="sim-card__kicker">
              <Layers size={12} /> Active positions
            </div>
            <div className="sim-card__title">{positions.length} open</div>
          </div>
          {positions.length === 0 ? (
            <div className="sim-empty">No open positions.</div>
          ) : (
            <div className="sim-table-wrap">
              <table className="sim-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Side</th>
                    <th className="r">Entry</th>
                    <th className="r">Mark</th>
                    <th className="r">Notional</th>
                    <th className="r">Lev</th>
                    <th className="r">Conf</th>
                    <th className="r">Unrealized</th>
                    <th className="r">Exit</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const pnlPos = (p.unrealized_pnl ?? 0) >= 0
                    return (
                      <tr key={p.id}>
                        <td>
                          <div className="sim-ticker">
                            <span className="sim-ticker__sym">{p.ticker}</span>
                            {p.sector && <span className="sim-ticker__sector">{p.sector}</span>}
                          </div>
                        </td>
                        <td><SideBadge side={p.side} size="sm" /></td>
                        <td className="r mono">${fmtNum(p.entry_price)}</td>
                        <td className="r mono">{p.last_mark_price ? `$${fmtNum(p.last_mark_price)}` : '—'}</td>
                        <td className="r mono">{fmtUSD(p.notional_value)}</td>
                        <td className="r mono">{p.leverage.toFixed(1)}×</td>
                        <td className="r mono">{(p.confidence * 100).toFixed(0)}%</td>
                        <td className={`r mono ${pnlPos ? 'pnl-up' : 'pnl-down'}`}>
                          {fmtUSD(p.unrealized_pnl ?? 0)}
                          <div className="pnl-pct">{fmtPct((p.unrealized_pnl_pct ?? 0) * 100, 2)}</div>
                        </td>
                        <td className="r small">{new Date(p.target_exit_date).toLocaleDateString()}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="sim-card sim-card--ticker">
          <div className="sim-card__head">
            <div className="sim-card__kicker">
              <Activity size={12} /> Trade tape
            </div>
            <div className="sim-card__title">Last {trades.length} executions</div>
          </div>
          {trades.length === 0 ? (
            <div className="sim-empty">No trades yet.</div>
          ) : (
            <div className="sim-tape">
              <AnimatePresence initial={false}>
                {trades.map((t) => {
                  const closed = t.action === 'CLOSE' && t.realized_pnl != null
                  const pnlPos = (t.realized_pnl ?? 0) >= 0
                  return (
                    <motion.div
                      key={t.id}
                      className={`sim-tape__row sim-tape__row--${t.action.toLowerCase()}`}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.35 }}
                    >
                      <div className="sim-tape__left">
                        <div className={`sim-tape__chip sim-tape__chip--${t.action.toLowerCase()}-${t.side.toLowerCase()}`}>
                          <span>{t.action}</span>
                          {t.side === 'LONG' ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
                        </div>
                        <div className="sim-tape__sym mono">{t.ticker}</div>
                      </div>
                      <div className="sim-tape__mid">
                        <div className="sim-tape__time">
                          {t.executed_at
                            ? new Date(t.executed_at).toLocaleString('en-US', {
                                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                              })
                            : '—'}
                        </div>
                        <div className="sim-tape__detail">
                          {fmtNum(t.shares, 1)} sh @ ${fmtNum(t.price)} · {t.leverage.toFixed(1)}×
                        </div>
                      </div>
                      <div className={`sim-tape__pnl ${closed ? (pnlPos ? 'pnl-up' : 'pnl-down') : ''}`}>
                        {closed ? (
                          <>
                            <span className="mono">{fmtUSD(t.realized_pnl ?? 0)}</span>
                            <span className="pnl-pct">{fmtPct((t.realized_pnl_pct ?? 0) * 100, 1)}</span>
                            <span className="sim-tape__reason">{t.exit_reason}</span>
                          </>
                        ) : (
                          <span className="sim-tape__reason mono">{fmtUSD(t.notional)}</span>
                        )}
                      </div>
                    </motion.div>
                  )
                })}
              </AnimatePresence>
            </div>
          )}
        </section>
      </div>

      {/* ============ Pending entries ============ */}
      <section className="sim-card">
        <div className="sim-card__head">
          <div className="sim-card__kicker">
            <Target size={12} /> Strategy pipeline
          </div>
          <div className="sim-card__title">Upcoming earnings the strategy is watching ({pending.length})</div>
        </div>
        {pending.length === 0 ? (
          <div className="sim-empty">No qualifying setups in the next 5 days.</div>
        ) : (
          <div className="sim-pending-grid">
            {pending.map((p) => {
              const skipLabel = !p.tradeable ? skipReasonLabel(p.skip_reason) : null
              return (
                <div
                  key={`${p.ticker}-${p.earnings_date}`}
                  className={`sim-pending-card ${p.already_held ? 'sim-pending-card--held' : ''} ${
                    !p.tradeable && !p.already_held ? 'sim-pending-card--skip' : ''
                  } ${p.tradeable && !p.already_held ? 'sim-pending-card--ready' : ''}`}
                >
                  <div className="sim-pending-card__head">
                    <span className="sim-pending-card__sym">{p.ticker}</span>
                    <SideBadge side={p.direction === 'UP' ? 'LONG' : 'SHORT'} size="sm" />
                  </div>
                  {p.company_name && <div className="sim-pending-card__name">{p.company_name}</div>}
                  <div className="sim-pending-card__meta">
                    <span>
                      {new Date(p.earnings_date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                    </span>
                    {p.report_time && <span className="sim-pending-card__rt">{p.report_time}</span>}
                    {p.sector && <span className="sim-pending-card__sector">{p.sector}</span>}
                  </div>
                  <div className="sim-pending-card__stats">
                    <div className="sim-pending-card__stat">
                      <span className="lbl">Confidence</span>
                      <span className="val mono">{(p.confidence * 100).toFixed(1)}%</span>
                    </div>
                    <div className="sim-pending-card__stat">
                      <span className="lbl">Expected move</span>
                      <span className="val mono">±{((p.expected_move_pct ?? 0) * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                  <div className="sim-pending-card__foot">
                    {p.already_held ? (
                      <span className="sim-pending-card__pill sim-pending-card__pill--held">
                        <Circle size={6} fill="currentColor" /> in book
                      </span>
                    ) : p.tradeable ? (
                      <span className="sim-pending-card__pill sim-pending-card__pill--ready">
                        <Circle size={6} fill="currentColor" className="sim-pulse-icon" /> entry-window open
                      </span>
                    ) : (
                      <span className="sim-pending-card__pill sim-pending-card__pill--skip">{skipLabel}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* ============ Strategy disclosure ============ */}
      <section className="sim-card sim-card--meta">
        <div className="sim-card__head">
          <div className="sim-card__kicker">
            <DollarSign size={12} /> Strategy parameters
          </div>
          <div className="sim-card__title">Hard-coded for transparency</div>
        </div>
        <div className="sim-meta-grid">
          <MetaCell label="Confidence threshold" value={`≥ ${(config.confidence_threshold * 100).toFixed(0)}%`} />
          <MetaCell label="Base position" value={`${(config.base_position_pct * 100).toFixed(1)}% of equity`} />
          <MetaCell label="Max position" value={`${(config.max_position_pct * 100).toFixed(1)}% of equity`} />
          <MetaCell label="Leverage cap" value={`${config.portfolio_leverage_cap}× portfolio`} />
          <MetaCell label="Stop loss" value={`-${(config.stop_loss_pct * 100).toFixed(1)}%`} />
          <MetaCell label="Take profit" value={`+${(config.take_profit_pct * 100).toFixed(1)}%`} />
          <MetaCell label="Holding period" value={`T+${config.holding_days} days`} />
          <MetaCell label="Slippage" value={`${config.slippage_bps} bps each side`} />
          <MetaCell label="Entry window" value="T-1 day or T-0 AMC only" />
          <MetaCell label="Mark prices" value="24h yfinance · 30-min freshness gate" />
          <MetaCell label="Auto-step" value={autoStep ? 'every 60s' : 'paused'} />
          <MetaCell label="Data poll" value="every 15s" />
        </div>
      </section>
    </div>
  )
}

function Kpi({
  icon: Icon, label, value, sub, tint,
}: {
  icon: any; label: string; value: string; sub?: string;
  tint: 'cyan' | 'purple' | 'emerald' | 'amber'
}) {
  return (
    <div className={`sim-kpi sim-kpi--${tint}`}>
      <div className="sim-kpi__head">
        <span className="sim-kpi__icon"><Icon size={14} /></span>
        <span className="sim-kpi__label">{label}</span>
      </div>
      <div className="sim-kpi__value mono">{value}</div>
      {sub && <div className="sim-kpi__sub">{sub}</div>}
    </div>
  )
}

function RealisedStat({
  icon: Icon, label, value, tint,
}: {
  icon: any; label: string; value: string; tint: 'up' | 'down'
}) {
  return (
    <div className={`sim-realised-stat sim-realised-stat--${tint}`}>
      <div className="sim-realised-stat__head">
        <Icon size={12} />
        <span>{label}</span>
      </div>
      <div className="sim-realised-stat__val mono">{value}</div>
    </div>
  )
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="sim-meta-cell">
      <div className="sim-meta-cell__l">{label}</div>
      <div className="sim-meta-cell__v mono">{value}</div>
    </div>
  )
}
