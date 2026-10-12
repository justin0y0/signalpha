import { Link, useLocation } from 'react-router-dom'
import { JOURNEY, journeyIndex } from '../lib/journey'
import { useT } from '../i18n'

/**
 * Foot of every page in the earnings loop: where this page sits, and the next step.
 * After the last step it loops back to the calendar, because the next report is
 * already on it.
 */
export function JourneyRail() {
  const { t } = useT()
  const { pathname } = useLocation()
  const i = journeyIndex(pathname)
  if (i < 0) return null
  const prev = JOURNEY[(i + JOURNEY.length - 1) % JOURNEY.length]
  const next = JOURNEY[(i + 1) % JOURNEY.length]
  return (
    <nav className="journey" aria-label={t('journey.aria')}>
      <Link to={prev.to} className="journey__link">
        <small>← {prev.step} · {t(prev.phase as 'journey.before')}</small>
        <span>{t(prev.nav as 'nav.calendar')}</span>
      </Link>
      <div className="journey__steps">
        {JOURNEY.map((j, k) => (
          <span key={j.to} style={{ display: 'contents' }}>
            {k > 0 && <i className="journey__bar" />}
            <Link to={j.to} className={`journey__dot${k === i ? ' is-here' : ''}`} title={t(j.nav as 'nav.calendar')}>{k + 1}</Link>
          </span>
        ))}
      </div>
      <Link to={next.to} className="journey__link journey__link--next">
        <small>{i === JOURNEY.length - 1 ? t('journey.loop') : t('journey.next')} · {next.step} · {t(next.phase as 'journey.before')} →</small>
        <span>{t(next.nav as 'nav.calendar')}</span>
      </Link>
    </nav>
  )
}
