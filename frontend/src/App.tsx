import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AboutPage } from './pages/AboutPage'
import { BacktestingPage } from './pages/BacktestingPage'
import { SimulatorPage } from './pages/SimulatorPage'
import { ContactPage } from './pages/ContactPage'
import { EarningsCalendarPage } from './pages/EarningsCalendarPage'
import { PerformanceTrackerPage } from './pages/PerformanceTrackerPage'
import { OraclePage } from './pages/OraclePage'
import { TrackRecordPage } from './pages/TrackRecordPage'
import { ShowdownPage } from './pages/ShowdownPage'
import { PulsePage } from './pages/PulsePage'
import { PredictionDeepDivePage } from './pages/PredictionDeepDivePage'
import { AdminPage } from './pages/AdminPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<EarningsCalendarPage />} />
        <Route path="/predict/:ticker" element={<PredictionDeepDivePage />} />
        <Route path="/backtest" element={<BacktestingPage />} />
        <Route path="/performance" element={<PerformanceTrackerPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/oracle" element={<OraclePage />} />
        <Route path="/track-record" element={<TrackRecordPage />} />
        <Route path="/showdown" element={<ShowdownPage />} />
        <Route path="/pulse" element={<PulsePage />} />
        <Route path="/contact" element={<ContactPage />} />
      </Route>
      <Route path="/admin" element={<AdminPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
