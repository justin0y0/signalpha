import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, Clock, Flame, Star } from 'lucide-react'
import { StatCard } from '../components/ui/StatCard'
import { OutcomeBar } from '../components/ui/OutcomeBar'
import { SplitFlap } from '../components/ui/SplitFlap'
import { MoveRisk } from '../components/ui/MoveRisk'
import { ArenaTeaser } from '../components/ArenaTeaser'
import { formatDateShort } from '../utils/date'
import { pct } from '../hooks/useHeadline'
import { useT } from '../i18n'

/**
 * Alpha Brief — the daily surface, ranked by breakout risk.
 *
 * Organised around one question: which reports this week will move their stock more
 * than it usually moves? That is the only call the model makes better than chance out
 * of sample (top decile vs base rate, see /model). "Will it be quiet" and "which way"
 * are both near chance on point-in-time features, so direction is shown as context and
 * no list claims to find non-events.
 *
 * The skill sentence under the breakout list comes from the API's live metrics, never
 * from copy — this page spent two label revisions quoting numbers for models that no
 * longer existed.
 */

type Row = {
  ticker: string; company_name: string | null; sector: string | null
  earnings_date: string; report_time: string | null
  prob_move: number | null; move_tier: 'breakout' | 'elevated' | 'normal' | null
  own_band: number | null; implied_move_pct: number | null
  p_flat: number | null; p_up: number | null; p_down: number | null
  expected_move_pct: number | null
  atm_iv: number | null
}
type Metrics = {
  auc: number; base_rate: number; n: number
  top_decile: { n: number; move_rate: number; z: number }
} | null
type Brief = {
  as_of: string; horizon_days: number; personalised: boolean; watchlist_size: number
  counts: { total: number; breakout: number; elevated: number; normal: number; unscored: number }
  breakout: Row[]; elevated: Row[]; normal: Row[]
  metrics: Metrics
}

function Section({ title, icon, rows, metrics, note }: {
  title: string; icon: React.ReactNode; rows: Row[]; metrics: Metrics; note?: string
}) {
  const { t } = useT()
  if (!rows.length) return null
  return (
    <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <h3 className="card-title">{icon}<span style={{ marginLeft: 6 }}>{title}</span>
        <span className="brief-count">{rows.length}</span>
      </h3>
      <div className="table-scroll">
        <table className="data-table brief-table">
          <thead>
            <tr>
              <th>{t('col.ticker')}</th><th>{t('col.company')}</th><th>{t('col.date')}</th>
              <th>{t('cal.col.moveRisk')}</th>
              <th style={{ textAlign: 'right' }}>{t('brief.col.usual')}</th>
              <th style={{ textAlign: 'right' }}>{t('brief.col.implied')}</th>
              <th>{t('cal.col.forecast')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.ticker}-${r.earnings_date}`}>
                <td><SplitFlap value={r.ticker} width={5} className="brief-flap" /></td>
                <td className="muted brief-company">{r.company_name ?? '—'}</td>
                <td className="mono small">{formatDateShort(r.earnings_date)}{r.report_time ? ` · ${r.report_time}` : ''}</td>
                <td><MoveRisk compact prob={r.prob_move} tier={r.move_tier} baseRate={metrics?.base_rate} /></td>
                <td className="mono r">{r.own_band != null ? `±${(r.own_band * 100).toFixed(1)}%` : '—'}</td>
                <td className="mono r">{r.implied_move_pct != null ? `±${(r.implied_move_pct * 100).toFixed(1)}%` : '—'}</td>
                <td className="cal-direction"><OutcomeBar compact up={r.p_up} flat={r.p_flat} down={r.p_down} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note && <p className="brief-note">{note}</p>}
    </motion.div>
  )
}

export function BriefPage() {
  const { t } = useT()
  const [data, setData] = useState<Brief | null>(null)
  const [error, setError] = useState<string | null>(null)
  const email = typeof localStorage !== 'undefined' ? localStorage.getItem('sa_email') : null

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ horizon_days: '7' })
      if (email) qs.set('email', email)
      const r = await fetch(`/api/v1/brief?${qs.toString()}`)
      if (!r.ok) throw new Error(await r.text())
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load brief')
    }
  }, [email])

  useEffect(() => { load() }, [load])

  if (error) return <div className="empty-state">{error}</div>
  if (!data) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="shimmer" style={{ height: 120 }} />
      <div className="shimmer" style={{ height: 300 }} />
    </div>
  )

  const m = data.metrics
  const skill = m
    ? t('brief.skill', { rate: pct(m.top_decile.move_rate), base: pct(m.base_rate), n: m.top_decile.n.toLocaleString() })
    : undefined

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <h1 className="hero-headline">{t('brief.title')}</h1>
        <p className="hero-sub">
          {t('brief.sub', { days: data.horizon_days })}
          {data.personalised ? ` ${t('brief.personalised', { n: data.watchlist_size })}` : t('brief.signIn')}
        </p>
      </motion.div>

      <ArenaTeaser />

      <div className="grid grid-4">
        <StatCard label={t('brief.stat.ahead')} icon={<Clock size={12} />} value={data.counts.total}
          helper={t('brief.stat.ahead.helper', { days: data.horizon_days })} accent="cyan" delay={0.05} />
        <StatCard label={t('move.breakout')} icon={<Flame size={12} />} value={data.counts.breakout}
          helper={t('brief.stat.breakout.helper')} accent="amber" delay={0.1} />
        <StatCard label={t('move.elevated')} icon={<Activity size={12} />} value={data.counts.elevated}
          helper={t('brief.stat.elevated.helper')} accent="purple" delay={0.15} />
        <StatCard label={t('brief.stat.watchlist')} icon={<Star size={12} />} value={data.watchlist_size}
          helper={data.personalised ? t('brief.stat.watch.on') : t('brief.stat.watch.off')} accent="emerald" delay={0.2} />
      </div>

      <Section title={t('brief.section.breakout')} icon={<Flame size={13} />} rows={data.breakout} metrics={m} note={skill} />
      <Section title={t('brief.section.elevated')} icon={<Activity size={13} />} rows={data.elevated} metrics={m} />
      <Section title={t('brief.section.normal')} icon={<Clock size={13} />} rows={data.normal} metrics={m}
        note={t('brief.normal.note')} />

      {data.counts.total === 0 && <div className="empty-state">{t('brief.empty')}</div>}
    </div>
  )
}
