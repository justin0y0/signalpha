import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, Wallet } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import { useHeadline } from '../hooks/useHeadline'
import { PlaybookPage } from './PlaybookPage'
import { SimulatorPage } from './SimulatorPage'
import { useT } from '../i18n'

/**
 * 04 · Strategy — one rule, shown twice: the evidence and the live account trading it.
 *
 * This tab used to hold three harnesses (a direction backtest, a five-bot showdown and
 * a paper account) that all traded the model's pre-report direction call. On clean data
 * that call is a coin flip, so two of the three were elaborate views of nothing. What
 * replaced them is the Playbook — the post-report follow-through signal with a lab to
 * test any variation — and the paper account, which trades that same rule.
 *
 * Old ?view= values (backtest, showdown, simulator) still land somewhere sensible.
 */
export function StrategyPage() {
  const { t } = useT()
  const f = useHeadline()?.follow_through
  const ITEMS = [
    { key: 'playbook', label: t('strategy.tab.playbook'), icon: <BookOpen size={15} /> },
    { key: 'paper', label: t('strategy.tab.paper'), icon: <Wallet size={15} /> },
  ]
  const [params, setParams] = useSearchParams()
  const raw = params.get('view') ?? ''
  const [view, setView] = useState(raw === 'simulator' || raw === 'paper' ? 'paper' : 'playbook')

  const change = (key: string) => {
    setView(key)
    const next = new URLSearchParams(params)
    next.set('view', key)
    setParams(next, { replace: true })
  }

  return (
    <div className="page-stack">
      <PageHead
        kicker={t('nav.strategy')}
        title={<>{t('pb.h.a')} <em>{t('pb.h.b')}</em></>}
        lede={t('pb.lede')}
        spike={0.3}
      >
        <div className="figs">
          <div className="is-up"><b><Num value={f ? f.hit * 100 : null} format={(v) => `${v.toFixed(1)}%`} /></b><span>{t('pb.fig.rule', { k: f?.k ?? 2, hold: f?.hold ?? 20 })}</span></div>
          <div><b><Num value={f ? f.baseline_hit * 100 : null} format={(v) => `${v.toFixed(1)}%`} /></b><span>{t('pb.fig.base')}</span></div>
          <div className="is-signal"><b><Num value={f?.t} format={(v) => v.toFixed(1)} /></b><span>{t('pb.fig.t')}</span></div>
        </div>
      </PageHead>
      <SubNav items={ITEMS} active={view} onChange={change} />
      {view === 'playbook' ? <PlaybookPage /> : <SimulatorPage />}
    </div>
  )
}
