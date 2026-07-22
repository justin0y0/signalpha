import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Gauge, ListChecks } from 'lucide-react'
import { SubNav } from '../components/ui/SubNav'
import { PerformanceTrackerPage } from './PerformanceTrackerPage'
import { TrackRecordPage } from './TrackRecordPage'
import { useT } from '../i18n'

/**
 * "Model" — everything about how good the model is, in one place.
 *
 * Performance and Track Record were separate top-level tabs that answered the same
 * question from two angles and duplicated roughly two thirds of their content (both
 * rendered a confusion matrix, an accuracy headline, a best-sector callout and a
 * sample count). Splitting one weak result across two tabs made the site look like it
 * had twice as much evidence as it does.
 *
 * The section is kept in the URL (?view=) so a link to either half still works.
 */


export function ModelPage() {
  const { t } = useT()
  const ITEMS = [
  { key: 'quality', label: t('model.tab.quality'), icon: <Gauge size={13} /> },
  { key: 'record', label: t('model.tab.record'), icon: <ListChecks size={13} /> },
  ]
  const [params, setParams] = useSearchParams()
  const initial = params.get('view') === 'record' ? 'record' : 'quality'
  const [view, setView] = useState(initial)

  const change = (key: string) => {
    setView(key)
    const next = new URLSearchParams(params)
    next.set('view', key)
    setParams(next, { replace: true })
  }

  return (
    <div>
      <SubNav items={ITEMS} active={view} onChange={change} />
      {view === 'quality' ? <PerformanceTrackerPage /> : <TrackRecordPage />}
    </div>
  )
}
