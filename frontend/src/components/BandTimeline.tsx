import { useEffect, useMemo, useRef, useState } from 'react'
import type React from 'react'
import { useRenderTier } from '../hooks/useRenderTier'
import type { CalendarEvent } from '../types'
import { parseLocalDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * Concept B — the calendar as a scrubbed timeline, with each stock's own flat band
 * drawn to scale.
 *
 * The point this exists to make: a 2% earnings move is enormous for a utility and
 * noise for TSLA, so the model labels each stock against its own historical reaction
 * median earnings reaction. That is the single most important thing about how
 * this model reads the world and it is invisible in a table of numbers. Here the band
 * is drawn — the grey slab behind each event is literally how far that stock has to
 * move before anyone calls it a move, and the bar is what the model expects.
 *
 * Colour comes from the breakout classifier's tier, not from "bar taller than band".
 * The regression estimate clears the band for roughly half of all reports — which is
 * just the base rate — so painting those amber told visitors half the calendar would
 * break out while the Calendar page, using the model that actually has skill, flagged
 * three. One site, one claim.
 *
 * Scroll scrubs the window rather than paging it, so 90 days pass under a fixed
 * viewport: pin-and-scrub, the pattern most award sites use to pace a story.
 */

type Props = { events: CalendarEvent[] }

const WINDOW_DAYS = 21

export function BandTimeline({ events }: Props) {
  const { t } = useT()
  const tier = useRenderTier()
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [offset, setOffset] = useState(0)
  const [hovered, setHovered] = useState<string | null>(null)
  const pausedRef = useRef(false)

  const rows = useMemo(() => {
    return events
      // A stock with no reaction history has no band to draw against.
      .filter((e) => e.flat_band != null)
      .map((e) => ({
        ticker: e.ticker,
        sector: e.sector,
        date: e.earnings_date,
        day: parseLocalDate(e.earnings_date).getTime(),
        // What options are pricing. This was the regression's estimate, which ranks
        // actual moves worse than the band it was being drawn against.
        move: e.implied_move_pct != null ? Math.abs(e.implied_move_pct) : null,
        band: e.flat_band as number,
        tier: e.move_tier ?? null,
        prob: e.prob_move ?? null,
      }))
      .sort((a, b) => a.day - b.day)
  }, [events])

  // Scrub inside the panel, never by hijacking the page.
  //
  // The first version pinned this and consumed up to 360vh of scroll, which pushed
  // the actual backtest tools 3.6 screens down — you had to scrub the whole calendar
  // before reaching the thing you came for. A component that explains the data has no
  // business holding the page hostage. It now drifts on its own and hands control to
  // the pointer on hover, so it costs exactly the height it occupies.
  useEffect(() => {
    if (!rows.length || tier === 'still') return
    const span = Math.max(0, rows.length - WINDOW_DAYS)
    if (span <= 0) return
    let raf = 0
    let last = performance.now()
    let alive = true
    const io = new IntersectionObserver(([e]) => {
      const was = alive
      alive = e.isIntersecting
      if (alive && !was) { last = performance.now(); raf = requestAnimationFrame(step) }
    })
    if (hostRef.current) io.observe(hostRef.current)
    function step(now: number) {
      if (!alive || document.hidden) return
      const dt = Math.min(80, now - last)
      last = now
      if (!pausedRef.current) {
        setOffset((o) => {
          const next = o + dt * 0.0011 * span * 0.06
          return next >= span ? 0 : next
        })
      }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => { cancelAnimationFrame(raf); io.disconnect() }
  }, [rows.length, tier])

  // Hover hands the scrub to the pointer: sweep across to move through the calendar.
  const onPointer = (ev: React.PointerEvent<HTMLDivElement>) => {
    const span = Math.max(0, rows.length - WINDOW_DAYS)
    if (span <= 0) return
    const r = ev.currentTarget.getBoundingClientRect()
    const p = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width))
    setOffset(p * span)
  }

  if (!rows.length) return null

  const start = Math.floor(offset)
  const frac = offset - start
  const visible = rows.slice(start, start + WINDOW_DAYS + 1)
  const maxBand = Math.max(...rows.map((r) => Math.max(r.band, r.move ?? 0)), 0.06)

  return (
    <div ref={hostRef} className="bandtl">
      <div
        className="bandtl__stage"
        onPointerMove={onPointer}
        onPointerEnter={() => { pausedRef.current = true }}
        onPointerLeave={() => { pausedRef.current = false; setHovered(null) }}
      >
        <div className="bandtl__head">
          <div>
            <div className="bandtl__kicker">{t('band.kicker')}</div>
            <h3 className="bandtl__title">{t('band.title')}</h3>
            <p className="bandtl__sub">
              {t('band.sub')}</p>
          </div>
          <div className="bandtl__scrubhint">
            {tier === 'still' ? `${rows.length} events` : t('band.hint')}
          </div>
        </div>

        <div className="bandtl__track" style={{ transform: tier === 'still' ? undefined : `translateX(${-frac * (100 / WINDOW_DAYS)}%)` }}>
          {(tier === 'still' ? rows.slice(0, WINDOW_DAYS) : visible).map((r) => {
            const band = r.band
            const bandPct = (band / maxBand) * 100
            const movePct = ((r.move ?? 0) / maxBand) * 100
            const hot = r.tier === 'breakout' ? ' is-breach' : r.tier === 'elevated' ? ' is-elevated' : ''
            const active = hovered === r.ticker + r.date
            return (
              <div
                key={r.ticker + r.date}
                className={`bandtl__col${active ? ' is-active' : ''}`}
                onMouseEnter={() => setHovered(r.ticker + r.date)}
                onMouseLeave={() => setHovered(null)}
              >
                <div className="bandtl__well">
                  <span className="bandtl__band" style={{ height: `${bandPct}%` }} />
                  <span
                    className={`bandtl__bar${hot}`}
                    style={{ height: `${Math.min(100, movePct)}%` }}
                  />
                </div>
                <div className="bandtl__tick">{r.ticker}</div>
                {active && (
                  <div className="bandtl__pop">
                    <b>{r.ticker}</b>
                    <span>{t('band.pop.band', { v: (band * 100).toFixed(2) })}</span>
                    <span>{r.move != null ? t('band.pop.expected', { v: (r.move * 100).toFixed(2) }) : t('band.pop.noOptions')}</span>
                    <span className={hot.trim()}>
                      {r.prob != null ? `${t('cal.col.moveRisk')} ${(r.prob * 100).toFixed(0)}% · ` : ''}
                      {r.tier ? t(`move.${r.tier}`) : t('move.unscored')}
                    </span>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="bandtl__legend">
          <span><i className="bandtl__swatch bandtl__swatch--band" />{t('band.legend.band')}</span>
          <span><i className="bandtl__swatch bandtl__swatch--bar" />{t('band.legend.bar')}</span>
          <span><i className="bandtl__swatch bandtl__swatch--elevated" />{t('move.elevated')}</span>
          <span><i className="bandtl__swatch bandtl__swatch--breach" />{t('band.legend.breach')}</span>
        </div>
      </div>
    </div>
  )
}
