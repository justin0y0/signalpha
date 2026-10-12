import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import type { LeanFactor, LeanMetrics } from '../types'
import { useT } from '../i18n'

/**
 * Direction lean, shown as a tug of war.
 *
 * Each factor pulls the rope toward UP or DOWN by its weight; the marker is where they
 * leave it. Factors that could be backtested are solid. The ones that could not — no
 * point-in-time history of analyst revisions or option skew exists — are hatched and
 * say so. Under it all sits the number that keeps this honest: the scorecard's
 * walk-forward accuracy, which is a coin flip.
 */
type Props = { p: number | null | undefined; factors: LeanFactor[]; metrics?: LeanMetrics | null }

export function LeanCard({ p, factors, metrics }: Props) {
  const { t } = useT()
  if (p == null) return (
    <div className="card leancard"><h3 className="card-title">{t('lean.title')}</h3><p className="tertiary">{t('lean.none')}</p></div>
  )
  const up = p >= 0.5
  const even = Math.abs(p - 0.5) < 0.015
  const max = Math.max(0.06, ...factors.map((f) => Math.abs(f.contrib)))
  const x = 50 + Math.max(-1, Math.min(1, (p - 0.5) / 0.12)) * 50
  return (
    <div className="card leancard">
      <div className="leancard__head">
        <h3 className="card-title">{t('lean.title')}</h3>
        <span className="tag tag--exp">{t('lean.exp')}</span>
      </div>
      <div className="leancard__call">
        <b className={`serif ${even ? '' : up ? 'is-up' : 'is-down'}`}>{even ? t('lean.callEven') : up ? t('lean.callUp') : t('lean.callDown')}</b>
        <span>{t('lean.pUp', { p: (p * 100).toFixed(1) })}</span>
      </div>

      <div className="rope" aria-hidden="true">
        <span className="rope__end">{t('lean.down')}</span>
        <div className="rope__line">
          <i className="rope__mid" />
          <motion.i className={`rope__knot ${even ? '' : up ? 'is-up' : 'is-down'}`} initial={{ left: '50%' }} animate={{ left: `${x}%` }}
            transition={{ type: 'spring', stiffness: 70, damping: 12, delay: 0.3 }} />
        </div>
        <span className="rope__end">{t('lean.up')}</span>
      </div>

      <ul className="pulls">
        {factors.map((f, i) => {
          const w = (Math.abs(f.contrib) / max) * 50
          const dir = f.contrib > 0.0005 ? 'up' : f.contrib < -0.0005 ? 'down' : 'none'
          return (
            <li key={f.key} className={`pull is-${dir}${f.proven ? '' : ' is-unproven'}${f.value == null ? ' is-missing' : ''}`}>
              <span className="pull__name">{t(`lean.f.${f.key}` as 'lean.f.reversion')}{!f.proven && <em>{t('lean.unproven')}</em>}</span>
              <span className="pull__bar">
                <motion.i initial={{ width: 0 }} animate={{ width: `${w}%` }} transition={{ duration: 0.6, delay: 0.35 + i * 0.04, ease: [0.2, 0.7, 0.2, 1] }}
                  style={dir === 'down' ? { right: '50%' } : { left: '50%' }} />
              </span>
              <span className="pull__val">{f.value == null ? t('lean.noData') : dir === 'none' ? '·' : dir === 'up' ? '▲' : '▼'}</span>
            </li>
          )
        })}
      </ul>

      <p className="leancard__truth">
        {metrics
          ? t('lean.truth', { acc: (metrics.accuracy * 100).toFixed(1), n: metrics.n.toLocaleString() })
          : t('lean.truthNone')}{' '}
        <Link to="/arena">{t('lean.truthLink')}</Link>
      </p>
    </div>
  )
}
