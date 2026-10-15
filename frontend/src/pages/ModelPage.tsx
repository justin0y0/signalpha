import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Gauge, ListChecks, Receipt } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import { useHeadline } from '../hooks/useHeadline'
import { PerformanceTrackerPage } from './PerformanceTrackerPage'
import { TrackRecordPage } from './TrackRecordPage'
import { ReceiptsPage } from './ReceiptsPage'
import { useT } from '../i18n'

/**
 * 05 · Model — the proof, including the parts that do not flatter.
 *
 * Last step of the loop: every claim made on the other pages, checked out of sample.
 * The three figures in the header are the three calls the site makes, each beside the
 * number it has to beat — breakout risk (works), follow-through (works), pre-report
 * direction (does not; shown anyway).
 */
export function ModelPage() {
  const { t } = useT()
  const h = useHeadline()
  const ITEMS = [
    { key: 'receipts', label: t('model.tab.receipts'), icon: <Receipt size={15} /> },
    { key: 'quality', label: t('model.tab.quality'), icon: <Gauge size={15} /> },
    { key: 'record', label: t('model.tab.record'), icon: <ListChecks size={15} /> },
  ]
  const [params, setParams] = useSearchParams()
  const v0 = params.get('view')
  const [view, setView] = useState(v0 === 'record' || v0 === 'quality' ? v0 : 'receipts')

  const change = (key: string) => {
    setView(key)
    const next = new URLSearchParams(params)
    next.set('view', key)
    setParams(next, { replace: true })
  }
  const pct1 = (v: number) => `${v.toFixed(1)}%`

  return (
    <div className="page-stack">
      <PageHead
        kicker={t('nav.model')}
        title={<>{t('model.h.a')} <em>{t('model.h.b')}</em></>}
        lede={t('model.h.lede', { features: h?.universe.features ?? '—', events: (h?.breakout?.n ?? h?.universe.scored_events)?.toLocaleString() ?? '—' })}
        spike={0.82}
      >
        <div className="figs">
          <div className="is-signal"><b><Num value={h?.breakout ? h.breakout.top_decile.move_rate * 100 : null} format={pct1} /></b><span>{t('model.fig.breakout', { base: h?.breakout ? (h.breakout.base_rate * 100).toFixed(0) : '—' })}</span></div>
          <div className="is-up"><b><Num value={h?.follow_through ? h.follow_through.hit * 100 : null} format={pct1} /></b><span>{t('model.fig.follow', { base: h?.follow_through ? (h.follow_through.baseline_hit * 100).toFixed(0) : '—' })}</span></div>
          <div><b><Num value={h?.lean ? h.lean.accuracy * 100 : null} format={pct1} /></b><span>{t('model.fig.lean', { base: h?.lean?.majority != null ? (h.lean.majority * 100).toFixed(1) : '50' })}</span></div>
        </div>
      </PageHead>
      <SubNav items={ITEMS} active={view} onChange={change} />
      {view === 'receipts' ? <ReceiptsPage /> : view === 'quality' ? <PerformanceTrackerPage /> : <TrackRecordPage />}
    </div>
  )
}
