import { useEffect, useRef, useState } from 'react'
import { useRenderTier } from '../../hooks/useRenderTier'

/**
 * A forecast rendered as a forecast.
 *
 * Every financial site collapses a probability distribution into one label — "UP ·
 * 62%" — and so did this one, which is how the calendar ended up showing FLAT on
 * 97.5% of rows and saying nothing. The model's actual output is three numbers, and
 * three numbers are what this draws: three overlapping states, opacity and offset
 * carrying probability, held in superposition for as long as the outcome genuinely
 * is unknown.
 *
 * Once an outcome exists the row collapses — the losing states fall away, the true
 * one snaps to centre. The animation is not decoration: an unresolved event and a
 * resolved one look categorically different, which is the single most important
 * thing a reader needs to know about any row.
 *
 * Hovering shortens the drift so the three bands separate and become readable; the
 * ambient state favours the impression, the hover state favours the number.
 */

type Props = {
  up?: number | null
  flat?: number | null
  down?: number | null
  /** Resolved class once known — collapses the row. */
  outcome?: 'UP' | 'FLAT' | 'DOWN' | null
  compact?: boolean
}

const STATES = [
  { key: 'DOWN', color: 'var(--down)', dir: -1 },
  { key: 'FLAT', color: 'var(--flat)', dir: 0 },
  { key: 'UP', color: 'var(--up)', dir: 1 },
] as const

export function Superposition({ up, flat, down, outcome = null, compact = false }: Props) {
  const tier = useRenderTier()
  const [hover, setHover] = useState(false)
  const [phase, setPhase] = useState(0)
  const raf = useRef(0)
  const host = useRef<HTMLDivElement | null>(null)

  const collapsed = outcome != null

  useEffect(() => {
    // Still tier and collapsed rows hold a fixed pose — nothing to animate.
    if (tier === 'still' || collapsed) return
    let alive = true
    // Only drift while on screen; a calendar can hold 90 of these.
    const io = new IntersectionObserver(([e]) => {
      alive = e.isIntersecting
      if (alive) raf.current = requestAnimationFrame(tick)
      else cancelAnimationFrame(raf.current)
    })
    if (host.current) io.observe(host.current)
    const t0 = performance.now()
    function tick(now: number) {
      if (!alive || document.hidden) return
      setPhase((now - t0) / 1000)
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf.current)
      io.disconnect()
    }
  }, [tier, collapsed])

  if (up == null || flat == null || down == null) {
    return <span className="tertiary">—</span>
  }
  const total = up + flat + down
  if (!(total > 0)) return <span className="tertiary">—</span>

  const p = { UP: up / total, FLAT: flat / total, DOWN: down / total }
  const quiet = p.FLAT
  const tone = quiet >= 0.6 ? 'high' : quiet >= 0.5 ? 'mid' : 'low'

  // Uncertainty drives the drift: a confident row is nearly still, a genuinely
  // uncertain one visibly cannot make up its mind. Entropy, normalised to [0,1].
  const entropy =
    -(['UP', 'FLAT', 'DOWN'] as const).reduce((acc, k) => {
      const v = p[k]
      return acc + (v > 0 ? v * Math.log(v) : 0)
    }, 0) / Math.log(3)

  const amplitude = collapsed || hover || tier === 'still' ? 0 : entropy * 5

  return (
    <div
      ref={host}
      className={`sup${compact ? ' sup--compact' : ''}${collapsed ? ' is-collapsed' : ''}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={`UP ${(p.UP * 100).toFixed(0)}% · FLAT ${(p.FLAT * 100).toFixed(0)}% · DOWN ${(p.DOWN * 100).toFixed(0)}%`}
    >
      <div className="sup__head">
        <span className={`sup__score sup__score--${tone}`}>{(quiet * 100).toFixed(0)}%</span>
        <span className="sup__label">
          {collapsed ? `resolved ${outcome}` : quiet >= 0.6 ? 'likely quiet' : quiet >= 0.5 ? 'leaning quiet' : 'move expected'}
        </span>
      </div>

      <div className="sup__stack">
        {STATES.map((s, i) => {
          const prob = p[s.key]
          const isTruth = collapsed && outcome === s.key
          const drift = Math.sin(phase * 0.9 + i * 2.1) * amplitude
          const opacity = collapsed ? (isTruth ? 1 : 0) : 0.25 + prob * 0.75
          return (
            <span
              key={s.key}
              className={`sup__ghost${isTruth ? ' is-truth' : ''}`}
              style={{
                background: s.color,
                width: `${(collapsed ? (isTruth ? 1 : prob) : prob) * 100}%`,
                transform: `translate3d(${collapsed ? 0 : drift + s.dir * 3}px, ${collapsed ? 0 : s.dir * -1.5}px, 0)`,
                opacity,
              }}
            />
          )
        })}
      </div>

      {!compact && (
        <div className="sup__legend">
          <span><i className="sup__dot" style={{ background: 'var(--down)' }} />{(p.DOWN * 100).toFixed(0)}</span>
          <span><i className="sup__dot" style={{ background: 'var(--flat)' }} />{(p.FLAT * 100).toFixed(0)}</span>
          <span><i className="sup__dot" style={{ background: 'var(--up)' }} />{(p.UP * 100).toFixed(0)}</span>
        </div>
      )}
    </div>
  )
}
