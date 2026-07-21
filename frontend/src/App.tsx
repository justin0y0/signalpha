import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AboutPage } from './pages/AboutPage'
import { ContactPage } from './pages/ContactPage'
import { EarningsCalendarPage } from './pages/EarningsCalendarPage'
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
        <Route path="/backtest" element={<Navigate to="/strategy?view=backtest" replace />} />
        <Route path="/showdown" element={<Navigate to="/strategy?view=showdown" replace />} />
        <Route path="/simulator" element={<Navigate to="/strategy?view=paper" replace />} />
      </Route>
      <Route path="/admin" element={<AdminPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
