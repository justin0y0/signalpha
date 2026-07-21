import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, TrendingUp, TrendingDown } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts'

interface TR {
  total_signals: number; closed: number; open: number
  total_pnl_dollars: number; avg_return_pct: number; win_rate: number
  wins: number; losses: number
  equity_curve: { date: string; cum_pnl: number }[]
  recent: any[]
}

export function PulseTrackRecord() {
  const [d, setD] = useState<TR | null>(null)
  useEffect(() => {
    const f = () => fetch('/api/v1/pulse/track-record')
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (j && typeof j.total_signals === 'number') setD(j) })
      .catch(() => {})
    f()
    const id = setInterval(f, 60000)
    return () => clearInterval(id)
  }, [])
  if (!d || typeof d.total_signals !== 'number' || d.total_signals === 0) return null
  const pos = d.total_pnl_dollars >= 0
  return (
    <motion.div className="ptr" initial={{opacity:0, y:-10}} animate={{opacity:1, y:0}}>
      <div className="ptr__head">
        <span className="ptr__title">
          <Activity size={13} /> LIVE TRACK RECORD
        </span>
        <span className="ptr__sub">since launch · {d.closed} closed / {d.open} open</span>
      </div>
      <div className="ptr__body">
        <div className="ptr__hero">
          <div className="ptr__pnl-label">CUMULATIVE P&L</div>
          <div className={`ptr__pnl-val ${pos ? 'pos' : 'neg'}`}>
            {pos ? '+' : '−'}${Math.abs(Math.round(d.total_pnl_dollars)).toLocaleString()}
          </div>
          <div className="ptr__pnl-sub">{d.total_signals} signals sent</div>
        </div>
        <div className="ptr__stats">
          <div className="ptr__stat">
            <span>WIN RATE</span>
            <b className={d.win_rate > 0.5 ? 'pos' : 'neg'}>{(d.win_rate * 100).toFixed(0)}%</b>
            <small>{d.wins}W / {d.losses}L</small>
          </div>
          <div className="ptr__stat">
            <span>AVG RETURN</span>
            <b className={d.avg_return_pct > 0 ? 'pos' : 'neg'}>{(d.avg_return_pct * 100).toFixed(2)}%</b>
            <small>per trade</small>
          </div>
          <div className="ptr__stat">
            <span>HIT RATIO</span>
            <b>{d.closed > 0 ? ((d.wins / d.closed) * 100).toFixed(0) : '—'}%</b>
            <small>of closed</small>
          </div>
        </div>
        {d.equity_curve.length > 1 && (
          <div className="ptr__chart">
            <ResponsiveContainer width="100%" height={75}>
              <LineChart data={d.equity_curve}>
                <Tooltip content={({active, payload}) => active && payload?.length ? (
                  <div className="mc-tt"><b>${Math.round(payload[0].value as number).toLocaleString()}</b></div>
                ) : null} />
                <Line type="monotone" dataKey="cum_pnl"
                  stroke={pos ? '#6FA287' : '#C4726A'} strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </motion.div>
  )
}
