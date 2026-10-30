import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useT } from '../i18n'

/**
 * Last and next report for one stock, to the minute where that is knowable: the last one
 * from the SEC's acceptance time of the results 8-K (to the second), the next one from the
 * calendar — marked unconfirmed when the company has not said. Under the last report, the
 * calls sealed before it (Earnings Arena) against what the stock did.
 */
type Call = { forecaster: string; p: number | null; lean: string | null; sealed_at: string | null; brier: number | null }
type Last = {
  date: string; ts: string | null; session: string | null; source: 'sec' | 'yahoo'; sec_url: string | null
  eps_estimate: number | null; eps_actual: number | null; surprise: number | null; event_date?: string
  actual?: { reaction_date: string | null; gap: number | null; move: number | null; band: number | null; broke_out: boolean | null }
  calls?: Call[]; model?: { p: number; lean_up: number | null; made_at: string }
}
type Next = { date: string; ts: string | null; session: string | null; confirmed: boolean; source: string; eps_estimate?: number | null }
type Sched = { ticker: string; last: Last | null; next: Next | null }

const ET = { timeZone: 'America/New_York' } as const
const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`)
const NAMES: Record<string, string> = { signalpha_ml: 'SignAlpha ML', options_market: 'Options', base_rate: 'Base rate', gpt_oss_120b: 'GPT-OSS', qwen3: 'Qwen3', claude: 'Claude' }

function When({ date, ts, session, confirmed = true }: { date: string; ts: string | null; session: string | null; confirmed?: boolean }) {
  const { t, locale } = useT()
  const d = ts ? new Date(ts) : new Date(`${date}T12:00:00`)
  const day = d.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', { ...ET, year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' })
  const hm = ts ? d.toLocaleTimeString(locale === 'zh' ? 'zh-CN' : 'en-US', { ...ET, hour: '2-digit', minute: '2-digit', hour12: false }) : null
  const s = (session || '').toLowerCase()
  return (
    <div className="esched__when">
      <b>{day}</b>
      <span className="mono">{hm ? `${hm} ET` : t('es.timeTbd')}</span>
      {s && ['bmo', 'amc', 'dmh'].includes(s) && <span className={`when-chip when-chip--${s}`}>{t(`when.${s}` as 'when.bmo')}{confirmed ? '' : ` · ${t('es.usual')}`}</span>}
    </div>
  )
}

export function EarningsSchedule({ ticker }: { ticker: string }) {
  const { t } = useT()
  const [d, setD] = useState<Sched | null>(null)
  useEffect(() => {
    setD(null)
    fetch(`/api/v1/predict/${encodeURIComponent(ticker)}/schedule`).then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => setD(null))
  }, [ticker])
  if (!d || (!d.last && !d.next)) return null
  const L = d.last
  const ml = L?.calls?.find((c) => c.forecaster === 'signalpha_ml')
  const preModel = L?.model && L.ts && new Date(L.model.made_at) < new Date(L.ts) ? L.model : null
  return (
    <section className="card esched">
      <h3 className="card-title">{t('es.title')}</h3>
      <div className="esched__grid">
        <div className="esched__col">
          <span className="esched__label">{t('es.next')}</span>
          {d.next ? (
            <>
              <When date={d.next.date} ts={d.next.ts} session={d.next.session} confirmed={d.next.confirmed} />
              <p className="esched__note">{d.next.confirmed ? t('es.nextSrc') : t('es.unconfirmed')}{d.next.eps_estimate != null ? ` · ${t('es.est', { v: d.next.eps_estimate.toFixed(2) })}` : ''}</p>
            </>
          ) : <p className="esched__note">{t('es.noNext')}</p>}
        </div>
        <div className="esched__col">
          <span className="esched__label">{t('es.last')}</span>
          {L ? (
            <>
              <When date={L.date} ts={L.ts} session={L.session} />
              <p className="esched__note">
                {L.source === 'sec' ? <>{t('es.secSrc')} {L.sec_url && <a href={L.sec_url} target="_blank" rel="noreferrer">8-K ↗</a>}</> : t('es.yahooSrc')}
                {L.eps_actual != null && L.eps_estimate != null && <> · EPS {L.eps_actual.toFixed(2)} {t('es.vs')} {L.eps_estimate.toFixed(2)} ({pct(L.surprise)})</>}
              </p>
            </>
          ) : <p className="esched__note">—</p>}
        </div>
      </div>
      {L?.actual && (
        <div className="esched__vs">
          <div>
            <span className="esched__label">{t('es.called')}</span>
            {ml?.p != null ? <b>{t('es.pBreak', { p: Math.round(ml.p * 100) })}{ml.lean && ml.lean !== 'NONE' ? ` · ${t(ml.lean === 'UP' ? 'es.leanUp' : 'es.leanDown')}` : ''}</b>
              : preModel ? <b>{t('es.pBreak', { p: Math.round(preModel.p * 100) })}</b> : <b className="esched__dim">{t('es.noCall')}</b>}
            {ml?.sealed_at && <em>{t('es.sealed', { d: new Date(ml.sealed_at).toLocaleDateString(undefined, { ...ET, month: 'short', day: 'numeric' }) })}</em>}
          </div>
          <div>
            <span className="esched__label">{t('es.happened')}</span>
            <b className={L.actual.move == null ? '' : L.actual.move >= 0 ? 'is-up' : 'is-down'}>{pct(L.actual.move)}</b>
            <em>{L.actual.band != null ? t('es.usualMove', { b: (L.actual.band * 100).toFixed(1) }) : ''}{L.actual.broke_out != null ? ` · ${t(L.actual.broke_out ? 'es.broke' : 'es.held')}` : ''}</em>
          </div>
          {L.calls && L.calls.length > 1 && (
            <div className="esched__others">
              {L.calls.filter((c) => c.forecaster !== 'signalpha_ml' && c.p != null).map((c) => <span key={c.forecaster}>{NAMES[c.forecaster] ?? c.forecaster} {Math.round((c.p ?? 0) * 100)}%</span>)}
            </div>
          )}
          <Link className="esched__link" to={`/predict/${d.ticker}?earnings_date=${L.event_date ?? L.date}`}>{t('es.open')}</Link>
        </div>
      )}
    </section>
  )
}
