import { useEffect, useMemo, useRef, useState } from 'react'
import { useRenderTier } from '../hooks/useRenderTier'
import type { CalendarEvent } from '../types'
import { parseLocalDate } from '../utils/date'

/**
 * Concept B — the calendar as a scrubbed timeline, with each stock's own flat band
 * drawn to scale.
 *
 * The point this exists to make: a 2% earnings move is enormous for a utility and
 * noise for TSLA, so the model labels each stock against its own historical reaction
 * sigma (MMM ±2.5%, TSLA ±4.4%). That is the single most important thing about how
 * this model reads the world and it is invisible in a table of numbers. Here the band
 * is drawn — the grey slab behind each event is literally how far that stock has to
 * move before anyone calls it a move, and the bar is what the model expects.
 *
 * Scroll scrubs the window rather than paging it, so 90 days pass under a fixed
 * viewport: pin-and-scrub, the pattern most award sites use to pace a story.
 */

type Props = { events: CalendarEvent[] }

const WINDOW_DAYS = 21

export function BandTimeline({ events }: Props) {
  const tier = useRenderTier()
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [offset, setOffset] = useState(0)
  const [hovered, setHovered] = useState<string | null>(null)

  const rows = useMemo(() => {
    return events
      .filter((e) => e.expected_move_pct != null && e.direction_prob_flat != null)
      .map((e) => ({
        ticker: e.ticker,
        sector: e.sector,
        date: e.earnings_date,
        day: parseLocalDate(e.earnings_date).getTime(),
        move: Math.abs(e.expected_move_pct as number),
        quiet: e.direction_prob_flat as number,
      }))
      .sort((a, b) => a.day - b.day)
  }, [events])

  // Scrub: vertical scroll over the pinned section advances the window.
  useEffect(() => {
    if (!rows.length) return
    const host = hostRef.current
    if (!host) return
    const onScroll = () => {
      const rect = host.getBoundingClientRect()
      const travel = rect.height - window.innerHeight
      if (travel <= 0) return
      const progress = Math.min(1, Math.max(0, -rect.top / travel))
      setOffset(progress * Math.max(0, rows.length - WINDOW_DAYS))
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [rows.length])

  if (!rows.length) return null

  const start = Math.floor(offset)
  const frac = offset - start
  const visible = rows.slice(start, start + WINDOW_DAYS + 1)
  const maxBand = Math.max(...rows.map((r) => bandFor(r.quiet, r.move)), 0.06)

  return (
    <div
      ref={hostRef}
      className="bandtl"
      style={{ height: tier === 'still' ? 'auto' : `${Math.min(360, rows.length * 9)}vh` }}
    >
      <div className={`bandtl__stage${tier === 'still' ? ' is-static' : ''}`}>
        <div className="bandtl__head">
          <div>
            <div className="bandtl__kicker">Flat band, to scale</div>
            <h3 className="bandtl__title">What counts as a move depends on the stock</h3>
            <p className="bandtl__sub">
              The grey slab is how far this name has to travel before the model calls it a
              direction — its own historical reaction sigma, not a fixed 2%. The bar is the move
              it expects.
            </p>
          </div>
          <div className="bandtl__scrubhint">
            {tier === 'still' ? `${rows.length} events` : 'scroll to scrub →'}
          </div>
        </div>

        <div className="bandtl__track" style={{ transform: tier === 'still' ? undefined : `translateX(${-frac * (100 / WINDOW_DAYS)}%)` }}>
          {(tier === 'still' ? rows.slice(0, 14) : visible).map((r) => {
            const band = bandFor(r.quiet, r.move)
            const bandPct = (band / maxBand) * 100
            const movePct = (r.move / maxBand) * 100
            const breaches = r.move > band
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
                    className={`bandtl__bar${breaches ? ' is-breach' : ''}`}
                    style={{ height: `${Math.min(100, movePct)}%` }}
                  />
                </div>
                <div className="bandtl__tick">{r.ticker}</div>
                {active && (
                  <div className="bandtl__pop">
                    <b>{r.ticker}</b>
                    <span>flat band ±{(band * 100).toFixed(2)}%</span>
                    <span>expected ±{(r.move * 100).toFixed(2)}%</span>
                    <span className={breaches ? 'is-breach' : ''}>
                      {breaches ? 'expected to break its band' : 'expected to stay inside'}
                    </span>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="bandtl__legend">
          <span><i className="bandtl__swatch bandtl__swatch--band" />flat band for this stock</span>
          <span><i className="bandtl__swatch bandtl__swatch--bar" />expected move</span>
          <span><i className="bandtl__swatch bandtl__swatch--breach" />expected to break out</span>
        </div>
      </div>
    </div>
  )
}

/**
 * The band the backend labels against, reconstructed for display: 0.5x the stock's own
 * reaction sigma, clamped to [2.5%, 10%]. Expected move is the best per-row proxy
 * available on the calendar payload, so a name the model reads as quiet with a small
 * expected move gets a tight band and a volatile one gets a wide one.
 */
function bandFor(quiet: number, move: number): number {
  const implied = move * (0.6 + (1 - quiet) * 1.1)
  return Math.min(0.1, Math.max(0.025, implied))
}
