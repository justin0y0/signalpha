import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { JOURNEY, journeyIndex } from '../lib/journey'
import { useT } from '../i18n'

/**
 * The one page header. Every page opens the same way: where you are in the loop, a
 * statement in the serif voice, one paragraph, and an optional aside for the numbers
 * that matter. The amber trace along the rule is the site's signature — a quiet line
 * with one spike, the shape of an earnings reaction.
 *
 * `title` may contain <em> for the single phrase that carries the page.
 */
type Props = { kicker?: string; title: ReactNode; lede?: ReactNode; children?: ReactNode; spike?: number }

export function PageHead({ kicker, title, lede, children, spike = 0.62 }: Props) {
  const { t } = useT()
  const { pathname } = useLocation()
  const i = journeyIndex(pathname)
  const step = i >= 0 ? JOURNEY[i] : null
  const x = Math.round(spike * 1000)
  // flat line, one reaction spike, a smaller echo, flat again
  const d = `M0 20 H${x - 34} l6 -3 l5 6 l7 -22 l8 30 l6 -15 l6 7 l8 -3 H1000`
  return (
    <header className="phead">
      <div>
        <div className="phead__kicker">
          {step && <span className="phead__idx">{step.step}</span>}
          <span>{step ? t(step.phase as 'journey.before') : kicker}</span>
          {step && kicker && <span>· {kicker}</span>}
        </div>
        <h1 className="phead__title">{title}</h1>
        {lede && <p className="phead__lede">{lede}</p>}
      </div>
      {children && <div className="phead__aside">{children}</div>}
      <svg className="phead__trace" viewBox="0 0 1000 26" preserveAspectRatio="none" aria-hidden="true">
        <path d={d} pathLength={1} />
      </svg>
    </header>
  )
}
