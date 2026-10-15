import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { BreakoutDial } from './BreakoutDial'
import { PriceTicker } from './ui/PriceTicker'
import { ReactionHistory } from './ReactionHistory'
import { formatDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * A ticker the site holds no history for — scored on the spot.
 *
 * /lookup pulls the report dates and bars, measures each past reaction on the right
 * session, takes the median as the usual move, and scores the next report with the live
 * breakout model. When the name sits below the training cut-off the page says so above
 * the dial, because a number there is an extrapolation.
 */
type Lookup = {
  ticker: string; company_name: string | null; sector: string | null; cap_tier: string; market_cap: number | null
  in_training: boolean; next_report: { date: string; report_time: string | null } | null
  band: number | null; n_reactions: number; reactions: { earnings_date: string; reaction_pct: number }[]
  prob_move: number | null; move_tier: 'breakout' | 'elevated' | 'normal' | null; base_rate: number | null
}

export function OnDemandDossier({ ticker }: { ticker: string }) {
  const { t } = useT()
  const [d, setD] = useState<Lookup | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setD(null); setErr(null)
    fetch(`/api/v1/lookup/${encodeURIComponent(ticker)}`)
      .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`); return r.json() })
      .then((x) => { if (alive) setD(x) })
      .catch((e: Error) => { if (alive) setErr(e.message) })
    return () => { alive = false }
  }, [ticker])

  if (err) {
    return (
      <div className="dossier">
        <Link to="/" className="dossier__back"><ArrowLeft size={13} /> {t('nav.calendar')}</Link>
        <div className="empty-state"><p>{t('dd.notFound', { ticker })}</p></div>
      </div>
    )
  }
  if (!d) {
    return (
      <div className="dossier">
        <div className="od-wait">
          <span className="pulse-status__live"><i />{t('od.computing', { ticker })}</span>
          <p className="page-note">{t('od.computing.d')}</p>
        </div>
        <div className="shimmer" style={{ height: 150 }} />
        <div className="shimmer" style={{ height: 320 }} />
      </div>
    )
  }

  const history = d.reactions.slice(-8).map((r) => ({ date: r.earnings_date.slice(2, 7), reaction: +(r.reaction_pct * 100).toFixed(2) }))
  return (
    <div className="dossier">
      <Link to="/" className="dossier__back"><ArrowLeft size={13} /> {t('nav.calendar')}</Link>
      <header className="dossier__head">
        <div>
          <div className="dossier__kicker">
            {d.sector && <span>{d.sector}</span>}
            <span className="od-tier">{t(`tier.${d.cap_tier}` as 'tier.large')}</span>
            {d.next_report && <span>{formatDate(d.next_report.date)}</span>}
            {d.next_report?.report_time && <span className={`when-chip when-chip--${d.next_report.report_time.toLowerCase()}`}>{t(`when.${d.next_report.report_time.toLowerCase()}` as 'when.bmo')}</span>}
          </div>
          <h1 className="ticker-symbol">{d.ticker}</h1>
          <p className="ticker-name">{d.company_name ?? '—'}</p>
        </div>
        <PriceTicker ticker={d.ticker} />
      </header>

      <p className={`od-note ${d.in_training ? '' : 'is-outside'}`}>
        {d.in_training ? t('od.note.building') : t('od.note.outside')}
      </p>

      <div className="dossier__calls">
        <section className="card dialcard">
          <h3 className="card-title">{t('dd.dial.title')}</h3>
          {d.prob_move != null
            ? <BreakoutDial prob={d.prob_move} tier={d.move_tier} base={d.base_rate} />
            : <p className="page-note">{d.next_report ? t('od.noScore') : t('od.noReport')}</p>}
          <dl className="dialcard__facts">
            <div><dt>{t('brief.col.usual')}</dt><dd>{d.band != null ? `±${(d.band * 100).toFixed(1)}%` : '—'}</dd></div>
            <div><dt>{t('od.reports')}</dt><dd>{d.n_reactions}</dd></div>
            <div><dt>{t('od.next')}</dt><dd>{d.next_report ? d.next_report.date.slice(5) : '—'}</dd></div>
          </dl>
        </section>
        <section className="card">
          <h3 className="card-title">{t('od.what.title')}</h3>
          <p className="page-note" style={{ fontSize: '0.86rem' }}>{t('od.what.body', { n: d.n_reactions })}</p>
        </section>
      </div>

      <ReactionHistory history={history} band={d.band} />
    </div>
  )
}
