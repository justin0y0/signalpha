import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useT } from '../i18n'

/**
 * Two dispatches from the rest of the loop, on the pages that come before them:
 * what the Arena has sealed, and what the follow-through rule is doing. They are the
 * hand-off from "what is coming" to "what was called" and "what to do after".
 */
type Arena = { pending: { ticker: string; calls: unknown[] }[]; totals: { calls: number; graded: number } }
type Live = { signal: { k: number; hold: number; hit: number; mean: number; baseline_hit: number; n: number } | null; triggered: string[] }

export function WireStrip() {
  const { t } = useT()
  const [arena, setArena] = useState<Arena | null>(null)
  const [live, setLive] = useState<Live | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/v1/arena').then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive) setArena(d) }).catch(() => {})
    fetch('/api/v1/playbook/live').then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive) setLive(d) }).catch(() => {})
    return () => { alive = false }
  }, [])
  const s = live?.signal
  return (
    <div className="wire">
      <Link to="/arena" className="wire__item">
        <span className="eyebrow"><i className="wire__n">03</i>{t('wire.arena.k')}</span>
        <p className="serif">
          {arena && arena.pending.length > 0
            ? t('wire.arena.live', { n: arena.pending.length, calls: arena.totals.calls, tickers: arena.pending.slice(0, 4).map((p) => p.ticker).join(', ') })
            : t('wire.arena.idle')}
        </p>
        <span className="wire__go">{t('wire.arena.go')} <ArrowRight size={13} /></span>
      </Link>
      <Link to="/strategy" className="wire__item">
        <span className="eyebrow"><i className="wire__n">04</i>{t('wire.play.k')}</span>
        <p className="serif">
          {s ? t('wire.play.stat', { k: s.k, hold: s.hold, hit: `${(s.hit * 100).toFixed(0)}%`, base: `${(s.baseline_hit * 100).toFixed(0)}%` }) : '…'}
          {live && (live.triggered.length > 0
            ? <em> {t('wire.play.now', { tickers: live.triggered.slice(0, 4).join(', ') })}</em>
            : <span className="tertiary"> {t('wire.play.none')}</span>)}
        </p>
        <span className="wire__go">{t('wire.play.go')} <ArrowRight size={13} /></span>
      </Link>
    </div>
  )
}
