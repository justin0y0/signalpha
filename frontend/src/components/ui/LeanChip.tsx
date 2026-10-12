import { useT } from '../../i18n'

/**
 * Direction lean for one report: which way the scorecard tilts, and how far from even.
 *
 * Deliberately quiet. The lean is an experiment whose backtest sits at coin-flip
 * accuracy, so it is drawn as a small tilt gauge rather than a verdict — a needle that
 * barely leaves centre is the honest picture of a 52% call.
 */
type Props = { p?: number | null; size?: 'sm' | 'md' }

export function LeanChip({ p, size = 'sm' }: Props) {
  const { t } = useT()
  if (p == null) return <span className="tertiary">—</span>
  const up = p >= 0.5
  const edge = Math.abs(p - 0.5)
  const even = edge < 0.015
  // needle travel: ±12% from even fills the gauge
  const x = 50 + Math.max(-1, Math.min(1, (p - 0.5) / 0.12)) * 50
  return (
    <span className={`lean lean--${size} ${even ? 'is-even' : up ? 'is-up' : 'is-down'}`} title={t('lean.tooltip', { p: (p * 100).toFixed(0) })}>
      <span className="lean__gauge"><i style={{ left: `${x}%` }} /></span>
      <span className="lean__txt">{even ? t('lean.even') : `${up ? '▲' : '▼'} ${((up ? p : 1 - p) * 100).toFixed(0)}%`}</span>
    </span>
  )
}
