import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Trophy, BookOpen, TrendingUp, TrendingDown } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts'

type Trade = {
  date: string; ticker: string; sector: string; side: string;
  return_pct: number; win: boolean
}
type Strategy = {
  code: string; name: string; emoji: string; tagline: string;
  citation: string; color: string; description: string;
  final_equity: number; total_return: number; trades: number; wins: number;
  win_rate: number; sharpe: number; sortino: number; max_drawdown: number;
  equity_curve: { date: string; equity: number; drawdown: number }[];
  recent_trades: Trade[];
}
type Showdown = {
  strategies: Strategy[]; events: number; initial_capital: number;
  start_date: string; end_date: string;
}

const RANK_EMOJI = ['🥇', '🥈', '🥉', '4.', '5.']
const fmt$ = (v: number) => `$${(v / 1000).toFixed(1)}k`
const fmtPct = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`

export function ShowdownPage() {
  const [data, setData] = useState<Showdown | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2026-04-30')
  const [selectedStrat, setSelectedStrat] = useState<string | null>(null)

  const load = async () => {
    setRunning(true)
    try {
      const r = await fetch(`/api/v1/showdown?start_date=${startDate}&end_date=${endDate}`)
      const d = await r.json()
      setData(d)
    } finally {
      setRunning(false); setLoading(false)
    }
  }

  useEffect(() => { load() /* eslint-disable-line */ }, [])

  // Merge all 5 equity curves into one dataset for the multi-line chart
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

  const allTrades = useMemo(() => {
    if (!data) return []
    const items: (Trade & { stratCode: string; stratEmoji: string; stratColor: string })[] = []
    data.strategies.forEach(s => {
      s.recent_trades.forEach(t => items.push({
        ...t, stratCode: s.code, stratEmoji: s.emoji, stratColor: s.color,
      }))
    })
    return items
      .filter(t => !selectedStrat || t.stratCode === selectedStrat)
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 30)
  }, [data, selectedStrat])

  if (loading) return (
    <div className="sw-loading">
      <div className="sw-loading__spinner" />
      <div>Loading showdown…</div>
    </div>
  )

  return (
    <div className="sw-page">
      <motion.div className="sw-hero" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <div className="sw-hero__badge"><span className="sw-hero__dot" />STRATEGY SHOWDOWN</div>
        <h1 className="sw-hero__title">5 Trading Philosophies. $1M Each. Who Wins?</h1>
        <p className="sw-hero__sub">
          Same data, same risk budget, five different schools of thought — from Bernard & Thomas's PEAD
          to Templeton's contrarianism to your own ML signal. Pick a date range and see who comes out on top.
        </p>
      </motion.div>

      <div className="sw-config">
        <div className="sw-config__field">
          <label>Start</label>
          <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="sw-input" />
        </div>
        <div className="sw-config__field">
          <label>End</label>
          <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="sw-input" />
        </div>
        <div className="sw-config__field sw-config__field--btn">
          <button className="sw-run" onClick={load} disabled={running}>
            {running ? <><span className="sw-run__spinner" />Running…</> : <><Play size={14} />Run Showdown</>}
          </button>
        </div>
      </div>

      {data && data.strategies.length > 0 && (
        <>
          {/* ── Leaderboard ────────────────────────── */}
          <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className="sw-card__title"><Trophy size={14} />Leaderboard <span className="sw-card__sub">{data.events.toLocaleString()} events · {data.start_date} → {data.end_date}</span></div>
            <div className="sw-board">
              {data.strategies.map((s, i) => (
                <motion.button key={s.code}
                  className={`sw-row ${selectedStrat === s.code ? 'sw-row--active' : ''}`}
                  onClick={() => setSelectedStrat(selectedStrat === s.code ? null : s.code)}
                  initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07 }}
                  style={{ borderLeft: `3px solid ${s.color}` }}>
                  <div className="sw-row__rank">{RANK_EMOJI[i]}</div>
                  <div className="sw-row__emoji">{s.emoji}</div>
                  <div className="sw-row__name">
                    <div className="sw-row__nameMain">{s.name}</div>
                    <div className="sw-row__tagline">{s.tagline}</div>
                  </div>
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
                    <div className="sw-row__label">Max DD</div>
                    <div className="sw-row__val mono" style={{ color: '#f87171' }}>{fmtPct(s.max_drawdown)}</div>
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
              ))}
            </div>
          </motion.div>

          {/* ── Race chart ──────────────────────────── */}
          <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
            <div className="sw-card__title">Race Chart <span className="sw-card__sub">cumulative return · click leaderboard row to isolate</span></div>
            <div style={{ height: 360 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mergedCurve} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false}
                    tickFormatter={v => v.slice(0, 7)} minTickGap={60} />
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
                                  {fmtPct(p.value / 100, 2)}
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
                      strokeWidth={selectedStrat === null || selectedStrat === s.code ? 2.2 : 0.6}
                      strokeOpacity={selectedStrat === null || selectedStrat === s.code ? 1 : 0.25}
                      dot={false} animationDuration={1500} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </motion.div>

          {/* ── Strategy Cards ──────────────────────── */}
          <div className="sw-cards">
            {data.strategies.map((s, i) => (
              <motion.div key={s.code} className="sw-cardlet"
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 + i * 0.06 }}
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
                  <div><span>Final</span><b>${(s.final_equity / 1000).toFixed(1)}k</b></div>
                  <div><span>Return</span><b style={{ color: s.total_return >= 0 ? s.color : '#f87171' }}>{fmtPct(s.total_return)}</b></div>
                  <div><span>Sharpe</span><b>{s.sharpe.toFixed(2)}</b></div>
                  <div><span>Sortino</span><b>{s.sortino.toFixed(2)}</b></div>
                </div>
                <div className="sw-cardlet__cite"><BookOpen size={11} /> {s.citation}</div>
              </motion.div>
            ))}
          </div>

          {/* ── Trade Attribution ───────────────────── */}
          <motion.div className="sw-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
            <div className="sw-card__title">
              Trade Attribution
              <span className="sw-card__sub">
                {selectedStrat
                  ? `filtering: ${data.strategies.find(s => s.code === selectedStrat)?.emoji} ${data.strategies.find(s => s.code === selectedStrat)?.name}`
                  : 'most recent trades across all strategies · click a strategy above to filter'}
              </span>
            </div>
            <div className="sw-trades-wrap">
              <table className="sw-trades">
                <thead><tr>
                  <th>Strategy</th><th>Date</th><th>Ticker</th><th>Sector</th>
                  <th>Side</th><th>Return</th><th>Verdict</th>
                </tr></thead>
                <tbody>
                  {allTrades.map((t, i) => (
                    <tr key={i}>
                      <td><span className="sw-badge" style={{ borderColor: t.stratColor, color: t.stratColor }}>
                        {t.stratEmoji} {data.strategies.find(s => s.code === t.stratCode)?.name}
                      </span></td>
                      <td className="mono">{t.date}</td>
                      <td className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>{t.ticker}</td>
                      <td className="sw-trades__sector">{t.sector}</td>
                      <td>
                        <span style={{ color: t.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700, fontSize: '0.75rem' }}>
                          {t.side === 'LONG' ? <TrendingUp size={12} style={{ display: 'inline', marginRight: 2 }} /> : <TrendingDown size={12} style={{ display: 'inline', marginRight: 2 }} />}
                          {t.side}
                        </span>
                      </td>
                      <td className="mono" style={{ color: t.return_pct >= 0 ? '#4ade80' : '#f87171' }}>
                        {t.return_pct >= 0 ? '+' : ''}{t.return_pct.toFixed(2)}%
                      </td>
                      <td>
                        <span className={`sw-verdict sw-verdict--${t.win ? 'hit' : 'miss'}`}>
                          {t.win ? '✓ WIN' : '✗ LOSS'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        </>
      )}
    </div>
  )
}
