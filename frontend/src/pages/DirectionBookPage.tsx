import { Link } from 'react-router-dom'
import { Num } from '../components/ui/Num'
import { useDirection } from '../hooks/useDirection'
import { useT } from '../i18n'
import './DirectionBookPage.css'

/**
 * The direction book — four calls made at the open of a report's reaction session.
 *
 * Each rule card leads with what it would have done: hit rate, return per trade beside
 * the market's over the same windows, years in profit, and the cumulative P&L of $10k
 * in every call drawn against the market. Below, the live book: every call since the
 * rule went live, marked to the latest bar. All of it comes from /api/v1/direction.
 */

type Stats = { n: number; mean: number | null; hit: number | null; t: number | null }
type Rule = {
  side: 'LONG' | 'SHORT'; entry: 'open' | 'close'; hold: number; tiers: string[]; live_from: string
  all: Stats; excess: Stats; discovery: Stats; holdout: Stats; years_positive: number; years_total: number
  per_year: number; pnl: number; pnl_market: number; curve: { d: string; v: number; m: number }[]; span: string[]
}
type Call = {
  rule: string; ticker: string; company: string | null; side: string; entry: string; hold: number; session: string
  earnings_date: string; gap: number | null; gap_x: number | null; surprise: number | null; tier: string | null
  origin: string; status: 'pending' | 'open' | 'closed'; entry_price?: number; mark?: number; mark_on?: string
  sessions?: number; ret?: number; spy_ret?: number | null; excess?: number | null; pnl?: number
}
export type Book = {
  stake: number; rules: Record<string, Rule>
  book: { calls: Call[]; summary: { n: number; right: number; hit: number | null; pnl: number; spy_pnl: number; open: number; open_pnl: number; open_right: number
    by_rule: Record<string, { n: number; right: number; mean: number | null; pnl: number }> } }
}

