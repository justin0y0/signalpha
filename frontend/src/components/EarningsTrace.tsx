import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CalendarEvent } from '../types'
import { parseLocalDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * The earnings trace — the calendar drawn as a seismograph.
 *
 * Time runs left to right over the next three weeks. Every report is a spike on the
 * trace, as tall as its breakout risk; amber spikes are the model's top decile, blue
 * the top fifth. The dashed line is the base rate, so "taller than the line" literally
 * means "more likely than usual to move". Sweep across it and the readout follows;
 * click to open the report.
 *
 * It replaces a particle field that looked alive but could not be read. This one is
 * the data.
 */

type Props = { events: CalendarEvent[]; baseRate?: number | null; days?: number }
type Pt = { e: CalendarEvent; x: number; tip: number; day: number }

const H = 250
const BASE = 196
const TOP = 34
const MAX_PER_DAY = 16

export function EarningsTrace({ events, baseRate, days = 21 }: Props) {
  const { t } = useT()
  const nav = useNavigate()
  const host = useRef<HTMLDivElement | null>(null)
  const [w, setW] = useState(1100)
  const [hot, setHot] = useState<Pt | null>(null)

  useEffect(() => {
    const el = host.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setW(Math.max(320, Math.round(entry.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { cols, pts } = useMemo(() => {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const cols: { d: Date; key: string }[] = []
    for (let i = 0; cols.length < days && i < days * 2; i++) {
      const d = new Date(today.getTime() + i * 86400_000)
      if (d.getDay() === 0 || d.getDay() === 6) continue
      cols.push({ d, key: d.toDateString() })
    }
    const idx = new Map(cols.map((c, i) => [c.key, i]))
    const byDay = new Map<number, CalendarEvent[]>()
    for (const e of events) {
      if (e.prob_move == null) continue
      const i = idx.get(parseLocalDate(e.earnings_date).toDateString())
      if (i == null) continue
      const list = byDay.get(i) ?? []
      list.push(e)
      byDay.set(i, list)
    }
    const pad = 18
    const cw = (w - pad * 2) / cols.length
    const pts: Pt[] = []
    byDay.forEach((full, day) => {
      // A peak day can hold hundreds of reports; the trace draws the loudest of them.
      const list = full.sort((a, b) => (b.prob_move ?? 0) - (a.prob_move ?? 0)).slice(0, MAX_PER_DAY)
      list.forEach((e, k) => {
        const x = pad + day * cw + ((k + 0.5) / list.length) * cw
        const p = Math.min(1, Math.max(0, e.prob_move as number))
        // 30%..90% probability spans the usable height; below 30% is still a visible blip
        const tip = BASE - Math.max(10, ((p - 0.3) / 0.6) * (BASE - TOP))
        pts.push({ e, x, tip, day })
      })
    })
    pts.sort((a, b) => a.x - b.x)
    return { cols: cols.map((c, i) => ({ ...c, x: pad + i * cw, cw })), pts }
  }, [events, w, days])

  const baseY = baseRate != null ? BASE - ((baseRate - 0.3) / 0.6) * (BASE - TOP) : null

  const onMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect()
    const px = ((ev.clientX - r.left) / r.width) * w
    let best: Pt | null = null
    for (const p of pts) if (!best || Math.abs(p.x - px) < Math.abs(best.x - px)) best = p
    setHot(best && Math.abs(best.x - px) < 60 ? best : null)
  }

  if (!pts.length) return null
  const shown = hot ?? pts.reduce((a, b) => ((b.e.prob_move ?? 0) > (a.e.prob_move ?? 0) ? b : a), pts[0])
  const tone = (e: CalendarEvent) => (e.move_tier === 'breakout' ? 'hot' : e.move_tier === 'elevated' ? 'warm' : 'calm')
  const labelled = new Set(pts.filter((p) => p.e.move_tier === 'breakout').map((p) => p.e.ticker + p.e.earnings_date))

  return (
    <div className="trace" ref={host}>
      <div className="trace__readout" aria-live="polite">
        <span className="trace__readout-k">{hot ? t('trace.reading') : t('trace.loudest')}</span>
        <b className="serif">{shown.e.ticker}</b>
        <span className="trace__readout-co">{shown.e.company_name}</span>
        <dl>
          <div><dt>{t('cal.col.moveRisk')}</dt><dd className={`is-${tone(shown.e)}`}>{((shown.e.prob_move ?? 0) * 100).toFixed(0)}%</dd></div>
          <div><dt>{t('brief.col.usual')}</dt><dd>{shown.e.flat_band != null ? `±${(shown.e.flat_band * 100).toFixed(1)}%` : '—'}</dd></div>
          <div><dt>{t('cal.col.move')}</dt><dd>{shown.e.implied_move_pct != null ? `±${(shown.e.implied_move_pct * 100).toFixed(1)}%` : '—'}</dd></div>
          <div><dt>{t('cal.col.when')}</dt><dd>{parseLocalDate(shown.e.earnings_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}{shown.e.report_time ? ` · ${shown.e.report_time}` : ''}</dd></div>
        </dl>
      </div>

      <svg
        className="trace__svg" viewBox={`0 0 ${w} ${H}`} role="img" aria-label={t('trace.aria', { n: pts.length })}
        onPointerMove={onMove} onPointerLeave={() => setHot(null)}
        onClick={() => { if (hot) nav(`/predict/${hot.e.ticker}?earnings_date=${hot.e.earnings_date}`) }}
        style={{ cursor: hot ? 'pointer' : 'crosshair' }}
      >
        {cols.map((c, i) => (
          <g key={c.key}>
            {c.d.getDay() === 1 && i > 0 && <line x1={c.x} x2={c.x} y1={TOP - 14} y2={BASE + 8} className="trace__week" />}
            <text x={c.x + c.cw / 2} y={BASE + 24} className="trace__dow">{c.d.toLocaleDateString(undefined, { weekday: 'narrow' })}</text>
            <text x={c.x + c.cw / 2} y={BASE + 40} className={`trace__dom${c.d.toDateString() === new Date().toDateString() ? ' is-today' : ''}`}>{c.d.getDate()}</text>
          </g>
        ))}
        {baseY != null && (
          <g>
            <line x1={0} x2={w} y1={baseY} y2={baseY} className="trace__base" />
            <text x={w - 6} y={baseY - 6} className="trace__baselbl">{t('trace.base', { v: Math.round((baseRate as number) * 100) })}</text>
          </g>
        )}
        <line x1={0} x2={w} y1={BASE} y2={BASE} className="trace__zero" />
        {pts.map((p, i) => {
          const on = hot === p
          const d = `M${p.x - 5} ${BASE} L${p.x - 2.2} ${BASE + 3} L${p.x} ${p.tip} L${p.x + 2.2} ${BASE + 6} L${p.x + 5} ${BASE}`
          return (
            <g key={p.e.ticker + p.e.earnings_date} className={`trace__spike is-${tone(p.e)}${on ? ' is-on' : ''}`}>
              <path d={d} pathLength={1} style={{ animationDelay: `${0.25 + i * 0.018}s` }} />
              {(on || labelled.has(p.e.ticker + p.e.earnings_date)) && (
                <text x={p.x} y={p.tip - 8} className="trace__tick">{p.e.ticker}</text>
              )}
            </g>
          )
        })}
        {hot && <line x1={hot.x} x2={hot.x} y1={TOP - 16} y2={BASE} className="trace__cursor" />}
        <defs>
          <linearGradient id="trace-scan" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#f5b544" stopOpacity="0" />
            <stop offset="1" stopColor="#f5b544" stopOpacity="0.16" />
          </linearGradient>
        </defs>
        <g className="trace__scan">
          <rect x={-120} y={TOP - 16} width={120} height={BASE - TOP + 16} fill="url(#trace-scan)" />
          <line x1={0} x2={0} y1={TOP - 16} y2={BASE} stroke="#f5b544" strokeOpacity="0.55" strokeWidth="1" />
        </g>
      </svg>

      <div className="trace__legend">
        <span><i className="is-hot" />{t('move.breakout')}</span>
        <span><i className="is-warm" />{t('move.elevated')}</span>
        <span><i className="is-calm" />{t('move.normal')}</span>
        <span className="trace__hint">{t('trace.hint')}</span>
      </div>
    </div>
  )
}
