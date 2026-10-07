import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Swords } from 'lucide-react'
import { useT } from '../i18n'

/**
 * One line linking Calendar and Brief to the Earnings Arena when calls are open.
 *
 * The Arena is where the breakout model's claim is tested in public, so the pages that
 * show breakout risk point at it — but only when there is something live to look at.
 */
type Pending = { ticker: string; calls: { forecaster: string }[] }

export function ArenaTeaser() {
  const { t } = useT()
  const [pending, setPending] = useState<Pending[] | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/v1/arena')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d) setPending(d.pending ?? []) })
      .catch(() => {})
    return () => { alive = false }
  }, [])
  if (!pending || pending.length === 0) return null
  const tickers = pending.slice(0, 4).map((p) => p.ticker).join(' · ')
  const calls = pending.reduce((s, p) => s + p.calls.length, 0)
  return (
    <Link to="/arena" className="arena-teaser">
      <Swords size={13} />
      <span>{t('arena.teaser', { n: pending.length, calls, tickers })}</span>
      <ArrowRight size={13} className="arena-teaser__arrow" />
    </Link>
  )
}
