import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useT } from '../i18n'

/**
 * What the three market rules Autopilot runs say about today's tape — the Markets desk's
 * own reading turned into a position: RSI-2 dip, 10-month trend, sector momentum. The
 * rules decide at 15:35 New York time; before the first decision the research snapshot
 * (as of the last backtest run) is shown instead.
 */
type Card = { key: string; family: string; backtest: { stats: { cagr: number | null; spy_cagr: number | null; max_dd: number | null; spy_max_dd?: number | null }; now?: Record<string, any> | null }
  live: { target?: { session: string; weights: Record<string, number>; why: string } | null } }

const pct = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`)

export function MarketRules() {
  const { t } = useT()
  const [cards, setCards] = useState<Card[]>([])
  useEffect(() => {
    fetch('/api/v1/autopilot/strategies').then((r) => (r.ok ? r.json() : null))
      .then((d) => setCards((d?.cards ?? []).filter((c: Card) => c.family === 'market'))).catch(() => setCards([]))
  }, [])
  if (!cards.length) return null
  const state = (c: Card): string => {
    const tg = c.live.target
    if (tg) return Object.entries(tg.weights).map(([k, w]) => (w >= 0.99 ? k : `${k} ${Math.round(w * 100)}%`)).join(' · ')
    const n = c.backtest.now ?? {}
    if (c.key === 'trend') return n.in_market ? 'SPY' : 'BIL'
    if (c.key === 'rsi2') return n.rsi2 != null ? `RSI(2) ${Number(n.rsi2).toFixed(0)}` : '—'
    if (c.key === 'sectors') return (n.holding ?? []).join(' · ')
    return '—'
  }
  return (
    <section className="mk-rules">
      <header>
        <h2>{t('mk.rules.h')}</h2>
        <Link to="/autopilot">{t('mk.rules.link')} →</Link>
      </header>
      <div className="mk-rules__grid">
        {cards.map((c) => (
          <div key={c.key}>
            <span className="mk-rules__k">{t(`ap.name.${c.key}` as 'ap.name.trend')}</span>
            <b>{state(c)}</b>
            <span className="mk-rules__why">{c.live.target?.why ?? t('mk.rules.snapshot')}</span>
            <span className="mk-rules__bt">{t('mk.rules.bt', { dd: pct(c.backtest.stats.max_dd), sdd: pct(c.backtest.stats.spy_max_dd ?? null), c: pct(c.backtest.stats.cagr, 1), s: pct(c.backtest.stats.spy_cagr, 1) })}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
