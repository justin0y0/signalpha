import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, TrendingUp } from 'lucide-react'
import { useT } from '../i18n'

/**
 * One line pointing at the Playbook: the post-report direction signal and who just
 * triggered it. This is the only direction call the site makes, so the pages people
 * land on say it up front.
 */
type Live = { signal: { k: number; hold: number; hit: number; mean: number; baseline_hit: number } | null; triggered: string[] }

export function FollowThroughTeaser() {
  const { t } = useT()
  const [d, setD] = useState<Live | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/v1/playbook/live').then((r) => (r.ok ? r.json() : null)).then((j) => { if (alive) setD(j) }).catch(() => {})
    return () => { alive = false }
  }, [])
  if (!d?.signal) return null
  const s = d.signal
  const vars = { k: s.k, hold: s.hold, hit: `${(s.hit * 100).toFixed(0)}%`, mean: `+${(s.mean * 100).toFixed(1)}%`, base: `${(s.baseline_hit * 100).toFixed(0)}%` }
  return (
    <Link to="/strategy?view=playbook" className="arena-teaser ft-teaser">
      <TrendingUp size={13} />
      <span>
        {t('ft.teaser', vars)}{' '}
        {d.triggered.length > 0
          ? <b>{t('ft.teaser.now', { tickers: d.triggered.slice(0, 5).join(' · ') })}</b>
          : t('ft.teaser.none')}
      </span>
      <ArrowRight size={13} className="arena-teaser__arrow" />
    </Link>
  )
}
