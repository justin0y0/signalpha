import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AboutPage } from './pages/AboutPage'
import { ContactPage } from './pages/ContactPage'
import { EarningsCalendarPage } from './pages/EarningsCalendarPage'
import { BriefPage } from './pages/BriefPage'
import { ArenaPage } from './pages/ArenaPage'
import { PricingPage } from './pages/PricingPage'
import { ModelPage } from './pages/ModelPage'
import { StrategyPage } from './pages/StrategyPage'
import { OraclePage } from './pages/OraclePage'
import { PulsePage } from './pages/PulsePage'
import { PredictionDeepDivePage } from './pages/PredictionDeepDivePage'
import { AdminPage } from './pages/AdminPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<EarningsCalendarPage />} />
        <Route path="/brief" element={<BriefPage />} />
        <Route path="/arena" element={<ArenaPage />} />
        <Route path="/pro" element={<PricingPage />} />
        <Route path="/pricing" element={<Navigate to="/pro" replace />} />
        <Route path="/predict/:ticker" element={<PredictionDeepDivePage />} />
        <Route path="/model" element={<ModelPage />} />
        <Route path="/strategy" element={<StrategyPage />} />
        <Route path="/pulse" element={<PulsePage />} />
        <Route path="/oracle" element={<OraclePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/contact" element={<ContactPage />} />

        {/* Old top-level tabs, now sections. Redirects keep existing links and any
            bookmarks working after the eleven-tab nav was collapsed to seven. */}
        <Route path="/performance" element={<Navigate to="/model?view=quality" replace />} />
        <Route path="/track-record" element={<Navigate to="/model?view=record" replace />} />
        <Route path="/backtest" element={<Navigate to="/strategy?view=playbook" replace />} />
        <Route path="/showdown" element={<Navigate to="/strategy?view=playbook" replace />} />
        <Route path="/simulator" element={<Navigate to="/strategy?view=paper" replace />} />
      </Route>
      <Route path="/admin" element={<AdminPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
