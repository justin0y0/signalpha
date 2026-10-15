import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Num } from '../components/ui/Num'
import { useT } from '../i18n'
import './ReceiptsPage.css'

/**
 * Receipts — every call the site made before the outcome existed, marked to today.
 *
 * Two ledgers. Follow-through calls (the one direction call with evidence) are open
 * positions marked to the latest close: sessions elapsed out of the hold, return so far,
 * the S&P 500 over the same days, and what $10k in each would be worth. Pre-report calls
 * (breakout flag, direction lean) were frozen when the bell rang and graded on the
 * reaction. Small samples get intervals, not adjectives.
 */

type FT = {
  ticker: string; company: string | null; tier: string; earnings_date: string; called_on: string
  gap: number; band: number; gap_x: number; entry: number; mark: number; mark_on: string
  sessions: number; hold: number; status: 'open' | 'closed'; ret: number; spy_ret: number | null
  excess: number | null; pnl: number; spy_pnl: number | null
}
type Pre = {
  ticker: string; company_name: string | null; earnings_date: string; report_time: string | null
  prob_move: number | null; move_tier: string | null; band: number | null; lean_up: number | null
  lean: 'UP' | 'DOWN' | null; actual_move: number | null; moved: boolean | null; lean_hit: boolean | null
  graded_at: string | null; cap_tier: string | null
}
type R = {
  since: string; as_of: string
  follow: { calls: FT[]; summary: { n: number; open: number; closed: number; right: number; hit: number | null; hit_lo: number | null; hit_hi: number | null; mean: number | null; excess: number | null; pnl: number; spy_pnl: number; stake: number } }
  pre: { calls: Pre[]; summary: { frozen: number; graded: number; pending: number; flagged: number; flagged_moved: number; flagged_rate: number | null; flagged_lo: number | null; flagged_hi: number | null; all_moved_rate: number | null; lean_n: number; lean_right: number; lean_hit: number | null; lean_lo: number | null; lean_hi: number | null; late_frozen?: number } }
  expect: { follow: { hit: number; baseline_hit: number; n: number; hold: number; k: number } | null; breakout_top: number | null; breakout_base: number | null }
}

const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const sgn = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`)
const usd = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`)
const ci = (lo: number | null, hi: number | null) => (lo == null || hi == null ? '' : `${(lo * 100).toFixed(0)}–${(hi * 100).toFixed(0)}%`)

