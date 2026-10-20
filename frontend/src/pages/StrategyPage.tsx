import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, Compass, Wallet } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import { useDirection } from '../hooks/useDirection'
import type { Book } from './DirectionBookPage'
import { PlaybookPage } from './PlaybookPage'
import { DirectionBookPage } from './DirectionBookPage'
import { AutopilotDesk } from './AutopilotPage'
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
 * The third tab was an in-house simulated account; it is now Autopilot, which trades the
 * same rules in a real (paper or live) Alpaca account — the full page is /autopilot.
 *
 * Old ?view= values (backtest, showdown, simulator) still land somewhere sensible.
 */
export function StrategyPage() {
  const { t } = useT()
  const book = useDirection<Book>().data
  const rules = book ? Object.values(book.rules) : []
  const best = rules.reduce<{ p: number; s: string } | null>((b, r) => (!b || r.years_positive / r.years_total > b.p ? { p: r.years_positive / r.years_total, s: `${r.years_positive}/${r.years_total}` } : b), null)
  const trades = rules.reduce((n, r) => n + r.all.n, 0)
  const ITEMS = [
    { key: 'book', label: t('strategy.tab.book'), icon: <Compass size={15} /> },
    { key: 'playbook', label: t('strategy.tab.playbook'), icon: <BookOpen size={15} /> },
    { key: 'paper', label: t('strategy.tab.autopilot'), icon: <Wallet size={15} /> },
  ]
  const [params, setParams] = useSearchParams()
  const raw = params.get('view') ?? ''
  const [view, setView] = useState(raw === 'simulator' || raw === 'paper' ? 'paper' : raw === 'playbook' || raw === 'backtest' || raw === 'showdown' ? 'playbook' : 'book')

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
        title={<>{t('db.h.a')} <em>{t('db.h.b')}</em></>}
        lede={t('db.h.lede')}
        spike={0.3}
      >
        <div className="figs">
          <div className="is-signal"><b><Num value={rules.length || null} /></b><span>{t('db.fig.rules')}</span></div>
          <div className="is-up"><b>{best?.s ?? '—'}</b><span>{t('db.fig.years')}</span></div>
          <div><b><Num value={trades || null} /></b><span>{t('db.fig.trades')}</span></div>
        </div>
      </PageHead>
      <SubNav items={ITEMS} active={view} onChange={change} />
      {view === 'book' ? <DirectionBookPage /> : view === 'playbook' ? <PlaybookPage /> : <AutopilotDesk />}
    </div>
  )
}
