import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, FlaskConical, Radio } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useT } from '../i18n'
import { formatDateShort } from '../utils/date'
import './PlaybookPage.css'

/**
 * Playbook — the direction call, placed where the data supports one.
 *
 * Before a report, direction is a coin flip (AUC 0.50 on clean data). After it, one
 * pattern is solid: a stock that gaps UP by more than twice its usual earnings move
 * tends to keep rising, while a gap down does not keep falling. This page is that
 * finding as a tool: the reports that just triggered, and a lab where any gap rule can
 * be tested against every report on record.
 *
 * It replaces a direction backtest and a five-bot "showdown" that both traded the
 * pre-report direction call — two polished views of a signal that does not exist.
 */

type Stats = { n: number; mean: number | null; median: number | null; hit: number | null; t: number | null }
type TestResult = {
  rule: { side: string; k: number; action: string; entry: string; hold: number; surprise: string; cost_bps: number }
  stats: Stats; excess: Stats; verdict: 'edge' | 'weak' | 'none' | 'negative' | 'thin'
  baseline: { n: number; mean_long: number; hit_long: number }
  years: { year: number; n: number; mean: number; excess: number; hit: number }[]
  curve: { d: string; v: number }[]
  recent: { ticker: string; date: string; side: string; gap: number; band: number; gap_x: number; surprise: number | null; ret: number }[]
  span: { from: string; to: string }
  caveats: string[]
}
type GridCell = { side: 'up' | 'down'; k: number; n: number; mean: number | null; hit: number | null; excess: number | null; t: number | null; verdict: string }
type LiveReport = {
  ticker: string; company: string | null; reaction_date: string; report_time: string | null
  gap: number | null; band: number | null; gap_x: number | null; surprise: number | null
  day1_from_open: number | null; since_open_5d: number | null; signal: 'long' | 'watch' | 'gap_down' | 'none'
}
type Live = {
  signal: { k: number; hold: number; n: number; mean: number; hit: number; excess: number; t: number; baseline_mean: number; baseline_hit: number; mean_5d: number; hit_5d: number; t_5d: number; years_positive: number; years_total: number; span: { from: string; to: string } }
  reports: LiveReport[]; triggered: string[]
}

