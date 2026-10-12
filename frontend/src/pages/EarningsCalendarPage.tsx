import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, Search } from 'lucide-react'
import { api } from '../api/client'
import type { CalendarEvent, CalendarResponse } from '../types'
import { MoveRisk } from '../components/ui/MoveRisk'
import { LeanChip } from '../components/ui/LeanChip'
import { Num } from '../components/ui/Num'
import { useHeadline } from '../hooks/useHeadline'
import { EarningsTrace } from '../components/EarningsTrace'
import { RiskAudio } from '../components/RiskAudio'
import { PageHead } from '../components/PageHead'
import { WireStrip } from '../components/WireStrip'
import { useT } from '../i18n'
import { daysUntil, parseLocalDate } from '../utils/date'
import './CalendarPage.css'

/**
 * 01 · Calendar — what is coming, and which of it matters.
 *
 * Step one of the loop. The trace shows the next three weeks at a glance; the docket
 * below is the same reports as a list, grouped by day because that is how an earnings
 * week is actually read.
 */

const SECTORS = ['All', 'Technology', 'Financial Services', 'Healthcare', 'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Energy', 'Communication Services']
type Scope = 'upcoming' | 'flagged' | 'past'

export function EarningsCalendarPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const headline = useHeadline()
  const breakout = headline?.breakout
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState('All')
  const [scope, setScope] = useState<Scope>('upcoming')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const params = new URLSearchParams({ days_forward: '90', days_back: '30' })
        const res: CalendarResponse = await api.getCalendar(params)
        setEvents(res.items)
        setError(null)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'failed to load calendar')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const upcoming = useMemo(() => events.filter((e) => daysUntil(e.earnings_date) >= 0), [events])
  const stats = useMemo(() => ({
    ahead: upcoming.length,
    week: upcoming.filter((e) => daysUntil(e.earnings_date) <= 7).length,
    watch: upcoming.filter((e) => e.move_tier === 'breakout').length,
    elevated: upcoming.filter((e) => e.move_tier === 'elevated').length,
  }), [upcoming])

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = events.filter((e) => {
      const du = daysUntil(e.earnings_date)
      if (scope === 'past' ? du >= 0 : du < 0) return false
      if (scope === 'flagged' && e.move_tier !== 'breakout' && e.move_tier !== 'elevated') return false
      if (sector !== 'All' && e.sector !== sector) return false
      if (q && !(e.ticker.toLowerCase().includes(q) || (e.company_name ?? '').toLowerCase().includes(q))) return false
      return true
    })
    rows.sort((a, b) => (scope === 'past' ? b.earnings_date.localeCompare(a.earnings_date) : a.earnings_date.localeCompare(b.earnings_date))
      || (b.prob_move ?? 0) - (a.prob_move ?? 0))
    const out: { date: string; rows: CalendarEvent[] }[] = []
    for (const r of rows) {
      const last = out[out.length - 1]
      if (last && last.date === r.earnings_date) last.rows.push(r)
      else out.push({ date: r.earnings_date, rows: [r] })
    }
    return out
  }, [events, query, sector, scope])
  const shown = groups.reduce((n, g) => n + g.rows.length, 0)

  const open = (e: CalendarEvent) => navigate(`/predict/${e.ticker}?earnings_date=${e.earnings_date}`)
  const dayLabel = (iso: string) => {
    const du = daysUntil(iso)
    return du === 0 ? t('cal.today') : du === 1 ? t('cal.tomorrow') : du > 0 ? t('cal.inDays', { n: du }) : t('cal.daysAgo', { n: -du })
  }

  return (
    <div className="cal">
      <PageHead
        kicker={t('nav.calendar')}
        title={<>{t('cal.h.a')} <em>{t('cal.h.b')}</em></>}
        lede={t('cal.h.lede')}
        spike={0.72}
      >
        <div className="figs">
          <div><b><Num value={stats.ahead} /></b><span>{t('cal.fig.ahead')}</span></div>
          <div><b><Num value={stats.week} /></b><span>{t('cal.fig.week')}</span></div>
          <div className="is-signal"><b><Num value={stats.watch} /></b><span>{t('cal.fig.watch')}</span></div>
        </div>
      </PageHead>

      <section className="cal-trace">
        <div className="cal-trace__head">
          <span className="eyebrow">{t('trace.title')}</span>
          <RiskAudio quietScores={upcoming.filter((e) => e.prob_move != null).map((e) => 1 - (e.prob_move as number))} />
        </div>
        {loading ? <div className="shimmer" style={{ height: 300 }} /> : <EarningsTrace events={upcoming} baseRate={breakout?.base_rate} />}
      </section>

      <WireStrip />

      <section className="docket">
        <div className="docket__bar">
          <h2 className="docket__title">{t('cal.docket')}</h2>
          <div className="seg" role="group" aria-label={t('cal.scope')}>
            {(['upcoming', 'flagged', 'past'] as const).map((s) => (
              <button key={s} type="button" className={scope === s ? 'is-on' : ''} onClick={() => setScope(s)}>
                {t(`cal.scope.${s}` as 'cal.scope.upcoming')}
                {s === 'flagged' && stats.watch + stats.elevated > 0 && <i>{stats.watch + stats.elevated}</i>}
              </button>
            ))}
          </div>
          <div className="docket__search">
            <Search size={14} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('cal.search.placeholder')} aria-label={t('cal.search')} />
          </div>
          <select className="docket__select" value={sector} onChange={(e) => setSector(e.target.value)} aria-label={t('cal.sector')}>
            {SECTORS.map((s) => <option key={s} value={s}>{s === 'All' ? t('cal.sector.all') : s}</option>)}
          </select>
        </div>

        {loading ? (
          <div style={{ display: 'grid', gap: 8 }}>{[0, 1, 2, 3].map((i) => <div key={i} className="shimmer" style={{ height: 52 }} />)}</div>
        ) : error ? (
          <div className="empty-state">{error}</div>
        ) : groups.length === 0 ? (
          <div className="empty-state">{t('cal.empty')}</div>
        ) : (
          <div className="docket__list">
            <div className="docket__cols" aria-hidden="true">
              <span>{t('cal.col.company')}</span><span>{t('cal.col.when')}</span><span>{t('cal.col.moveRisk')}</span>
              <span>{t('cal.col.lean')}</span><span className="r">{t('cal.col.move')}</span><span />
            </div>
            {groups.map((g) => {
              const d = parseLocalDate(g.date)
              return (
                <div key={g.date} className="docket__day">
                  <div className="docket__date">
                    <b className="serif">{d.toLocaleDateString(undefined, { weekday: 'long' })}</b>
                    <span>{d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                    <i>{dayLabel(g.date)}</i>
                    <em>{t('cal.nReports', { n: g.rows.length })}</em>
                  </div>
                  {g.rows.map((e) => (
                    <button key={e.ticker} type="button" className={`docket__row is-${e.move_tier ?? 'none'}`} onClick={() => open(e)}>
                      <span className="docket__name">
                        <b>{e.ticker}</b>
                        <small>{e.company_name ?? '—'}{e.sector ? <i> · {e.sector}</i> : null}</small>
                      </span>
                      <span>{e.report_time
                        ? <span className={`when-chip when-chip--${e.report_time.toLowerCase()}`}>{t(`when.${e.report_time.toLowerCase()}` as 'when.bmo')}</span>
                        : <span className="tertiary">—</span>}</span>
                      <span><MoveRisk compact prob={e.prob_move} tier={e.move_tier} band={e.flat_band} baseRate={breakout?.base_rate} /></span>
                      <span><LeanChip p={e.lean_up} /></span>
                      <span className="mono r docket__move">
                        {e.implied_move_pct != null ? `±${(e.implied_move_pct * 100).toFixed(1)}%` : <span className="tertiary">—</span>}
                        {e.flat_band != null && <small>{t('cal.usual', { v: (e.flat_band * 100).toFixed(1) })}</small>}
                      </span>
                      <span className="docket__go"><ArrowUpRight size={15} /></span>
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        )}
        <p className="docket__foot">{t('cal.footer', { shown, total: events.length, auc: breakout ? breakout.auc.toFixed(3) : '—' })}</p>
      </section>
    </div>
  )
}
