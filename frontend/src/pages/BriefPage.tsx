import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHead } from '../components/PageHead'
import { LeanChip } from '../components/ui/LeanChip'
import { Num } from '../components/ui/Num'
import { parseLocalDate } from '../utils/date'
import { pct } from '../hooks/useHeadline'
import { useT } from '../i18n'
import './BriefPage.css'

/**
 * 02 · Brief — this week on one sheet of paper.
 *
 * The same reports as the calendar, edited down to what a person would actually read
 * before the open: what is flagged, what just reacted, and the rest in small type.
 * It is set as a printed note — cream stock, dark ink — because a brief is the one
 * thing here that is finished and handed over, not a live instrument.
 */

type Row = {
  ticker: string; company_name: string | null; sector: string | null
  earnings_date: string; report_time: string | null
  prob_move: number | null; move_tier: 'breakout' | 'elevated' | 'normal' | null
  own_band: number | null; implied_move_pct: number | null; lean_up?: number | null
}
type Metrics = { auc: number; base_rate: number; n: number; top_decile: { n: number; move_rate: number; z: number } } | null
type Brief = {
  as_of: string; horizon_days: number; personalised: boolean; watchlist_size: number
  counts: { total: number; breakout: number; elevated: number; normal: number; unscored: number }
  breakout: Row[]; elevated: Row[]; normal: Row[]; metrics: Metrics
}
type Reacted = { ticker: string; reaction_date: string; gap: number | null; gap_x: number | null; surprise: number | null; signal: string }

