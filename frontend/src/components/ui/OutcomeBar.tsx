import { motion } from 'framer-motion'

/**
 * The model's full outcome distribution, replacing the single argmax label.
 *
 * After walk-forward calibration the probabilities converge to the base rate
 * (UP 25.8 / FLAT 52.5 / DOWN 21.7 against an actual 26.6 / 49.8 / 23.6) — which is
 * the correct behaviour for a model with no directional edge, but it makes argmax
 * degenerate: FLAT wins on 97.5% of events, so a "direction" label carries almost no
 * information. The distribution behind it still does. P(FLAT) has real spread
 * (quartiles 0.47 / 0.52 / 0.57, tails at 0 and 1) and is the one thing the model
 * demonstrably gets right: at P(FLAT) >= 0.60 it is correct 66.6% of the time against
 * a 49.8% base rate.
 *
 * So the headline number here is the quiet score, not a direction, and the bar shows
 * all three probabilities so the reader can see the tilt without it being asserted.
 * The directional tilt is deliberately NOT given a verdict: P(UP)-P(DOWN) quintiles
 * show no monotonic relationship to realised return (most-bullish quintile averages
 * +0.01%, most-bearish +0.51%).
 */

type Props = {
  up?: number | null
  flat?: number | null
  down?: number | null
  compact?: boolean
}

export function OutcomeBar({ up, flat, down, compact = false }: Props) {
  if (up == null || flat == null || down == null) {
    return <span className="tertiary">—</span>
  }
  const total = up + flat + down
  if (!(total > 0)) return <span className="tertiary">—</span>

  const pUp = up / total
  const pFlat = flat / total
  const pDown = down / total

  // Quiet score is P(FLAT): the higher it is, the more the model expects a non-event.
  const quiet = pFlat
  const tone = quiet >= 0.6 ? 'high' : quiet >= 0.5 ? 'mid' : 'low'
  const label = quiet >= 0.6 ? 'Likely quiet' : quiet >= 0.5 ? 'Leaning quiet' : 'Move expected'

  return (
    <div className={`outcome${compact ? ' outcome--compact' : ''}`}>
      <div className="outcome__head">
        <span className={`outcome__score outcome__score--${tone}`}>{(quiet * 100).toFixed(0)}%</span>
        <span className="outcome__label">{label}</span>
      </div>
      <div className="outcome__bar" title={`UP ${(pUp * 100).toFixed(0)}% · FLAT ${(pFlat * 100).toFixed(0)}% · DOWN ${(pDown * 100).toFixed(0)}%`}>
        <motion.span className="outcome__seg outcome__seg--down" initial={{ width: 0 }} animate={{ width: `${pDown * 100}%` }} transition={{ duration: 0.4 }} />
        <motion.span className="outcome__seg outcome__seg--flat" initial={{ width: 0 }} animate={{ width: `${pFlat * 100}%` }} transition={{ duration: 0.4, delay: 0.05 }} />
        <motion.span className="outcome__seg outcome__seg--up" initial={{ width: 0 }} animate={{ width: `${pUp * 100}%` }} transition={{ duration: 0.4, delay: 0.1 }} />
      </div>
      {!compact && (
        <div className="outcome__legend">
          <span><i className="outcome__dot outcome__dot--down" />{(pDown * 100).toFixed(0)}</span>
          <span><i className="outcome__dot outcome__dot--flat" />{(pFlat * 100).toFixed(0)}</span>
          <span><i className="outcome__dot outcome__dot--up" />{(pUp * 100).toFixed(0)}</span>
        </div>
      )}
    </div>
  )
}
