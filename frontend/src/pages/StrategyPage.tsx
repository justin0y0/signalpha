import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, Wallet } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { PlaybookPage } from './PlaybookPage'
import { SimulatorPage } from './SimulatorPage'
import { useT } from '../i18n'

/**
 * "Strategy" — one rule, shown twice: the evidence and the live account trading it.
 *
 * This tab used to hold three harnesses (a direction backtest, a five-bot showdown and
 * a paper account) that all traded the model's pre-report direction call. On clean data
 * that call is a coin flip, so two of the three were elaborate views of nothing. What
 * replaced them is the Playbook — the post-report follow-through signal with a lab to
 * test any variation — and the paper account, which now trades that same rule.
 *
 * Old ?view= values (backtest, showdown, simulator) still land somewhere sensible.
 */
export function StrategyPage() {
  const { t } = useT()
  const ITEMS = [
    { key: 'playbook', label: t('strategy.tab.playbook'), icon: <BookOpen size={13} /> },
    { key: 'paper', label: t('strategy.tab.paper'), icon: <Wallet size={13} /> },
  ]
  const [params, setParams] = useSearchParams()
  const raw = params.get('view') ?? ''
  const requested = raw === 'simulator' || raw === 'paper' ? 'paper' : 'playbook'
  const [view, setView] = useState(requested)

  const change = (key: string) => {
    setView(key)
    const next = new URLSearchParams(params)
    next.set('view', key)
    setParams(next, { replace: true })
  }

  return (
    <div>
      <SubNav items={ITEMS} active={view} onChange={change} />
      {view === 'playbook' ? <PlaybookPage /> : <SimulatorPage />}
    </div>
  )
}
