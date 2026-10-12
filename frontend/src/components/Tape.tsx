import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useUpcoming } from '../hooks/useUpcoming'
import { parseLocalDate } from '../utils/date'
import { useT } from '../i18n'

/**
 * The tape under the masthead: every tracked report in the next three weeks, with the
 * two calls the site makes — breakout risk before the print, follow-through after it.
 * It runs on every page so the product always looks like what it is: something that is
 * watching a calendar.
 */
type Live = { reports: { ticker: string; gap: number | null; gap_x: number | null; signal: string }[] }

export function Tape() {
  const { t } = useT()
  const upcoming = useUpcoming()
  const [live, setLive] = useState<Live | null>(null)
  useEffect(() => {
    fetch('/api/v1/playbook/live?days=6').then((r) => (r.ok ? r.json() : null)).then(setLive).catch(() => {})
  }, [])

  const items = useMemo(() => {
    const out: { key: string; to: string; node: JSX.Element }[] = []
    for (const r of live?.reports ?? []) {
      if (r.gap == null) continue
      out.push({
        key: `r${r.ticker}`, to: `/predict/${r.ticker}`,
        node: <>
          <b>{r.ticker}</b>
          <span className={r.gap >= 0 ? 'is-long' : ''} style={r.gap < 0 ? { color: 'var(--down)' } : undefined}>
            {r.gap >= 0 ? '▲' : '▼'} {(Math.abs(r.gap) * 100).toFixed(1)}%
          </span>
          <span>{r.signal === 'long' ? <em className="is-long" style={{ fontStyle: 'normal' }}>{t('tape.follow')}</em> : t('tape.reacted')}</span>
        </>,
      })
    }
    const horizon = Date.now() + 21 * 86400_000
    for (const e of upcoming) {
      const d = parseLocalDate(e.earnings_date)
      if (d.getTime() > horizon || e.prob_move == null) continue
      const cls = e.move_tier === 'breakout' ? 'is-hot' : e.move_tier === 'elevated' ? 'is-warm' : ''
      out.push({
        key: `u${e.ticker}${e.earnings_date}`, to: `/predict/${e.ticker}?earnings_date=${e.earnings_date}`,
        node: <>
          <b>{e.ticker}</b>
          <span>{d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}{e.report_time ? ` ${e.report_time}` : ''}</span>
          <span className={cls}>{cls === 'is-hot' ? '◆' : '◇'} {(e.prob_move * 100).toFixed(0)}%</span>
        </>,
      })
    }
    return out
  }, [upcoming, live, t])

  if (items.length < 4) return null
  const loop = [...items, ...items]
  return (
    <div className="tape" aria-label={t('tape.aria')}>
      <div className="tape__track" style={{ ['--tape-dur' as string]: `${Math.max(40, items.length * 3.2)}s` }}>
        {loop.map((it, i) => (
          <Link key={`${it.key}-${i}`} to={it.to} className="tape__item" tabIndex={i >= items.length ? -1 : 0} aria-hidden={i >= items.length}>
            {it.node}
          </Link>
        ))}
      </div>
    </div>
  )
}
