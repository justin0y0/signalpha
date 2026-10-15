import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import type { PredictionResponse } from '../types'
import { PriceTicker } from '../components/ui/PriceTicker'
import { daysUntil, formatDate } from '../utils/date'
import { StraddleCheck } from '../components/StraddleCheck'
import { BreakoutDial } from '../components/BreakoutDial'
import { LeanCard } from '../components/LeanCard'
import { ArenaForReport } from '../components/ArenaForReport'
import { OnDemandDossier } from '../components/OnDemandDossier'
import { ReactionHistory } from '../components/ReactionHistory'
import { useT } from '../i18n'
import './DossierPage.css'

/**
 * The dossier — one report, everything the site knows about it.
 *
 * Where the loop meets a single stock: how likely this report is to move it more than
 * usual (the dial), which way the experimental scorecard leans and why (the rope),
 * whether options already price the move (straddle check), what the Arena sealed, and
 * what the stock did the last eight times.
 *
 * It used to lead with the three-class direction bars, a 20-day "convergence zone" and
 * SHAP drivers of the direction model. All three were views of a model that scores at
 * chance on clean data, so they are gone rather than restyled.
 */

const pctSigned = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`)

export function PredictionDeepDivePage() {
  const { t } = useT()
  const { ticker = '' } = useParams<{ ticker: string }>()
  const [search] = useSearchParams()
  const earningsDate = search.get('earnings_date') ?? undefined
  const [data, setData] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ticker) return
    let alive = true
    setData(null)
    api.getPrediction(ticker, earningsDate)
      .then((r) => { if (alive) { setData(r); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : 'failed') })
    return () => { alive = false }
  }, [ticker, earningsDate])

  const history = useMemo(() => {
    if (!data?.historical_reactions) return []
    return [...data.historical_reactions]
      .filter((r) => r.reaction_pct != null)
      .sort((a, b) => a.earnings_date.localeCompare(b.earnings_date))
      .slice(-8)
      .map((r) => ({ date: r.earnings_date.slice(2, 7), reaction: +((r.reaction_pct as number) * 100).toFixed(2) }))
  }, [data])

  if (error) {
    return <OnDemandDossier ticker={ticker.toUpperCase()} />
  }
  if (!data) {
    return (
      <div className="dossier">
        <div className="shimmer" style={{ height: 150 }} />
        <div className="grid grid-2"><div className="shimmer" style={{ height: 320 }} /><div className="shimmer" style={{ height: 320 }} /></div>
        <div className="shimmer" style={{ height: 300 }} />
      </div>
    )
  }

  const du = daysUntil(data.earnings_date)
  const when = du === 0 ? t('cal.today') : du === 1 ? t('cal.tomorrow') : du > 0 ? t('cal.inDays', { n: du }) : t('cal.daysAgo', { n: -du })
  const band = data.flat_band
  const implied = data.implied_move_pct
  const ratio = implied != null && band ? implied / band : null

  return (
    <div className="dossier">
      <Link to="/" className="dossier__back"><ArrowLeft size={13} /> {t('nav.calendar')}</Link>

      <header className="dossier__head">
        <div>
          <div className="dossier__kicker">
            {data.sector && <span>{data.sector}</span>}
            <span>{formatDate(data.earnings_date)}</span>
            {data.report_time && <span className={`when-chip when-chip--${data.report_time.toLowerCase()}`}>{t(`when.${data.report_time.toLowerCase()}` as 'when.bmo')}</span>}
            <span className="dossier__when">{when}</span>
          </div>
          <h1 className="ticker-symbol">{data.ticker}</h1>
          <p className="ticker-name">{data.company_name ?? '—'}</p>
        </div>
        <PriceTicker ticker={data.ticker} />
      </header>

      <div className="dossier__calls">
        <section className="card dialcard">
          <h3 className="card-title">{t('dd.dial.title')}</h3>
          <BreakoutDial prob={data.prob_move} tier={data.move_tier} base={data.breakout_base_rate} />
          <dl className="dialcard__facts">
            <div><dt>{t('brief.col.usual')}</dt><dd>{band != null ? `±${(band * 100).toFixed(1)}%` : '—'}</dd></div>
            <div><dt>{t('brief.col.implied')}</dt><dd>{implied != null ? `±${(implied * 100).toFixed(1)}%` : '—'}</dd></div>
            <div><dt>{t('dd.dial.ratio')}</dt><dd>{ratio != null ? `${ratio.toFixed(1)}×` : '—'}</dd></div>
          </dl>
          <p className="page-note">{t(`dd.dial.read.${data.move_tier ?? 'none'}` as 'dd.dial.read.normal')}</p>
        </section>

        <LeanCard p={data.lean_up} factors={data.lean_factors ?? []} metrics={data.lean_metrics} />
      </div>

      <StraddleCheck ticker={data.ticker} />

      <ArenaForReport ticker={data.ticker} date={data.earnings_date} />

      <ReactionHistory history={history} band={band} />

      {data.similar_cases.length > 0 && (
        <details className="dossier__more">
          <summary>{t('dd.similarNN')}</summary>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>{t('col.ticker')}</th><th>{t('col.date')}</th><th>{t('col.sector')}</th>
                <th className="r">{t('col.similarity')}</th><th className="r">T+1</th><th className="r">T+5</th><th className="r">T+20</th></tr></thead>
              <tbody>
                {data.similar_cases.slice(0, 8).map((c) => (
                  <tr key={`${c.ticker}-${c.earnings_date}`} style={{ cursor: 'default' }}>
                    <td className="mono" style={{ fontWeight: 700 }}>{c.ticker}</td>
                    <td className="mono">{c.earnings_date}</td>
                    <td className="muted">{c.sector ?? '—'}</td>
                    <td className="mono r">{(c.similarity * 100).toFixed(1)}%</td>
                    {[c.actual_t1_return, c.actual_t5_return, c.actual_t20_return].map((v, i) => (
                      <td key={i} className="mono r" style={{ color: (v ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>{pctSigned(v)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}

