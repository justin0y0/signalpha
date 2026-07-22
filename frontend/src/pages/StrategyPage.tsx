import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FlaskConical, Swords, Wallet } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { BandTimeline } from '../components/BandTimeline'
import { api } from '../api/client'
import type { CalendarEvent } from '../types'
import { BacktestingPage } from './BacktestingPage'
import { ShowdownPage } from './ShowdownPage'
import { SimulatorPage } from './SimulatorPage'
import { useT } from '../i18n'

/**
 * "Strategy" — the three ways the same ML signal gets turned into trades.
 *
 * Backtest, Showdown and Simulator were three top-level tabs running one signal
 * through three harnesses: an interactive parameter sweep, five preset personas, and a
 * $1M paper account. They belong together — Showdown is Backtest with fixed presets,
 * and the Simulator is the same thing again with a live clock.
 *
 * The section is kept in the URL (?view=) so old links keep working.
 */



export function StrategyPage() {
  const { t } = useT()
  const ITEMS = [
  { key: 'backtest', label: t('strategy.tab.backtest'), icon: <FlaskConical size={13} /> },
  { key: 'showdown', label: t('strategy.tab.showdown'), icon: <Swords size={13} /> },
  { key: 'paper', label: t('strategy.tab.paper'), icon: <Wallet size={13} /> },
  ]
  const [params, setParams] = useSearchParams()
  const requested = params.get('view') ?? ''
  const [view, setView] = useState(['backtest','showdown','paper'].includes(requested) ? requested : 'backtest')

  const change = (key: string) => {
    setView(key)
    const next = new URLSearchParams(params)
    next.set('view', key)
    setParams(next, { replace: true })
  }

  // The band timeline sits above every strategy view: whatever harness you are
  // looking at, it is scoring against these per-stock bands.
  const [events, setEvents] = useState<CalendarEvent[]>([])
  useEffect(() => {
    const q = new URLSearchParams({ days_forward: '90', days_back: '0' })
    api.getCalendar(q).then((r) => setEvents(r.items)).catch(() => setEvents([]))
  }, [])

  return (
    <div>
      <SubNav items={ITEMS} active={view} onChange={change} />
      <BandTimeline events={events} />
      {view === 'backtest' && <BacktestingPage />}
      {view === 'showdown' && <ShowdownPage />}
      {view === 'paper' && <SimulatorPage />}
    </div>
  )
}
