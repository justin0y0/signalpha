import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, ReferenceLine, CartesianGrid,
} from 'recharts'
import { useT } from '../i18n'

const API = '/api/v1/track-record'

type Summary = {
  total: number; hit_rate: number; avg_actual_move_pct: number
  baseline: number; baseline_class: string
  best_sector: { name: string; hit_rate: number; n: number } | null
  by_confidence: Record<string, { n: number; hits: number; hit_rate: number }>
  by_sector: { name: string; n: number; hits: number; hit_rate: number }[]
}
type Confusion = { classes: string[]; matrix: Record<string, Record<string, number>>; total: number }
type CalibPt = { confidence_bin: number; n: number; predicted_rate: number; actual_rate: number }
type RollingPt = { date: string; accuracy: number; n: number }
type ConfBreakRow = { min_confidence: number; label: string; n: number; hit_rate: number }
type RecentItem = {
  ticker: string; earnings_date: string; sector: string
  predicted: string; predicted_prob: number; confidence: number
  expected_move_pct: number; actual_class: string; actual_t1_return: number
  actual_t5_return: number | null; hit: boolean
}

const CYAN = '#38bdf8'
const PURPLE = '#a78bfa'
const GREEN = '#4ade80'
const RED = '#f87171'
const AMBER = '#fbbf24'

const fmt = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`
const fmtRet = (v: number) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`

function KpiCard({ label, value, sub, accent = CYAN }:
  { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <motion.div className="tr-kpi" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
      style={{ borderTop: `2px solid ${accent}` }}>
      <div className="tr-kpi__label">{label}</div>
      <div className="tr-kpi__value" style={{ color: accent }}>{value}</div>
      {sub && <div className="tr-kpi__sub">{sub}</div>}
    </motion.div>
  )
}

function ConfusionMatrix({ data }: { data: Confusion }) {
  const { t } = useT()
  const { classes, matrix, total } = data
  const maxVal = Math.max(...classes.flatMap(p => classes.map(a => matrix[p]?.[a] ?? 0)))
  return (
    <div className="tr-card">
      <div className="tr-card__title">{t('tr.confusion.title')} <span className="tr-card__sub">{t('tr.confusion.sub')}</span></div>
      <div className="tr-confusion">
        <div className="tr-confusion__corner" />
        {classes.map(a => (
          <div key={a} className="tr-confusion__header">{a}</div>
        ))}
        {classes.map(pred => (
          <>
            <div key={`row-${pred}`} className="tr-confusion__row-label">{pred}</div>
            {classes.map(actual => {
              const val = matrix[pred]?.[actual] ?? 0
              const isHit = pred === actual
              const intensity = maxVal > 0 ? val / maxVal : 0
              const bg = isHit
                ? `rgba(56,189,248,${0.1 + intensity * 0.55})`
                : `rgba(248,113,113,${intensity * 0.35})`
              return (
                <div key={`${pred}-${actual}`} className="tr-confusion__cell" style={{ background: bg }}>
                  <span className="tr-confusion__n">{val.toLocaleString()}</span>
                  <span className="tr-confusion__pct">{total > 0 ? fmt(val / total) : '—'}</span>
                </div>
              )
            })}
          </>
        ))}
      </div>
    </div>
  )
}