const ORDER = ['fade_spike', 'buy_flush', 'fade_miss', 'follow_gap'] as const
const pc = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const sg = (v: number | null | undefined, d = 2) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`)
const usd = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(Math.round(v)).toLocaleString()}`)
const big = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1000)}k`)

function Curve({ pts }: { pts: Rule['curve'] }) {
  if (pts.length < 2) return null
  const w = 300, h = 74
  const hi = Math.max(...pts.map((p) => Math.max(p.v, p.m)), 1), lo = Math.min(...pts.map((p) => Math.min(p.v, p.m)), 0)
  const y = (v: number) => h - ((v - lo) / (hi - lo || 1)) * h
  const line = (k: 'v' | 'm') => pts.map((p, i) => `${(i / (pts.length - 1)) * w},${y(p[k]).toFixed(1)}`).join(' ')
  return (
    <svg className="db-curve" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2={w} y1={y(0)} y2={y(0)} className="db-curve__zero" />
      <polyline points={line('m')} className="db-curve__mkt" />
      <polyline points={`0,${y(0)} ${line('v')} ${w},${y(0)}`} className="db-curve__area" />
      <polyline points={line('v')} className="db-curve__line" pathLength={1} />
    </svg>
  )
}

export function DirectionBookPage() {
  const { t } = useT()
  const { data: d, error: err } = useDirection<Book>()
  if (err) return <div className="empty-state"><p>{t('db.error')}</p></div>
  if (!d) return <div className="shimmer" style={{ height: 640 }} />

  const rules = ORDER.map((k) => [k, d.rules[k]] as const).filter(([, r]) => r)
  const trades = rules.reduce((n, [, r]) => n + r.all.n, 0)
  const pnl = rules.reduce((n, [, r]) => n + r.pnl, 0)
  const mkt = rules.reduce((n, [, r]) => n + r.pnl_market, 0)
  const s = d.book.summary
  const live = d.book.calls

  return (
    <div className="db">
      <section className="db-claim">
        <p className="serif">
          {t('db.claim.a', { stake: d.stake.toLocaleString() })} <b>{big(pnl)}</b> {t('db.claim.b', { n: trades.toLocaleString() })}{' '}
          <span>{t('db.claim.c', { mkt: big(mkt) })}</span>
        </p>
        <p className="page-note">{t('db.claim.note')}</p>
      </section>

      <div className="db-rules">
        {rules.map(([k, r], i) => {
          const lr = s.by_rule[k]
          return (
            <article key={k} className={`db-rule is-${r.side.toLowerCase()}`} style={{ animationDelay: `${i * 0.08}s` }}>
              <header>
                <span className={`db-side is-${r.side.toLowerCase()}`}>{r.side === 'LONG' ? t('db.long') : t('db.short')}</span>
                <span className="db-hold">{t(`db.hold.${k}` as 'db.hold.fade_spike')}</span>
              </header>
              <h3 className="serif">{t(`db.rule.${k}` as 'db.rule.fade_spike')}</h3>
              <p className="db-when">{t(`db.when.${k}` as 'db.when.fade_spike')}</p>
              <div className="db-num">
                <b className="serif"><Num value={r.all.hit != null ? r.all.hit * 100 : null} format={(v) => `${v.toFixed(1)}%`} /></b>
                <span>{t('db.right')}</span>
              </div>
              <dl className="db-facts">
                <div><dt>{t('db.perTrade')}</dt><dd className="is-up">{sg(r.all.mean)}</dd></div>
                <div><dt>{t('db.vsMarket')}</dt><dd>{sg(r.excess.mean)}</dd></div>
                <div><dt>{t('db.years')}</dt><dd>{r.years_positive}/{r.years_total}</dd></div>
                <div><dt>{t('db.trades')}</dt><dd>{r.all.n.toLocaleString()}</dd></div>
              </dl>
              <Curve pts={r.curve} />
              <div className="db-curvecap"><span><i className="is-v" />{t('db.curve.rule', { pnl: big(r.pnl) })}</span><span><i className="is-m" />{t('db.curve.mkt', { pnl: big(r.pnl_market) })}</span></div>
              <footer>
                <span>{t('db.holdout', { hit: pc(r.holdout.hit), ex: sg(r.holdout.mean), t: r.holdout.t?.toFixed(1) ?? '—' })}</span>
                <span>{t('db.tiers', { tiers: r.tiers.map((x) => t(`tier.${x}` as 'tier.large')).join(' · ') })}</span>
                <span>{lr && lr.n ? t('db.liveRec', { right: lr.right, n: lr.n, pnl: usd(lr.pnl) }) : t('db.liveFrom', { d: r.live_from })}</span>
              </footer>
            </article>
          )
        })}
      </div>

      <section className="db-live">
        <header className="rc-block__head">
          <h2 className="serif">{t('db.live.title')}</h2>
          <p>{s.n
            ? t('db.live.sum', { right: s.right, n: s.n, hit: pc(s.hit, 0), pnl: usd(s.pnl), spy: usd(s.spy_pnl), open: s.open })
            : t('db.live.none', { open: s.open })}</p>
        </header>
        {live.length === 0 ? <p className="rc-empty serif">{t('db.live.empty')}</p> : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr>
                <th>{t('db.col.session')}</th><th>{t('col.ticker')}</th><th>{t('db.col.rule')}</th><th className="r">{t('db.col.gap')}</th>
                <th className="r">{t('db.col.entry')}</th><th className="r">{t('db.col.ret')}</th><th className="r">{t('db.col.pnl')}</th><th>{t('db.col.status')}</th>
              </tr></thead>
              <tbody>
                {live.map((c) => (
                  <tr key={c.rule + c.ticker + c.earnings_date}>
                    <td className="mono">{c.session.slice(5)}</td>
                    <td><Link to={`/predict/${c.ticker}?earnings_date=${c.earnings_date}`} className="mono rc-tk">{c.ticker}</Link></td>
                    <td><span className={`db-side is-${c.side.toLowerCase()}`}>{c.side === 'LONG' ? t('db.long') : t('db.short')}</span> {t(`db.rule.${c.rule}` as 'db.rule.fade_spike')}</td>
                    <td className="r mono">{c.gap_x != null ? `${c.gap_x > 0 ? '+' : ''}${c.gap_x.toFixed(1)}×` : '—'}</td>
                    <td className="r mono">{c.entry_price != null ? `$${c.entry_price.toFixed(2)}` : '—'}</td>
                    <td className={`r mono ${(c.ret ?? 0) >= 0 ? 'is-up' : 'is-down'}`}>{sg(c.ret)}</td>
                    <td className="r mono">{usd(c.pnl)}</td>
                    <td><span className={`rc-chip ${c.status === 'closed' ? ((c.ret ?? 0) > 0 ? 'is-right' : 'is-wrong') : ''}`}>
                      {c.status === 'closed' ? ((c.ret ?? 0) > 0 ? t('rc.right') : t('rc.wrong')) : c.status === 'pending' ? t('db.pending') : t('db.open', { n: c.sessions ?? 0, h: c.hold + (c.entry === 'open' ? 1 : 0) })}
                    </span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="db-how">
        <h3 className="serif">{t('db.how.title')}</h3>
        <p>{t('db.how.body')}</p>
      </section>
    </div>
  )
}