const day = (iso: string) => parseLocalDate(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
const pm = (v: number | null) => (v == null ? '—' : `±${(v * 100).toFixed(1)}%`)

function Flagged({ r, base }: { r: Row; base?: number }) {
  const { t } = useT()
  const ratio = r.implied_move_pct != null && r.own_band ? r.implied_move_pct / r.own_band : null
  return (
    <Link to={`/predict/${r.ticker}?earnings_date=${r.earnings_date}`} className={`sheet-flag is-${r.move_tier}`}>
      <div className="sheet-flag__top">
        <b>{r.ticker}</b>
        <span>{day(r.earnings_date)}{r.report_time ? ` · ${r.report_time}` : ''}</span>
      </div>
      <div className="sheet-flag__co">{r.company_name}</div>
      <div className="sheet-flag__num">
        <strong>{r.prob_move != null ? `${(r.prob_move * 100).toFixed(0)}%` : '—'}</strong>
        <span>{t('brief.flag.risk')}{base != null ? ` · ${t('dd.baseRate', { v: (base * 100).toFixed(0) })}` : ''}</span>
      </div>
      <dl>
        <div><dt>{t('brief.col.usual')}</dt><dd>{pm(r.own_band)}</dd></div>
        <div><dt>{t('brief.col.implied')}</dt><dd>{pm(r.implied_move_pct)}{ratio != null && <i> {ratio.toFixed(1)}×</i>}</dd></div>
        <div><dt>{t('brief.col.lean')}</dt><dd><LeanChip p={r.lean_up} /></dd></div>
      </dl>
      <span className="sheet-flag__stamp">{t(`move.${r.move_tier}` as 'move.breakout')}</span>
    </Link>
  )
}

export function BriefPage() {
  const { t } = useT()
  const [data, setData] = useState<Brief | null>(null)
  const [reacted, setReacted] = useState<Reacted[]>([])
  const [error, setError] = useState<string | null>(null)
  const email = (() => { try { return localStorage.getItem('sa_email') } catch { return null } })()

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ horizon_days: '7' })
      if (email) qs.set('email', email)
      const r = await fetch(`/api/v1/brief?${qs.toString()}`)
      if (!r.ok) throw new Error(await r.text())
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load brief')
    }
  }, [email])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    fetch('/api/v1/playbook/live?days=7').then((r) => (r.ok ? r.json() : null)).then((d) => setReacted(d?.reports ?? [])).catch(() => {})
  }, [])

  if (error) return <div className="empty-state">{error}</div>
  const m = data?.metrics
  const flagged = data ? [...data.breakout, ...data.elevated] : []

  return (
    <div className="brief">
      <PageHead
        kicker={t('nav.brief')}
        title={<>{t('brief.h.a')} <em>{t('brief.h.b')}</em></>}
        lede={t('brief.h.lede')}
        spike={0.5}
      >
        <div className="figs">
          <div><b><Num value={data?.counts.total} /></b><span>{t('brief.stat.ahead')}</span></div>
          <div className="is-signal"><b><Num value={data ? data.counts.breakout + data.counts.elevated : null} /></b><span>{t('brief.fig.flagged')}</span></div>
          <div className="is-up"><b><Num value={reacted.filter((r) => r.signal === 'long').length} /></b><span>{t('brief.fig.follow')}</span></div>
        </div>
      </PageHead>

      {!data ? <div className="shimmer" style={{ height: 520 }} /> : (
        <article className="sheet paper">
          <header className="sheet__mast">
            <div>
              <span className="sheet__kicker">{t('brief.sheet.kicker')}</span>
              <h2>{t('brief.sheet.title')}</h2>
            </div>
            <div className="sheet__meta">
              <span>{t('brief.sheet.asOf', { d: day(data.as_of) })}</span>
              <span>{t('brief.sheet.window', { days: data.horizon_days })}</span>
              <span>{data.personalised ? t('brief.personalised', { n: data.watchlist_size }) : t('brief.sheet.all')}</span>
            </div>
          </header>

          <section className="sheet__sec">
            <h3><i>A</i>{t('brief.sec.flagged')}</h3>
            {flagged.length === 0 ? (
              <p className="sheet__none">{t('brief.sec.flagged.none')}</p>
            ) : (
              <div className="sheet__flags">{flagged.map((r) => <Flagged key={r.ticker + r.earnings_date} r={r} base={m?.base_rate} />)}</div>
            )}
            {m && <p className="sheet__note">{t('brief.skill', { rate: pct(m.top_decile.move_rate), base: pct(m.base_rate), n: m.top_decile.n.toLocaleString() })}</p>}
          </section>

          <section className="sheet__sec">
            <h3><i>B</i>{t('brief.sec.reacted')}</h3>
            {reacted.length === 0 ? <p className="sheet__none">{t('pb.live.empty')}</p> : (
              <div className="sheet__scroll"><table className="sheet__table">
                <thead><tr><th>{t('col.ticker')}</th><th>{t('pb.col.reacted')}</th><th className="r">{t('pb.col.gap')}</th><th className="r">{t('pb.col.vsUsual')}</th><th className="r">{t('pb.col.eps')}</th><th>{t('pb.col.call')}</th></tr></thead>
                <tbody>
                  {reacted.map((r) => (
                    <tr key={r.ticker + r.reaction_date}>
                      <td><Link to={`/predict/${r.ticker}`}><b>{r.ticker}</b></Link></td>
                      <td>{day(r.reaction_date)}</td>
                      <td className={`r ${r.gap != null && r.gap >= 0 ? 'is-up' : 'is-dn'}`}>{r.gap != null ? `${r.gap >= 0 ? '+' : ''}${(r.gap * 100).toFixed(1)}%` : '—'}</td>
                      <td className="r">{r.gap_x != null ? `${Math.abs(r.gap_x).toFixed(1)}×` : '—'}</td>
                      <td className="r">{r.surprise != null ? `${r.surprise >= 0 ? '+' : ''}${r.surprise.toFixed(0)}%` : '—'}</td>
                      <td><span className={`sheet__call is-${r.signal}`}>{t(`pb.call.${r.signal}` as 'pb.call.long')}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
            <p className="sheet__note">{t('brief.sec.reacted.note')} <Link to="/strategy">{t('wire.play.go')} →</Link></p>
          </section>

          <section className="sheet__sec">
            <h3><i>C</i>{t('brief.sec.rest')}</h3>
            {data.normal.length === 0 ? <p className="sheet__none">{t('brief.empty')}</p> : (
              <div className="sheet__scroll"><table className="sheet__table">
                <thead><tr><th>{t('col.ticker')}</th><th>{t('col.company')}</th><th>{t('col.date')}</th><th className="r">{t('cal.col.moveRisk')}</th><th className="r">{t('brief.col.usual')}</th><th className="r">{t('brief.col.implied')}</th></tr></thead>
                <tbody>
                  {data.normal.map((r) => (
                    <tr key={r.ticker + r.earnings_date}>
                      <td><Link to={`/predict/${r.ticker}?earnings_date=${r.earnings_date}`}><b>{r.ticker}</b></Link></td>
                      <td className="sheet__co">{r.company_name}</td>
                      <td>{day(r.earnings_date)}{r.report_time ? ` · ${r.report_time}` : ''}</td>
                      <td className="r">{r.prob_move != null ? `${(r.prob_move * 100).toFixed(0)}%` : '—'}</td>
                      <td className="r">{pm(r.own_band)}</td>
                      <td className="r">{pm(r.implied_move_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
            <p className="sheet__note">{t('brief.normal.note')}</p>
          </section>

          <footer className="sheet__foot">
            <span>{t('brief.sheet.foot')}</span>
            <span className="sheet__sig">SignAlpha</span>
          </footer>
        </article>
      )}
    </div>
  )
}