function CalibrationChart({ data }: { data: CalibPt[] }) {
  const { t } = useT()
  const pts = data.map(d => ({ ...d, confidence_bin: +(d.confidence_bin * 100).toFixed(0) }))
  return (
    <div className="tr-card">
      <div className="tr-card__title">
        {t('tr.calib.title')}
        <span className="tr-card__sub">{t('tr.calib.sub')}</span>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="confidence_bin" type="number" domain={[30, 100]}
            tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={v => `${v}%`}
            label={{ value: t('tr.calib.xaxis'), fill: '#64748b', fontSize: 11, position: 'insideBottom', offset: -4 }} />
          <YAxis dataKey="actual_rate" type="number" domain={[0.3, 1]}
            tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={v => `${(v * 100).toFixed(0)}%`} />
          <ReferenceLine stroke="rgba(255,255,255,0.2)"
            segment={[{ x: 30, y: 0.3 }, { x: 100, y: 1.0 }]}
            strokeDasharray="6 3" label={{ value: t('tr.calib.perfect'), fill: '#64748b', fontSize: 10, position: 'insideTopRight' }} />
          <Tooltip
            cursor={{ strokeDasharray: '3 3' }}
            content={({ payload }) => {
              if (!payload?.length) return null
              const d = payload[0].payload as CalibPt & { confidence_bin: number }
              return (
                <div className="tr-tooltip">
                  <div>{t('tr.calib.confidence')}: <b>{d.confidence_bin}%</b></div>
                  <div>{t('tr.calib.actualRate')}: <b style={{ color: CYAN }}>{fmt(d.actual_rate)}</b></div>
                  <div>{t('tr.calib.sample')}: <b>{d.n}</b></div>
                </div>
              )
            }}
          />
          <Scatter data={pts} dataKey="actual_rate" fill={CYAN}
            shape={(props: any) => {
              const { cx, cy } = props
              return <circle cx={cx} cy={cy} r={6} fill={CYAN} fillOpacity={0.85} stroke="#0d1829" strokeWidth={1.5} />
            }} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function RollingChart({ data, baseline }: { data: RollingPt[]; baseline: number }) {
  const { t } = useT()
  const pts = data.map(d => ({ ...d, pct: +(d.accuracy * 100).toFixed(1) }))
  return (
    <div className="tr-card">
      <div className="tr-card__title">{t('tr.rolling.title')} <span className="tr-card__sub">{t('tr.rolling.sub')}</span></div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={pts} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={v => v.slice(0, 7)} interval="preserveStartEnd" />
          <YAxis domain={[30, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickFormatter={v => `${v}%`} />
          <ReferenceLine y={33.3} stroke="rgba(248,113,113,0.4)" strokeDasharray="4 3"
            label={{ value: t('tr.rolling.random'), fill: '#f87171', fontSize: 10, position: 'right' }} />
          <ReferenceLine y={+(baseline * 100).toFixed(1)} stroke="rgba(251,191,36,0.55)" strokeDasharray="4 3"
            label={{ value: `${t('tr.rolling.flatOnly')} ${(baseline * 100).toFixed(1)}%`, fill: '#fbbf24', fontSize: 10, position: 'right' }} />
          <Tooltip
            content={({ payload, label }) => {
              if (!payload?.length) return null
              const d = payload[0].payload as RollingPt & { pct: number }
              return (
                <div className="tr-tooltip">
                  <div>{label}</div>
                  <div>{t('tr.rolling.accuracy')}: <b style={{ color: CYAN }}>{d.pct}%</b></div>
                  <div>{t('tr.rolling.sampleN')}: <b>{d.n} {t('tr.rolling.events')}</b></div>
                </div>
              )
            }}
          />
          <Line type="monotone" dataKey="pct" stroke={CYAN} strokeWidth={2}
            dot={false} activeDot={{ r: 4, fill: CYAN }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

const DIR_COLOR = { UP: GREEN, FLAT: AMBER, DOWN: RED }
const DIR_ICON = { UP: '↑', FLAT: '—', DOWN: '↓' }

function RecentTable({ items, total, onFilter, verdict, setVerdict, minConf, setMinConf }:
  { items: RecentItem[]; total: number; onFilter: (v: string) => void; verdict: string; setVerdict: (v: string) => void; minConf: number; setMinConf: (v: number) => void }) {
  const { t } = useT()
  return (
    <div className="tr-card tr-card--full">
      <div className="tr-card__header">
        <div className="tr-card__title">{t('tr.table.title')} <span className="tr-card__sub">{t('tr.table.sub', { n: total.toLocaleString() })}</span></div>
        <div className="tr-filters">
          <div className="tr-conf-filter">
            <span>{t('tr.table.minConf')}</span>
            <select value={minConf} onChange={e => setMinConf(+e.target.value)} className="tr-conf-select">
              {[0, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85].map(v => (
                <option key={v} value={v}>{v === 0 ? t('tr.table.all') : `≥${(v*100).toFixed(0)}%`}</option>
              ))}
            </select>
          </div>
          {(['all', 'hit', 'miss'] as const).map(v => (
            <button key={v} className={`tr-filter-btn ${verdict === v ? 'tr-filter-btn--active' : ''}`}
              onClick={() => { setVerdict(v); onFilter(v) }}>
              {v === 'all' ? t('tr.table.all') : v === 'hit' ? `✓ ${t('tr.table.hits')}` : `✗ ${t('tr.table.misses')}`}
            </button>
          ))}
        </div>
      </div>
      <div className="tr-table-wrap">
        <table className="tr-table">
          <thead>
            <tr>
              <th>{t('tr.th.date')}</th><th>{t('tr.th.ticker')}</th><th>{t('tr.th.sector')}</th>
              <th>{t('tr.th.predicted')}</th><th>{t('tr.th.confidence')}</th>
              <th>{t('tr.th.actual')}</th><th>{t('tr.th.t1')}</th><th>{t('tr.th.t5')}</th>
              <th>{t('tr.th.verdict')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r, i) => (
              <tr key={i} className={r.hit ? 'tr-row--hit' : 'tr-row--miss'}>
                <td className="mono">{r.earnings_date}</td>
                <td><span className="tr-ticker">{r.ticker}</span></td>
                <td className="tr-sector">{r.sector}</td>
                <td>
                  <div className="tr-pred-cell">
                    <span className="tr-dir" style={{ color: DIR_COLOR[r.predicted as keyof typeof DIR_COLOR] || CYAN }}>
                      {DIR_ICON[r.predicted as keyof typeof DIR_ICON]} {r.predicted}
                    </span>
                    <span className="tr-prob">{fmt(r.predicted_prob)}</span>
                  </div>
                </td>
                <td>
                  <div className="tr-conf-bar">
                    <div className="tr-conf-bar__fill"
                      style={{ width: `${r.confidence * 100}%`, background: r.confidence >= 0.75 ? CYAN : r.confidence >= 0.6 ? PURPLE : '#64748b' }} />
                    <span>{fmt(r.confidence)}</span>
                  </div>
                </td>
                <td>
                  <span className="tr-dir" style={{ color: DIR_COLOR[r.actual_class as keyof typeof DIR_COLOR] || '#94a3b8' }}>
                    {DIR_ICON[r.actual_class as keyof typeof DIR_ICON]} {r.actual_class}
                  </span>
                </td>
                <td className="mono" style={{ color: r.actual_t1_return >= 0 ? GREEN : RED }}>
                  {fmtRet(r.actual_t1_return)}
                </td>
                <td className="mono" style={{ color: r.actual_t5_return == null ? '#64748b' : r.actual_t5_return >= 0 ? GREEN : RED }}>
                  {r.actual_t5_return != null ? fmtRet(r.actual_t5_return) : '—'}
                </td>
                <td>
                  <span className={`tr-verdict ${r.hit ? 'tr-verdict--hit' : 'tr-verdict--miss'}`}>
                    {r.hit ? `✓ ${t('tr.verdict.hit')}` : `✗ ${t('tr.verdict.miss')}`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function TrackRecordPage() {
  const { t } = useT()
  const [summary, setSummary] = useState<Summary | null>(null)
  const [confusion, setConfusion] = useState<Confusion | null>(null)
  const [calib, setCalib] = useState<CalibPt[]>([])
  const [rolling, setRolling] = useState<RollingPt[]>([])
  const [confBreak, setConfBreak] = useState<ConfBreakRow[]>([])
  const [recent, setRecent] = useState<RecentItem[]>([])
  const [totalFiltered, setTotalFiltered] = useState(0)
  const [verdict, setVerdict] = useState('all')
  const [minConf, setMinConf] = useState(0)
  const [loading, setLoading] = useState(true)

  const fetchRecent = useCallback(async (v: string, conf: number = 0) => {
    const r = await fetch(`${API}/recent?limit=100&verdict=${v}&min_confidence=${conf}`)
    if (!r.ok) { setRecent([]); setTotalFiltered(0); return }
    const d = await r.json()
    setRecent(d.items || [])
    setTotalFiltered(d.total_filtered || 0)
  }, [])

  useEffect(() => {
    Promise.all([
      fetch(`${API}/summary`).then(r => r.ok ? r.json() : null).then(setSummary),
      fetch(`${API}/confusion`).then(r => r.ok ? r.json() : null).then(setConfusion),
      fetch(`${API}/calibration`).then(r => r.ok ? r.json() : null).then(d => setCalib(d?.points || [])),
      fetch(`${API}/rolling`).then(r => r.ok ? r.json() : null).then(d => setRolling(d?.points || [])),
      fetch(`${API}/confidence-breakdown`).then(r => r.ok ? r.json() : null).then(d => setConfBreak(d?.rows || [])),
      fetchRecent('all'),
    ]).finally(() => setLoading(false))
  }, [fetchRecent])

  if (loading) return (
    <div className="tr-loading">
      <div className="tr-loading__spinner" />
      <div>{t('tr.loading')}</div>
    </div>
  )

  if (!summary || typeof summary.total !== 'number') return (
    <div className="tr-page">
      <div className="tr-hero">
        <h1 className="tr-hero__title">{t('tr.title')}</h1>
        <p className="tr-hero__sub">{t('tr.empty')}</p>
      </div>
    </div>
  )

  return (
    <div className="tr-page">
      <div className="tr-hero">
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
          <h1 className="tr-hero__title">{t('tr.title')}</h1>
          <p className="tr-hero__sub">{t('tr.hero.sub', { n: summary?.total.toLocaleString() ?? '' })}</p>
        </motion.div>
      </div>

      {summary && (
        <div className="tr-kpi-strip">
          <KpiCard label={t('tr.kpi.total')} value={summary.total.toLocaleString()} sub={t('tr.kpi.totalSub')} accent={CYAN} />
          <KpiCard label={t('tr.kpi.hitRate')} value={fmt(summary.hit_rate)}
            sub={t('tr.kpi.hitRateSub', { b: fmt(summary.baseline ?? 0) })}
            accent={summary.hit_rate > (summary.baseline ?? 0) ? GREEN : AMBER} />
          <KpiCard label={t('tr.kpi.highConf')} value={fmt(summary.by_confidence.HIGH?.hit_rate ?? 0)} sub={t('tr.kpi.highConfSub', { n: summary.by_confidence.HIGH?.n.toLocaleString() ?? '0' })} accent={CYAN} />
          <KpiCard label={t('tr.kpi.avgMove')} value={`±${summary.avg_actual_move_pct}%`} sub={t('tr.kpi.avgMoveSub')} accent={PURPLE} />
          {summary.best_sector && (
            <KpiCard label={t('tr.kpi.bestSector')} value={summary.best_sector.name.replace(' Services','').replace(' Cyclical','').replace(' Defensive','')} 
              sub={`${fmt(summary.best_sector.hit_rate)} · ${summary.best_sector.n} events`} accent={GREEN} />
          )}
        </div>
      )}

      <div className="tr-grid-2">
        {confusion && <ConfusionMatrix data={confusion} />}
        {calib.length > 0 && <CalibrationChart data={calib} />}
      </div>

      {rolling.length > 0 && <RollingChart data={rolling} baseline={summary?.baseline ?? 0} />}

      {summary && (
        <div className="tr-card">
          <div className="tr-card__title">{t('tr.bySector')}</div>
          <div className="tr-sector-bars">
            {summary.by_sector.map(s => (
              <div key={s.name} className="tr-sector-row">
                <div className="tr-sector-row__name">{s.name}</div>
                <div className="tr-sector-row__bar-wrap">
                  <div className="tr-sector-row__bar"
                    style={{ width: `${s.hit_rate * 100}%`, background: s.hit_rate > 0.7 ? CYAN : s.hit_rate > 0.5 ? PURPLE : '#64748b' }} />
                </div>
                <div className="tr-sector-row__stat mono">{fmt(s.hit_rate)} <span className="tr-sector-row__n">({s.n})</span></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {confBreak.length > 0 && (
        <div className="tr-card">
          <div className="tr-card__title">
            {t('tr.confbreak.title')}
            <span className="tr-card__sub">{t('tr.confbreak.sub')}</span>
          </div>
          <div className="tr-confbreak">
            {confBreak.map(r => (
              <div key={r.label} className="tr-confbreak__row">
                <div className="tr-confbreak__label">{r.label}</div>
                <div className="tr-confbreak__bar-wrap">
                  <div className="tr-confbreak__bar" style={{
                    width: `${r.hit_rate * 100}%`,
                    background: r.hit_rate >= 0.85 ? '#4ade80' : r.hit_rate >= 0.75 ? '#38bdf8' : r.hit_rate >= 0.6 ? '#a78bfa' : '#64748b'
                  }} />
                  <div className="tr-confbreak__baseline" style={{ left: '33.3%' }} />
                  <div className="tr-confbreak__baseline tr-confbreak__baseline--amber"
                    style={{ left: `${(summary?.baseline ?? 0.5) * 100}%` }} />
                </div>
                <div className="tr-confbreak__stat">
                  <span className="tr-confbreak__pct" style={{
                    color: r.hit_rate >= 0.85 ? '#4ade80' : r.hit_rate >= 0.75 ? '#38bdf8' : '#a78bfa'
                  }}>{(r.hit_rate * 100).toFixed(1)}%</span>
                  <span className="tr-confbreak__n">n={r.n.toLocaleString()}</span>
                </div>
              </div>
            ))}
            <div className="tr-confbreak__note">{t('tr.confbreak.note')}</div>
          </div>
        </div>
      )}

      <RecentTable items={recent} total={totalFiltered}
        onFilter={(v) => fetchRecent(v, minConf)} verdict={verdict} setVerdict={setVerdict}
        minConf={minConf} setMinConf={(c) => { setMinConf(c); fetchRecent(verdict, c) }} />
    </div>
  )
}
