import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { parseLocalDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * Today — one session on one sheet: how the market traded, which reports are out before
 * the next open, which reacted and how hard, which triggered a call, how the open calls
 * stand. Every sentence in the lead is assembled from the numbers in the tables below it.
 */

type Quote = { symbol: string; name: string; last: number; chg: number; as_of: string; spark: number[] }
type Rep = { ticker: string; company: string | null; when: 'bmo' | 'amc' | 'day' | 'next_bmo'; cap_tier: string
  prob_move: number | null; move_tier: string | null; implied: number | null; band: number | null }
type Rx = { ticker: string; company: string | null; move: number | null; band: number | null; x_band: number | null
  moved: boolean | null; flagged: boolean; triggered: boolean; cap_tier: string
  calls?: { rule: string; side: string; ret: number | null; status: string }[] }
type DCall = { rule: string; ticker: string; company: string | null; side: string; gap_x: number | null; status: string; ret?: number; pnl?: number; entry: string }
type Setup = { ticker: string; company: string | null; when: string; last: number; band: number; prob_move: number | null; move_tier: string | null
  levels: { rule: string; side: string; above?: number; below?: number; needs_miss?: boolean }[] }
type Open = { ticker: string; called_on: string; sessions: number; hold: number; ret: number; excess: number | null }
type Today = {
  direction: { latest_session: string | null; calls: DCall[]
    live: { n: number; right: number; hit: number | null; pnl: number; spy_pnl: number; open: number; open_pnl: number }
    record: { trades: number; pnl: number; market: number; best: { rule: string; years: string; hit: number } } }
  setups: Setup[]
  session: string; next_session: string; reactions_on: string | null; as_of: string
  summary: { spy_chg: number | null; leader: Quote | null; laggard: Quote | null; reacted: number; moved: number
    flagged: number; flagged_moved: number; triggered: string[]; reporting: number; reporting_flagged: string[]
    open_calls: number; open_mean: number | null }
  market: { indices: Quote[]; sectors: Quote[] }
  reporting: Rep[]; reporting_total: number; reacted: Rx[]; reacted_total: number; open_calls: Open[]
}

const sgn = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`)
const pm = (v: number | null | undefined) => (v == null ? '—' : `±${(v * 100).toFixed(1)}%`)
const big = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1000)}k`)
const usd = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(Math.round(v)).toLocaleString()}`)
const longDay = (iso: string) => parseLocalDate(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

function Spark({ v }: { v: number[] }) {
  if (v.length < 2) return null
  const lo = Math.min(...v), hi = Math.max(...v), w = 64, h = 18
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * w},${h - ((x - lo) / (hi - lo || 1)) * h}`).join(' ')
  return <svg className="tape-spark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} /></svg>
}

