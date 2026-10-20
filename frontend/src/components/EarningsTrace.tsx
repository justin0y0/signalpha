import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CalendarEvent } from '../types'
import { parseLocalDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * The earnings trace — the next three weeks of reports, one column a session.
 *
 * Each column is the day's risk: amber is the model's top decile (the reports it expects
 * to break their usual range), blue the next band; the number on top is the amber count
 * and the small figure under the date is every report that day.
 * Pick a column (hover or tap) and the panel beside it lists that day's loudest names.
 *
 * It used to draw every report as its own spike. With the whole US universe that is
 * hundreds of spikes and overlapping tickers on a peak day; the per-day stack says the
 * same thing — when the risk lands, and how much of it — and can be read at a glance.
 */

type Props = { events: CalendarEvent[]; baseRate?: number | null; days?: number }
type Day = { d: Date; key: string; all: CalendarEvent[]; hot: number; warm: number; calm: number }

const H = 224
const TOP = 26
const BASE = 168

const tier = (e: CalendarEvent) => (e.move_tier === 'breakout' ? 'hot' : e.move_tier === 'elevated' ? 'warm' : 'calm')

export function EarningsTrace({ events, days = 15 }: Props) {
  const { t } = useT()
  const host = useRef<HTMLDivElement | null>(null)
  const [w, setW] = useState(760)
  const [pick, setPick] = useState<number | null>(null)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = host.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setW(Math.max(300, Math.round(entry.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const cols = useMemo<Day[]>(() => {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const out: Day[] = []
    for (let i = 0; out.length < days && i < days * 2; i++) {
      const d = new Date(today.getTime() + i * 86400_000)
      if (d.getDay() === 0 || d.getDay() === 6) continue
      out.push({ d, key: d.toDateString(), all: [], hot: 0, warm: 0, calm: 0 })
    }
    const idx = new Map(out.map((c, i) => [c.key, i]))
    for (const e of events) {
      if (e.prob_move == null) continue
      const i = idx.get(parseLocalDate(e.earnings_date).toDateString())
      if (i == null) continue
      const c = out[i]
      c.all.push(e)
      c[tier(e)] += 1
    }
    for (const c of out) c.all.sort((a, b) => (b.prob_move ?? 0) - (a.prob_move ?? 0))
    return out
  }, [events, days])

  const busiest = cols.reduce((b, c, i) => (c.hot > (cols[b]?.hot ?? -1) ? i : b), 0)
  const sel = hover ?? pick ?? busiest
  const day = cols[sel]
  // Bars carry only the risk (amber + blue); the day's total is the small figure under it.
  const max = Math.max(1, ...cols.map((c) => c.hot + c.warm))
  const pad = 8
  const cw = (w - pad * 2) / cols.length
  const bw = Math.min(30, cw * 0.56)
  const Y = (n: number) => BASE - (n / max) * (BASE - TOP)

  if (!cols.some((c) => c.all.length)) return null
  const fmtDay = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })

  return (
    <div className="trace">
      <div className="trace__plot" ref={host}>
        <svg className="trace__svg" viewBox={`0 0 ${w} ${H}`} role="img"
          aria-label={t('trace.aria', { n: cols.reduce((n, c) => n + c.all.length, 0) })}
          onPointerLeave={() => setHover(null)}>
          {[0.5, 1].map((f) => (
            <line key={f} x1={0} x2={w} y1={Y(max * f)} y2={Y(max * f)} className="trace__grid" />
          ))}
          <line x1={0} x2={w} y1={BASE} y2={BASE} className="trace__zero" />
          {cols.map((c, i) => {
            const x = pad + i * cw + (cw - bw) / 2
            const yHot = Y(c.hot), yWarm = Y(c.hot + c.warm)
            const on = i === sel
            return (
              <g key={c.key} className={`trace__col${on ? ' is-on' : ''}`}
                onPointerEnter={() => setHover(i)} onClick={() => setPick(i)}>
                <rect x={pad + i * cw} y={TOP - 18} width={cw} height={BASE - TOP + 50} className="trace__hit" />
                {c.d.getDay() === 1 && i > 0 && <line x1={pad + i * cw} x2={pad + i * cw} y1={TOP - 10} y2={BASE + 6} className="trace__week" />}
                {c.warm > 0 && <rect x={x} y={yWarm} width={bw} height={Math.max(0, yHot - yWarm)} className="trace__bar is-warm" />}
                {c.hot > 0 && <rect x={x} y={yHot} width={bw} height={Math.max(0, BASE - yHot)} className="trace__bar is-hot" />}
                {c.hot > 0 && <text x={x + bw / 2} y={yWarm - 6} className="trace__n">{c.hot}</text>}
                <text x={pad + i * cw + cw / 2} y={BASE + 20} className="trace__dow">{c.d.toLocaleDateString(undefined, { weekday: 'narrow' })}</text>
                <text x={pad + i * cw + cw / 2} y={BASE + 35} className={`trace__dom${i === 0 ? ' is-today' : ''}`}>{c.d.getDate()}</text>
                {c.all.length > 0 && <text x={pad + i * cw + cw / 2} y={BASE + 50} className="trace__tot">{c.all.length}</text>}
              </g>
            )
          })}
        </svg>
        <div className="trace__legend">
          <span><i className="is-hot" />{t('move.breakout')}</span>
          <span><i className="is-warm" />{t('move.elevated')}</span>
          <span><b className="trace__tot-k">123</b>{t('trace.totKey')}</span>
          <span className="trace__hint">{t('trace.hint2')}</span>
        </div>
      </div>

      <aside className="trace__day" aria-live="polite">
        <span className="trace__day-k">{fmtDay(day.d)}</span>
        <p className="trace__day-n"><b>{day.hot}</b> {t('trace.dayHot')} <span>· {t('trace.dayAll', { n: day.all.length })}</span></p>
        {day.all.length === 0 ? (
          <p className="trace__day-empty">{t('trace.dayNone')}</p>
        ) : (
          <ol>
            {day.all.slice(0, 6).map((e) => (
              <li key={e.ticker}>
                <Link to={`/predict/${e.ticker}?earnings_date=${e.earnings_date}`}>
                  <b className={`is-${tier(e)}`}>{e.ticker}</b>
                  <span className="trace__co">{e.company_name}</span>
                  <span className="trace__p">{((e.prob_move ?? 0) * 100).toFixed(0)}%</span>
                  <span className="trace__when">{e.report_time ?? ''}</span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </aside>
    </div>
  )
}