const p1 = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`)
const pc = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

function Seg<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: { v: T; l: string; off?: boolean }[]; onChange: (v: T) => void
}) {
  return (
    <div className="pb-seg">
      <span className="pb-seg__label">{label}</span>
      <div className="pb-seg__opts" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={String(o.v)} type="button" disabled={o.off}
            className={o.v === value ? 'is-on' : ''} onClick={() => onChange(o.v)}>{o.l}</button>
        ))}
      </div>
    </div>
  )
}

export function PlaybookPage() {
  const { t } = useT()
  const [live, setLive] = useState<Live | null>(null)
  const [grid, setGrid] = useState<GridCell[]>([])
  const [res, setRes] = useState<TestResult | null>(null)
  const [busy, setBusy] = useState(false)

  const [side, setSide] = useState<'up' | 'down' | 'either'>('up')
  const [k, setK] = useState(2)
  const [action, setAction] = useState<'follow' | 'fade'>('follow')
  const [entry, setEntry] = useState<'open' | 'close'>('close')
  const [hold, setHold] = useState(20)
  const [surprise, setSurprise] = useState<'any' | 'beat' | 'miss'>('any')

  useEffect(() => {
    fetch('/api/v1/playbook/live').then((r) => (r.ok ? r.json() : null)).then(setLive).catch(() => {})
  }, [])

  useEffect(() => {
    const h = entry === 'close' && hold === 0 ? 5 : hold
    if (h !== hold) { setHold(h); return }
    let alive = true
    setBusy(true)
    const q = new URLSearchParams({ side, k: String(k), action, entry, hold: String(h), surprise })
    fetch(`/api/v1/playbook/test?${q}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && !d.error) setRes(d) })
      .catch(() => {})
      .finally(() => { if (alive) setBusy(false) })
    fetch(`/api/v1/playbook/grid?entry=${entry}&hold=${h}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d?.cells) setGrid(d.cells) })
      .catch(() => {})
    return () => { alive = false }
  }, [side, k, action, entry, hold, surprise])

  const sig = live?.signal
  const years = useMemo(() => (res?.years ?? []).map((y) => ({ ...y, pct: +(y.excess * 100).toFixed(2) })), [res])
  const curve = useMemo(() => (res?.curve ?? []).map((c) => ({ d: c.d, v: +(c.v * 100).toFixed(1) })), [res])
  const holdLabel = (h: number) => (h === 0 ? t('pb.hold.day') : t('pb.hold.n', { n: h }))

  return (
    <div className="pb">
      {/* ── finding ── */}
      <motion.section className="pb-hero" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <div className="pb-hero__kicker">{t('pb.kicker')}</div>
        <h1 className="pb-hero__title">{t('pb.title')}</h1>
        <p className="pb-hero__lede">{t('pb.lede')}</p>
        {sig && (
          <div className="pb-hero__cells">
            <div className="is-up">
              <span>{t('pb.cell.rule', { k: sig.k, hold: sig.hold })}</span>
              <b>{pc(sig.hit, 1)}</b>
              <i>{t('pb.cell.up5', { mean: p1(sig.mean, 2), n: sig.n })}</i>
            </div>
            <div>
              <span>{t('pb.cell.base', { hold: sig.hold })}</span>
              <b>{pc(sig.baseline_hit, 1)}</b>
              <i>{t('pb.cell.baseMean', { mean: p1(sig.baseline_mean, 2) })}</i>
            </div>
            <div>
              <span>{t('pb.cell.t')}</span>
              <b>{sig.t?.toFixed(1)}</b>
              <i>{t('pb.cell.years', { a: sig.years_positive, b: sig.years_total })}</i>
            </div>
            <div>
              <span>{t('pb.cell.short')}</span>
              <b>{pc(sig.hit_5d, 1)}</b>
              <i>{t('pb.cell.shortNote', { t: sig.t_5d?.toFixed(1) })}</i>
            </div>
          </div>
        )}
        <p className="pb-hero__fine">{t('pb.fine')}</p>
      </motion.section>

      {/* ── just reacted ── */}
      <section className="card pb-live">
        <h3 className="card-title"><Radio size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />{t('pb.live.title')}</h3>
        {!live ? <div className="shimmer" style={{ height: 120 }} /> : live.reports.length === 0 ? (
          <p className="tertiary">{t('pb.live.empty')}</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table pb-live__table">
              <thead>
                <tr>
                  <th>{t('col.ticker')}</th><th>{t('pb.col.reacted')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.gap')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.vsUsual')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.eps')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.since')}</th>
                  <th>{t('pb.col.call')}</th>
                </tr>
              </thead>
              <tbody>
                {live.reports.map((r) => (
                  <tr key={`${r.ticker}${r.reaction_date}`} className={r.signal === 'long' ? 'is-hot' : ''}>
                    <td><Link to={`/predict/${r.ticker}`} className="pb-tk">{r.ticker}</Link></td>
                    <td className="mono small">{formatDateShort(r.reaction_date)}{r.report_time ? ` · ${r.report_time}` : ''}</td>
                    <td className={`mono r ${r.gap != null && r.gap >= 0 ? 'pb-up' : 'pb-dn'}`}>{p1(r.gap)}</td>
                    <td className="mono r">{r.gap_x != null ? `${Math.abs(r.gap_x).toFixed(1)}×` : '—'}</td>
                    <td className="mono r">{r.surprise != null ? p1(r.surprise / 100) : '—'}</td>
                    <td className={`mono r ${(r.since_open_5d ?? r.day1_from_open ?? 0) >= 0 ? 'pb-up' : 'pb-dn'}`}>
                      {p1(r.since_open_5d ?? r.day1_from_open)}
                      <span className="tertiary"> {r.since_open_5d != null ? '5d' : '1d'}</span>
                    </td>
                    <td><span className={`pb-call pb-call--${r.signal}`}>
                      {r.signal === 'long' && <ArrowUpRight size={11} />}{t(`pb.call.${r.signal}` as 'pb.call.long')}
                    </span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="pb-note">{t('pb.live.note')}</p>
      </section>

      {/* ── lab ── */}
      <section className="card pb-lab">
        <h3 className="card-title"><FlaskConical size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />{t('pb.lab.title')}</h3>
        <p className="pb-lab__lede">{t('pb.lab.lede')}</p>

        <div className="pb-controls">
          <Seg label={t('pb.c.side')} value={side} onChange={setSide}
            options={[{ v: 'up', l: t('pb.c.up') }, { v: 'down', l: t('pb.c.down') }, { v: 'either', l: t('pb.c.either') }]} />
          <Seg label={t('pb.c.size')} value={k} onChange={setK}
            options={[0.5, 1, 1.5, 2, 3].map((v) => ({ v, l: `${v}×` }))} />
          <Seg label={t('pb.c.action')} value={action} onChange={setAction}
            options={[{ v: 'follow', l: t('pb.c.follow') }, { v: 'fade', l: t('pb.c.fade') }]} />
          <Seg label={t('pb.c.entry')} value={entry} onChange={setEntry}
            options={[{ v: 'open', l: t('pb.c.open') }, { v: 'close', l: t('pb.c.close') }]} />
          <Seg label={t('pb.c.hold')} value={hold} onChange={setHold}
            options={[{ v: 0, l: holdLabel(0), off: entry === 'close' }, { v: 5, l: holdLabel(5) }, { v: 20, l: holdLabel(20) }]} />
          <Seg label={t('pb.c.eps')} value={surprise} onChange={setSurprise}
            options={[{ v: 'any', l: t('pb.c.any') }, { v: 'beat', l: t('pb.c.beat') }, { v: 'miss', l: t('pb.c.miss') }]} />
        </div>

        {res && (
          <div className={`pb-result${busy ? ' is-busy' : ''}`}>
            <div className={`pb-verdict pb-verdict--${res.verdict}`}>
              <b>{t(`pb.verdict.${res.verdict}` as 'pb.verdict.edge')}</b>
              <span>{t(`pb.verdict.${res.verdict}.d` as 'pb.verdict.edge.d', {
                excess: p1(res.excess.mean, 2), t: res.excess.t?.toFixed(1) ?? '—', n: res.stats.n,
              })}</span>
            </div>
            <div className="pb-stats">
              <div><span>{t('pb.s.trades')}</span><b>{res.stats.n.toLocaleString()}</b><i>{res.span.from.slice(0, 4)}–{res.span.to.slice(0, 4)}</i></div>
              <div><span>{t('pb.s.hit')}</span><b>{pc(res.stats.hit, 1)}</b><i>{t('pb.s.vsAll', { v: pc(res.rule.action === 'follow' && res.rule.side !== 'down' ? res.baseline.hit_long : 1 - res.baseline.hit_long, 1) })}</i></div>
              <div><span>{t('pb.s.avg')}</span><b className={(res.stats.mean ?? 0) >= 0 ? 'pb-up' : 'pb-dn'}>{p1(res.stats.mean, 2)}</b><i>{t('pb.s.afterCost', { bps: res.rule.cost_bps })}</i></div>
              <div><span>{t('pb.s.excess')}</span><b className={(res.excess.mean ?? 0) >= 0 ? 'pb-up' : 'pb-dn'}>{p1(res.excess.mean, 2)}</b><i>t = {res.excess.t?.toFixed(2) ?? '—'}</i></div>
            </div>

            <div className="pb-charts">
              <div>
                <div className="pb-chart__title">{t('pb.chart.years')}</div>
                <div style={{ height: 190 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={years} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.08)" vertical={false} />
                      <XAxis dataKey="year" tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis tickFormatter={(v) => `${v}%`} tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <ReferenceLine y={0} stroke="rgba(226,232,240,0.35)" />
                      <Tooltip cursor={{ fill: 'rgba(148,163,184,0.06)' }}
                        contentStyle={{ background: 'var(--bg-2)', border: '1px solid var(--border-strong)', borderRadius: 10, fontSize: 12 }}
                        formatter={(v: number, _k, item) => [`${v}% · n=${item.payload.n} · ${(item.payload.hit * 100).toFixed(0)}% hit`, t('pb.s.excess')]} />
                      <Bar dataKey="pct" radius={[3, 3, 0, 0]}>
                        {years.map((y) => <Cell key={y.year} fill={y.pct >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'} fillOpacity={y.n < 10 ? 0.35 : 0.85} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div>
                <div className="pb-chart__title">{t('pb.chart.curve')}</div>
                <div style={{ height: 190 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={curve} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
                      <defs>
                        <linearGradient id="pbfill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--accent-cyan)" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="var(--accent-cyan)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.08)" vertical={false} />
                      <XAxis dataKey="d" tickFormatter={(d) => String(d).slice(0, 4)} minTickGap={40} tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis tickFormatter={(v) => `${v}%`} tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <ReferenceLine y={0} stroke="rgba(226,232,240,0.35)" />
                      <Tooltip contentStyle={{ background: 'var(--bg-2)', border: '1px solid var(--border-strong)', borderRadius: 10, fontSize: 12 }}
                        formatter={(v: number) => [`${v}%`, t('pb.chart.curveTip')]} />
                      <Area type="monotone" dataKey="v" stroke="var(--accent-cyan)" strokeWidth={1.6} fill="url(#pbfill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* where the edge lives */}
        {grid.length > 0 && (
          <div className="pb-grid">
            <div className="pb-chart__title">{t('pb.grid.title', { hold: holdLabel(hold) })}</div>
            <div className="pb-grid__table">
              <span />
              {[0.5, 1, 1.5, 2, 3].map((v) => <span key={v} className="pb-grid__h">{t('pb.grid.col', { k: v })}</span>)}
              {(['up', 'down'] as const).map((s) => (
                <div key={s} style={{ display: 'contents' }}>
                  <span className="pb-grid__r">{s === 'up' ? t('pb.grid.up') : t('pb.grid.down')}</span>
                  {grid.filter((c) => c.side === s).map((c) => {
                    const on = side === s && k === c.k && action === 'follow'
                    const tone = c.verdict === 'edge' ? 'edge' : c.verdict === 'weak' ? 'weak' : c.verdict === 'negative' ? 'neg' : 'none'
                    return (
                      <button key={c.k} type="button" className={`pb-cell pb-cell--${tone}${on ? ' is-on' : ''}`}
                        onClick={() => { setSide(s); setK(c.k); setAction('follow') }}
                        title={`n=${c.n} · t=${c.t?.toFixed(1)}`}>
                        <b>{p1(c.excess, 2)}</b>
                        <i>{pc(c.hit)} · n={c.n}</i>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
            <p className="pb-note">{t('pb.grid.note')}</p>
          </div>
        )}

        {res && res.recent.length > 0 && (
          <details className="pb-recent">
            <summary>{t('pb.recent', { n: res.recent.length })}</summary>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>{t('col.ticker')}</th><th>{t('col.date')}</th><th>{t('col.side')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.gap')}</th><th style={{ textAlign: 'right' }}>{t('pb.col.vsUsual')}</th>
                  <th style={{ textAlign: 'right' }}>{t('pb.col.eps')}</th><th style={{ textAlign: 'right' }}>{t('pb.col.result')}</th></tr></thead>
                <tbody>
                  {res.recent.map((r) => (
                    <tr key={`${r.ticker}${r.date}`}>
                      <td className="mono">{r.ticker}</td><td className="mono small">{r.date}</td><td className="small">{r.side}</td>
                      <td className="mono r">{p1(r.gap)}</td><td className="mono r">{Math.abs(r.gap_x).toFixed(1)}×</td>
                      <td className="mono r">{r.surprise != null ? p1(r.surprise / 100) : '—'}</td>
                      <td className={`mono r ${r.ret >= 0 ? 'pb-up' : 'pb-dn'}`}>{p1(r.ret, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        <ul className="pb-caveats">
          <li>{t('pb.caveat.surv')}</li>
          <li>{t('pb.caveat.cost')}</li>
          <li>{t('pb.caveat.mining')}</li>
        </ul>
      </section>
    </div>
  )
}