export function TodaySheet() {
  const { t } = useT()
  const [d, setD] = useState<Today | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    fetch('/api/v1/today').then((r) => (r.ok ? r.json() : Promise.reject())).then(setD).catch(() => setErr(true))
  }, [])
  if (err) return <div className="empty-state"><p>{t('today.error')}</p></div>
  if (!d) return <div className="shimmer" style={{ height: 620 }} />

  const s = d.summary
  const spy = s.spy_chg
  const maxSec = Math.max(0.005, ...d.market.sectors.map((x) => Math.abs(x.chg)))
  const groups: { key: Rep['when']; label: string }[] = [
    { key: 'bmo', label: t('today.out.bmo') }, { key: 'day', label: t('today.out.day') },
    { key: 'amc', label: t('today.out.amc') }, { key: 'next_bmo', label: t('today.out.next') },
  ]

  return (
    <article className="sheet paper today">
      <header className="sheet__mast">
        <div>
          <span className="sheet__kicker">{t('today.kicker')}</span>
          <h2>{t('today.title')}</h2>
        </div>
        <div className="sheet__meta">
          <span>{longDay(d.session)}</span>
          <span>{t('today.asOf', { time: new Date(d.as_of).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) })}</span>
        </div>
      </header>

      <p className="today__lead serif">
        {spy != null && t(spy >= 0 ? 'today.lead.up' : 'today.lead.down', { v: Math.abs(spy * 100).toFixed(2) })}{' '}
        {s.leader && s.laggard && t('today.lead.sectors', { lead: s.leader.name, lag: s.laggard.name })}{' '}
        {s.reacted > 0 && t('today.lead.reacted', { n: s.reacted, moved: s.moved })}{' '}
        {s.flagged > 0 && t('today.lead.flagged', { fm: s.flagged_moved, f: s.flagged })}{' '}
        {s.triggered.length > 0
          ? t('today.lead.calls', { list: s.triggered.slice(0, 5).join(', ') })
          : s.reacted > 0 ? t('today.lead.nocall') : ''}{' '}
        {t('today.lead.next', { n: s.reporting })}
        {s.reporting_flagged.length > 0 && <> {t('today.lead.watch', { list: s.reporting_flagged.join(', ') })}</>}
      </p>

      <Link to="/strategy" className="today__record">
        <span className="today__record-k">{t('today.rec.k')}</span>
        <b className="serif">{t('today.rec.a')} <em>{big(d.direction.record.pnl)}</em></b>
        <span>{t('today.rec.b', { n: d.direction.record.trades.toLocaleString(), mkt: big(d.direction.record.market), best: t(`db.rule.${d.direction.record.best.rule}` as 'db.rule.fade_spike'), years: d.direction.record.best.years })}</span>
      </Link>

      <section className="sheet__sec">
        <h3><i>1</i>{t('today.sec.calls', { d: d.direction.latest_session ? longDay(d.direction.latest_session) : '—' })}</h3>
        {d.direction.calls.length === 0 ? <p className="sheet__none">{t('today.calls.none')}</p> : (
          <div className="today__calls">
            {d.direction.calls.map((c) => (
              <Link key={c.rule + c.ticker} to={`/predict/${c.ticker}`} className={`today__call is-${c.side.toLowerCase()}`}>
                <span className="today__call-side">{c.side === 'LONG' ? t('db.long') : t('db.short')}</span>
                <b>{c.ticker}</b>
                <span className="today__call-rule">{t(`db.rule.${c.rule}` as 'db.rule.fade_spike')}{c.gap_x != null ? ` · ${c.gap_x > 0 ? '+' : ''}${c.gap_x.toFixed(1)}×` : ''}</span>
                <em className={(c.ret ?? 0) >= 0 ? 'is-up' : 'is-dn'}>{c.ret != null ? sgn(c.ret, 2) : t('db.pending')}</em>
              </Link>
            ))}
          </div>
        )}
        <p className="sheet__note">
          {d.direction.live.n
            ? t('today.calls.live', { right: d.direction.live.right, n: d.direction.live.n, pnl: usd(d.direction.live.pnl), spy: usd(d.direction.live.spy_pnl) })
            : t('today.calls.liveNone', { open: d.direction.live.open })}{' '}
          <Link to="/strategy">{t('today.calls.book')} →</Link>
        </p>
      </section>

      <section className="sheet__sec">
        <h3><i>2</i>{t('today.sec.setups')}</h3>
        {d.setups.length === 0 ? <p className="sheet__none">{t('today.setups.none')}</p> : (
          <div className="sheet__scroll">
            <table className="sheet__table today__setups">
              <thead><tr><th>{t('col.ticker')}</th><th className="r">{t('today.col.last')}</th><th className="r">{t('brief.col.usual')}</th><th>{t('today.col.levels')}</th></tr></thead>
              <tbody>
                {d.setups.map((x) => (
                  <tr key={x.ticker}>
                    <td><Link to={`/predict/${x.ticker}`}><b>{x.ticker}</b> <span className="sheet__co">{x.when === 'amc' ? t('today.setup.tonight') : t('today.setup.preopen')}{x.move_tier === 'breakout' ? ` · ${t('move.breakout')}` : ''}</span></Link></td>
                    <td className="r">${x.last.toFixed(2)}</td>
                    <td className="r">{pm(x.band)}</td>
                    <td className="today__levels">
                      {x.levels.map((l) => (
                        <span key={l.rule} className={`today__lvl is-${l.side.toLowerCase()}`}>
                          {t(`today.lvl.${l.rule}` as 'today.lvl.fade_spike', { p: (l.above ?? l.below ?? 0).toFixed(2) })}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="sheet__note">{t('today.setups.note')}</p>
      </section>

      <section className="sheet__sec">
        <h3><i>3</i>{t('today.sec.market')}</h3>
        <div className="tape-idx">
          {d.market.indices.map((q) => (
            <div key={q.symbol}>
              <span>{q.name}</span>
              <b className="mono">{q.symbol === '^TNX' ? `${(q.last / (q.last > 20 ? 10 : 1)).toFixed(2)}%` : q.last.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
              <em className={q.chg >= 0 ? 'is-up' : 'is-dn'}>{sgn(q.chg, 2)}</em>
              <Spark v={q.spark} />
            </div>
          ))}
        </div>
        <div className="tape-sec">
          {d.market.sectors.map((q) => (
            <div key={q.symbol}>
              <span>{q.name}</span>
              <div className="tape-sec__bar">
                <i className={q.chg >= 0 ? 'is-up' : 'is-dn'} style={{ width: `${(Math.abs(q.chg) / maxSec) * 50}%`, [q.chg >= 0 ? 'left' : 'right']: '50%' }} />
              </div>
              <em className={q.chg >= 0 ? 'is-up' : 'is-dn'}>{sgn(q.chg, 2)}</em>
            </div>
          ))}
        </div>
      </section>

      <section className="sheet__sec">
        <h3><i>4</i>{t('today.sec.reacted', { d: d.reactions_on ? longDay(d.reactions_on) : '—' })}</h3>
        {d.reacted.length === 0 ? <p className="sheet__none">{t('today.reacted.none')}</p> : (
          <div className="sheet__scroll">
            <table className="sheet__table">
              <thead><tr><th>{t('col.ticker')}</th><th className="r">{t('today.col.move')}</th><th className="r">{t('brief.col.usual')}</th>
                <th className="r">{t('today.col.x')}</th><th>{t('today.col.flag')}</th><th>{t('today.col.ours')}</th></tr></thead>
              <tbody>
                {d.reacted.slice(0, 40).map((r) => (
                  <tr key={r.ticker}>
                    <td><Link to={`/predict/${r.ticker}`}><b>{r.ticker}</b> <span className="sheet__co">{r.company}</span></Link></td>
                    <td className={`r ${(r.move ?? 0) >= 0 ? 'is-up' : 'is-dn'}`}>{sgn(r.move)}</td>
                    <td className="r">{pm(r.band)}</td>
                    <td className="r">{r.x_band != null ? `${r.x_band.toFixed(1)}×` : '—'}</td>
                    <td>{r.flagged ? <span className={`today__mark ${r.moved ? 'is-hit' : 'is-miss'}`}>{r.moved ? t('today.flag.hit') : t('today.flag.miss')}</span> : ''}</td>
                    <td>{(r.calls ?? []).map((c) => (
                      <span key={c.rule} className={`today__mark ${c.ret == null ? '' : c.ret > 0 ? 'is-call' : 'is-miss'}`}>
                        {c.side === 'LONG' ? '↑' : '↓'} {t(`db.rule.${c.rule}` as 'db.rule.fade_spike')}{c.ret != null ? ` ${sgn(c.ret)}` : ''}
                      </span>
                    ))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d.reacted_total > 40 && <p className="sheet__note">{t('today.more', { n: d.reacted_total - 40 })}</p>}
      </section>

      <section className="sheet__sec">
        <h3><i>5</i>{t('today.sec.out', { n: d.reporting_total })}</h3>
        {d.reporting.length === 0 ? <p className="sheet__none">{t('today.out.none')}</p> : groups.map((g) => {
          const rows = d.reporting.filter((r) => r.when === g.key)
          if (!rows.length) return null
          return (
            <div key={g.key} className="today__grp">
              <h4>{g.label} <span>{rows.length}</span></h4>
              <div className="today__chips">
                {rows.slice(0, 36).map((r) => (
                  <Link key={r.ticker} to={`/predict/${r.ticker}`} className={`today__chip is-${r.move_tier ?? 'none'}`}
                    title={`${r.company ?? ''} · ${t('brief.col.usual')} ${pm(r.band)} · ${t('brief.col.implied')} ${pm(r.implied)}`}>
                    <b>{r.ticker}</b>{r.prob_move != null && <span>{(r.prob_move * 100).toFixed(0)}%</span>}
                  </Link>
                ))}
                {rows.length > 36 && <span className="today__more">+{rows.length - 36}</span>}
              </div>
            </div>
          )
        })}
        <p className="sheet__note">{t('today.out.note')}</p>
      </section>

      <section className="sheet__sec">
        <h3><i>6</i>{t('today.sec.open', { n: d.open_calls.length })}</h3>
        {d.open_calls.length === 0 ? <p className="sheet__none">{t('rc.open.none')}</p> : (
          <div className="today__open">
            {d.open_calls.map((c) => (
              <div key={c.ticker + c.called_on}>
                <b>{c.ticker}</b>
                <span>{t('rc.sessions', { n: c.sessions, hold: c.hold })}</span>
                <em className={c.ret >= 0 ? 'is-up' : 'is-dn'}>{sgn(c.ret)}</em>
              </div>
            ))}
          </div>
        )}
        <p className="sheet__note"><Link to="/model">{t('today.receipts')} →</Link></p>
      </section>
    </article>
  )
}
