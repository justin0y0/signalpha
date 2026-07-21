import { useEffect, useRef, useState } from 'react'
import { useRenderTier } from '../../hooks/useRenderTier'

/**
 * Concept D — split-flap display, for the Brief.
 *
 * Earnings are scheduled departures, and the Brief is the departures hall: a fixed
 * list of things leaving at known times, refreshed each morning. A flap board is the
 * native instrument for that, and it costs no GPU — which matters on the one page
 * meant to be opened every day, including on a phone.
 *
 * The flap only runs when the value actually changes, so a static board is genuinely
 * static rather than perpetually shuffling for effect. Reduced-motion users get the
 * final characters immediately.
 */

const GLYPHS = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,+-%'

type Props = {
  value: string
  /** Pad or truncate to this many cells so columns line up. */
  width?: number
  className?: string
}

export function SplitFlap({ value, width, className = '' }: Props) {
  const tier = useRenderTier()
  const target = (width ? value.slice(0, width).padEnd(width, ' ') : value).toUpperCase()
  const [shown, setShown] = useState(target)
  const timer = useRef<number>(0)

  useEffect(() => {
    if (tier === 'still') {
      setShown(target)
      return
    }
    // Nothing to animate if the board already reads correctly.
    if (shown === target) return

    let frame = 0
    const from = shown.padEnd(target.length, ' ')
    const steps = 14

    const tick = () => {
      frame += 1
      const next = target
        .split('')
        .map((ch, i) => {
          // Each cell settles at a slightly different time, left to right, so the
          // board resolves in a wave rather than snapping as one block.
          const settleAt = steps * (0.35 + (i / target.length) * 0.65)
          if (frame >= settleAt) return ch
          const fromIdx = Math.max(0, GLYPHS.indexOf(from[i] ?? ' '))
          const toIdx = Math.max(0, GLYPHS.indexOf(ch))
          const span = (toIdx - fromIdx + GLYPHS.length) % GLYPHS.length || GLYPHS.length
          const progress = frame / settleAt
          return GLYPHS[(fromIdx + Math.floor(span * progress)) % GLYPHS.length]
        })
        .join('')
      setShown(next)
      if (frame < steps) timer.current = window.setTimeout(tick, 34)
    }
    timer.current = window.setTimeout(tick, 34)
    return () => window.clearTimeout(timer.current)
    // `shown` intentionally omitted: including it would restart the animation on
    // every intermediate frame it sets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, tier])

  return (
    <span className={`flap ${className}`} aria-label={value}>
      {shown.split('').map((ch, i) => (
        <span key={i} className="flap__cell" aria-hidden="true">
          {ch === ' ' ? ' ' : ch}
        </span>
      ))}
    </span>
  )
}
