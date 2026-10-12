import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useT } from '../i18n'

/**
 * What the Arena has on file for this one report: each forecaster's sealed probability
 * and lean, and — once the report has traded — how it turned out. The dossier's link
 * into step 03 of the loop.
 */
type Call = { forecaster: string; p: number; lean: 'UP' | 'DOWN' | null; brier: number | null; lean_hit?: boolean | null }
type Ev = { ticker: string; earnings_date: string; band: number; actual_move: number | null; broke_out: boolean | null; calls: Call[] }
type Board = { forecasters: { code: string; name: string }[]; pending: Ev[]; resolved: Ev[] }

export function ArenaForReport({ ticker, date }: { ticker: string; date: string }) {
  const { t } = useT()
  const [b, setB] = useState<Board | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/v1/arena').then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive) setB(d) }).catch(() => {})
    return () => { alive = false }
  }, [])
  if (!b) return null
  const ev = [...b.pending, ...b.resolved].find((e) => e.ticker === ticker && e.earnings_date === date)
  const name = (c: string) => b.forecasters.find((f) => f.code === c)?.name ?? c
  return (
    <section className="card arena-mini">
      <div className="arena-mini__head">
        <h3 className="card-title">{t('dd.arena.title')}</h3>
        <Link to="/arena" className="arena-mini__go">{t('dd.arena.go')} <ArrowRight size={13} /></Link>
      </div>
      {!ev ? <p className="tertiary arena-mini__none">{t('dd.arena.none')}</p> : (
        <>
          <div className="arena-mini__grid">
            {[...ev.calls].sort((a, c) => c.p - a.p).map((c) => (
              <div key={c.forecaster} className="arena-mini__cell">
                <span>{name(c.forecaster)}</span>
                <b className="serif">{(c.p * 100).toFixed(0)}%</b>
                <i className={c.lean === 'UP' ? 'is-up' : c.lean === 'DOWN' ? 'is-down' : ''}>
                  {c.lean ? `${c.lean === 'UP' ? '▲' : '▼'} ${t(c.lean === 'UP' ? 'lean.up' : 'lean.down')}` : t('dd.arena.noLean')}
                  {c.lean_hit != null && <em>{c.lean_hit ? ' ✓' : ' ✗'}</em>}
                </i>
              </div>
            ))}
          </div>
          <p className="page-note">
            {ev.broke_out == null
              ? t('dd.arena.pending', { band: (ev.band * 100).toFixed(1) })
              : t('dd.arena.resolved', { move: `${(ev.actual_move ?? 0) >= 0 ? '+' : ''}${((ev.actual_move ?? 0) * 100).toFixed(2)}%`, band: (ev.band * 100).toFixed(1), result: ev.broke_out ? t('arena.graded.broke') : t('arena.graded.held') })}
          </p>
        </>
      )}
    </section>
  )
}