export function ReceiptsPage() {
  const { t } = useT()
  const [d, setD] = useState<R | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    fetch('/api/v1/receipts').then((r) => (r.ok ? r.json() : Promise.reject())).then(setD).catch(() => setErr(true))
  }, [])

  if (err) return <div className="empty-state"><p>{t('rc.error')}</p></div>
  if (!d) return <div className="page-stack"><div className="shimmer" style={{ height: 140 }} /><div className="shimmer" style={{ height: 360 }} /></div>

  const f = d.follow.summary
  const p = d.pre.summary
  const open = d.follow.calls.filter((c) => c.status === 'open')
  const closed = d.follow.calls.filter((c) => c.status === 'closed')
  const graded = d.pre.calls.filter((c) => c.graded_at)
  const pending = d.pre.calls.filter((c) => !c.graded_at)

  return (
    <div className="rc">
      <section className="rc-score">
        <div>
          <span className="eyebrow">{t('rc.score.ft')}</span>
          <b className="serif">{f.n ? <><Num value={f.right} />/{f.n}</> : '—'}</b>
          <span>{f.n ? t('rc.score.ft.d', { hit: pct(f.hit, 0), ci: ci(f.hit_lo, f.hit_hi), exp: pct(d.expect.follow?.hit, 0) }) : t('rc.score.none')}</span>
        </div>
        <div>
          <span className="eyebrow">{t('rc.score.pnl', { stake: f.stake.toLocaleString() })}</span>
          <b className={`serif ${f.pnl >= 0 ? 'is-up' : 'is-down'}`}>{f.n ? usd(f.pnl) : '—'}</b>
          <span>{f.n ? t('rc.score.pnl.d', { spy: usd(f.spy_pnl) }) : t('rc.score.none')}</span>
        </div>
        <div>
          <span className="eyebrow">{t('rc.score.flag')}</span>
          <b className="serif">{p.flagged ? `${p.flagged_moved}/${p.flagged}` : '—'}</b>
          <span>{p.flagged ? t('rc.score.flag.d', { rate: pct(p.flagged_rate, 0), ci: ci(p.flagged_lo, p.flagged_hi), all: pct(p.all_moved_rate, 0) }) : t('rc.score.waiting', { n: p.pending })}</span>
        </div>
        <div>
          <span className="eyebrow">{t('rc.score.lean')}</span>
          <b className="serif">{p.lean_n ? `${p.lean_right}/${p.lean_n}` : '—'}</b>
          <span>{p.lean_n ? t('rc.score.lean.d', { hit: pct(p.lean_hit, 0), ci: ci(p.lean_lo, p.lean_hi) }) : t('rc.score.waiting', { n: p.pending })}</span>
        </div>
      </section>
      <p className="page-note">{t('rc.since', { since: d.since })}</p>

      {/* ── follow-through, open ── */}
      <section className="rc-block">
        <header className="rc-block__head">
          <h2 className="serif">{t('rc.open.title')}</h2>
          <p>{t('rc.open.sub', { k: d.expect.follow?.k ?? 2, hold: d.expect.follow?.hold ?? 20 })}</p>
        </header>
        {open.length === 0 ? <p className="rc-empty serif">{t('rc.open.none')}</p> : (
          <div className="rc-open">
            {open.map((c) => (
              <Link key={c.ticker + c.called_on} to={`/predict/${c.ticker}?earnings_date=${c.earnings_date}`} className="rc-pos">
                <div className="rc-pos__id">
                  <b className="mono">{c.ticker}</b>
                  <span>{c.company}</span>
                </div>
                <div className="rc-pos__track" aria-label={t('rc.sessions', { n: c.sessions, hold: c.hold })}>
                  {Array.from({ length: c.hold }, (_, i) => <i key={i} style={{ ['--i' as string]: i }} className={i < c.sessions ? 'is-on' : ''} />)}
                </div>
                <div className="rc-pos__meta">
                  <span>{t('rc.called', { d: c.called_on.slice(5), x: c.gap_x.toFixed(1) })}</span>
                  <span>{t('rc.sessions', { n: c.sessions, hold: c.hold })}</span>
                </div>
                <div className="rc-pos__num">
                  <b className={`serif ${c.ret >= 0 ? 'is-up' : 'is-down'}`}>{sgn(c.ret)}</b>
                  <span>{t('rc.vsSpy', { v: sgn(c.excess) })} · {usd(c.pnl)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* ── follow-through, closed ── */}
      {closed.length > 0 && (
        <section className="rc-block">
          <header className="rc-block__head"><h2 className="serif">{t('rc.closed.title')}</h2></header>
          <div className="paper rc-closed">
            {closed.map((c) => (
              <div key={c.ticker + c.called_on} className="rc-closed__row">
                <b className="mono">{c.ticker}</b>
                <span>{c.called_on} → {c.mark_on}</span>
                <span className={c.ret >= 0 ? 'is-up' : 'is-down'}>{sgn(c.ret)}</span>
                <span>{t('rc.vsSpy', { v: sgn(c.excess) })}</span>
                <span>{usd(c.pnl)}</span>
                <span className={`rc-stamp ${c.ret > 0 ? 'is-right' : 'is-wrong'}`}>{c.ret > 0 ? t('rc.right') : t('rc.wrong')}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── pre-report calls ── */}
      <section className="rc-block">
        <header className="rc-block__head">
          <h2 className="serif">{t('rc.pre.title')}</h2>
          <p>{t('rc.pre.sub')}</p>
        </header>
        {pending.length > 0 && (
          <p className="rc-pending">
            <span className="eyebrow">{t('rc.pending', { n: pending.length })}</span>{' '}
            {pending.slice(0, 24).map((c) => c.ticker).join(' · ')}{pending.length > 24 ? ' …' : ''}
          </p>
        )}
        {graded.length === 0 ? <p className="rc-empty serif">{t('rc.pre.none')}</p> : (
          <div className="table-scroll">
            <table className="data-table rc-table">
              <thead><tr>
                <th>{t('rc.col.report')}</th><th>{t('col.ticker')}</th><th className="r">{t('rc.col.prob')}</th>
                <th className="r">{t('brief.col.usual')}</th><th className="r">{t('rc.col.actual')}</th><th>{t('rc.col.flag')}</th><th>{t('rc.col.lean')}</th>
              </tr></thead>
              <tbody>
                {graded.slice(0, 160).map((c) => (
                  <tr key={c.ticker + c.earnings_date}>
                    <td className="mono">{c.earnings_date.slice(5)}</td>
                    <td><Link to={`/predict/${c.ticker}?earnings_date=${c.earnings_date}`} className="mono rc-tk">{c.ticker}</Link></td>
                    <td className="r mono">
                      {pct(c.prob_move, 0)}
                      {c.move_tier === 'breakout' && <i className="rc-flag">{t('move.breakout')}</i>}
                    </td>
                    <td className="r mono">{c.band != null ? `±${(c.band * 100).toFixed(1)}%` : '—'}</td>
                    <td className={`r mono ${(c.actual_move ?? 0) >= 0 ? 'is-up' : 'is-down'}`}>{sgn(c.actual_move)}</td>
                    <td><span className={`rc-chip ${c.moved ? 'is-moved' : ''}`}>{c.moved ? t('rc.moved') : t('rc.held')}</span></td>
                    <td>{c.lean ? <span className={`rc-chip ${c.lean_hit ? 'is-right' : 'is-wrong'}`}>{c.lean === 'UP' ? '↑' : '↓'} {c.lean_hit ? t('rc.right') : t('rc.wrong')}</span> : <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(p.late_frozen ?? 0) > 0 && <p className="page-note">{t('rc.pre.late', { n: p.late_frozen ?? 0 })}</p>}
        <p className="page-note">{t('rc.pre.note', { top: pct(d.expect.breakout_top, 0), base: pct(d.expect.breakout_base, 0) })}</p>
      </section>
    </div>
  )
}
