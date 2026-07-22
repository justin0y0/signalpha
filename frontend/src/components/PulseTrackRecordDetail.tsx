import { useEffect, useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react'
import { useT } from '../i18n'

interface Trade {
  id: number; ticker: string; side: string; score: number; strategy: string
  entry_price: number; entry_time: string; tp_price: number; sl_price: number
  expected_exit_time: string; exit_price: number | null; exit_time: string | null
  exit_reason: string | null; return_pct: number | null; pnl_dollars: number | null
  win: boolean | null; status: string; hours_held: number
}
interface Cohort { n: number; wins: number; losses: number; pnl: number; avg_ret?: number }
interface Detail {
  total_signals: number; closed: number; open: number
  all_trades: Trade[]
  by_side: (Cohort & { side: string })[]
  by_session: (Cohort & { session: string })[]
  by_strategy: (Cohort & { strategy: string })[]
}

export function PulseTrackRecordDetail() {
  const { t } = useT()
  const [d, setD] = useState<Detail | null>(null)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<'all'|'open'|'closed'>('all')
  const [tab, setTab] = useState<'trades'|'cohorts'>('trades')
  useEffect(() => {
    const f = () => fetch('/api/v1/pulse/track-record')
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (j && typeof j.total_signals === 'number') setD(j) }).catch(() => {})
    f(); const i = setInterval(f, 60000); return () => clearInterval(i)
  }, [])
  const trades = useMemo(() =>
    !d ? [] : d.all_trades.filter(t => filter==='all' || (filter==='open' && t.status==='open') || (filter==='closed' && t.status==='closed')),
    [d, filter])
  if (!d || d.total_signals === 0) return null
  const worst = (cohorts: any[], key: string) => {
    if (!cohorts || cohorts.length === 0) return null
    const w = [...cohorts].sort((a,b) => (a.pnl||0) - (b.pnl||0))[0]
    return w
  }
  return (
    <div className="ptrd">
      <button className="ptrd__toggle" onClick={() => setOpen(!open)}>
        <span><AlertCircle size={13} /> TRACK RECORD DETAIL · {d.closed} closed · {d.open} open</span>
        {open ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}
      </button>
      <AnimatePresence>
      {open && (
        <motion.div className="ptrd__body" initial={{height:0, opacity:0}} animate={{height:'auto', opacity:1}} exit={{height:0, opacity:0}}>
          <div className="ptrd__tabs">
            <button className={tab==='trades'?'on':''} onClick={()=>setTab('trades')}>{t('ptr.allTrades')}</button>
            <button className={tab==='cohorts'?'on':''} onClick={()=>setTab('cohorts')}>{t('ptr.lossAnalysis')}</button>
          </div>
          {tab==='trades' && (
            <>
              <div className="ptrd__filter">
                <button className={filter==='all'?'on':''} onClick={()=>setFilter('all')}>All ({d.all_trades.length})</button>
                <button className={filter==='open'?'on':''} onClick={()=>setFilter('open')}>Open ({d.open})</button>
                <button className={filter==='closed'?'on':''} onClick={()=>setFilter('closed')}>Closed ({d.closed})</button>
              </div>
              <div className="ptrd__tbl-wrap">
                <table className="ptrd__tbl"><thead><tr>
                  <th>{t('col.ticker')}</th><th>{t('col.side')}</th><th>{t('col.strategy')}</th><th>{t('col.entry')}</th><th>{t('col.exit')}</th><th>{t('col.hold')}</th><th>{t('col.return')}</th><th>P&L</th><th>{t('col.status')}</th>
                </tr></thead><tbody>
                {trades.slice(0, 100).map(t => (
                  <tr key={t.id}>
                    <td><b>{t.ticker}</b></td>
                    <td className={t.side==='LONG'?'pos':'neg'}>{t.side==='LONG'?'↑':'↓'} {t.side}</td>
                    <td className="ptrd__small">{(t.strategy||'').replace(/_/g,' ')}</td>
                    <td>${Number(t.entry_price).toFixed(2)}<div className="ptrd__small">{new Date(t.entry_time).toLocaleString('en-US',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</div></td>
                    <td>{t.exit_price ? <>${Number(t.exit_price).toFixed(2)}<div className="ptrd__small">{new Date(t.exit_time!).toLocaleString('en-US',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</div></> : <span className="ptrd__small">—</span>}</td>
                    <td>{Number(t.hours_held).toFixed(1)}h</td>
                    <td className={(t.return_pct||0)>=0?'pos':'neg'}>{t.return_pct!=null ? `${(t.return_pct*100).toFixed(2)}%` : '—'}</td>
                    <td className={(t.pnl_dollars||0)>=0?'pos':'neg'}>{t.pnl_dollars!=null ? `$${Math.round(t.pnl_dollars).toLocaleString()}` : '—'}</td>
                    <td><span className={`ptrd__stat-${t.status}`}>{t.status}{t.win===true?' ✓':t.win===false?' ✗':''}</span></td>
                  </tr>
                ))}
                </tbody></table>
              </div>
            </>
          )}
          {tab==='cohorts' && (
            <div className="ptrd__cohorts">
              <CohortCard title="BY SIDE" rows={d.by_side} keyField="side" />
              <CohortCard title="BY SESSION" rows={d.by_session} keyField="session" />
              <CohortCard title="BY STRATEGY" rows={d.by_strategy} keyField="strategy" />
              <div className="ptrd__insight">
                <b>💡 Where losses concentrate:</b>
                {' '}{worst(d.by_side, 'side') && <> Side: <b>{worst(d.by_side,'side').side}</b> ({worst(d.by_side,'side').losses}L · ${Math.round(worst(d.by_side,'side').pnl).toLocaleString()})</>}
                {' · '}{worst(d.by_session, 'session') && <> Session: <b>{worst(d.by_session,'session').session}</b> (${Math.round(worst(d.by_session,'session').pnl).toLocaleString()})</>}
              </div>
            </div>
          )}
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  )
}

function CohortCard({ title, rows, keyField }: { title: string; rows: any[]; keyField: string }) {
  return (
    <div className="ptrd__cohort">
      <div className="ptrd__cohort-h">{title}</div>
      <table className="ptrd__cohort-tbl"><thead><tr>
        <th>{keyField}</th><th>n</th><th>W/L</th><th>WR</th><th>P&L</th>
      </tr></thead><tbody>
      {(rows||[]).map((r:any, i:number) => {
        const wr = r.n > 0 ? (r.wins / r.n * 100) : 0
        return <tr key={i}>
          <td><b>{r[keyField]}</b></td>
          <td>{r.n}</td>
          <td>{r.wins}/{r.losses}</td>
          <td className={wr>=50?'pos':'neg'}>{wr.toFixed(0)}%</td>
          <td className={r.pnl>=0?'pos':'neg'}>${Math.round(r.pnl).toLocaleString()}</td>
        </tr>
      })}
      </tbody></table>
    </div>
  )
}
