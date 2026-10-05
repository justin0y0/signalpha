import { useT } from '../../i18n'

/**
 * Breakout risk for one report: will it move the stock more than that stock usually
 * moves on earnings?
 *
 * This is the one question the model answers better than chance out of sample — its
 * top decile clears the stock's own band far more often than the base rate — so it
 * leads each row. The three-way direction split (Superposition) stays beside it as
 * context, because direction itself is near chance.
 *
 * The tick on the bar is the base rate: half of all reports clear their own band by
 * construction, so the useful reading is how far a row sits beyond that line, not the
 * raw percentage.
 */
type Props = {
  prob?: number | null
  tier?: 'breakout' | 'elevated' | 'normal' | null
  /** The stock's usual move — its median absolute earnings reaction. */
  band?: number | null
  baseRate?: number | null
  compact?: boolean
}

export function MoveRisk({ prob, tier, band, baseRate, compact = false }: Props) {
  const { t } = useT()
  if (prob == null) return <span className="tertiary">—</span>
  const level = tier ?? 'normal'
  const label = level === 'breakout' ? t('move.breakout') : level === 'elevated' ? t('move.elevated') : t('move.normal')
  return (
    <div
      className={`mrisk mrisk--${level}${compact ? ' mrisk--compact' : ''}`}
      title={t('move.tooltip', { p: (prob * 100).toFixed(0), band: band != null ? (band * 100).toFixed(1) : '—' })}
    >
      <div className="mrisk__head">
        <span className="mrisk__score">{(prob * 100).toFixed(0)}%</span>
        <span className="mrisk__label">{label}</span>
      </div>
      <div className="mrisk__track">
        <span className="mrisk__fill" style={{ width: `${Math.max(2, Math.min(100, prob * 100))}%` }} />
        {baseRate != null && <span className="mrisk__base" style={{ left: `${baseRate * 100}%` }} />}
      </div>
      {!compact && band != null && (
        <div className="mrisk__band">{t('move.usual', { band: (band * 100).toFixed(1) })}</div>
      )}
    </div>
  )
}
