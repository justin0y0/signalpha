import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Clock, Moon, Star, Zap } from 'lucide-react'
import { StatCard } from '../components/ui/StatCard'
import { OutcomeBar } from '../components/ui/OutcomeBar'
import { SplitFlap } from '../components/ui/SplitFlap'
import { formatDateShort } from '../utils/date'
import { useT } from '../i18n'

/**
 * Alpha Brief — the daily surface.
 *
 * Deliberately organised around quiet-vs-loud rather than up-vs-down. The model has
 * no directional edge (59.8% 3-class against a 60.6% always-FLAT baseline; it commits
 * to a direction on 2.5% of events and gets 53.5% of those right on n=71), but it
 * identifies non-events at 76.4% against a 60.7% base rate on n=1,058. Leading with a
 * direction call would be selling a capability the data says does not exist.
 */

type Row = {
  ticker: string; company_name: string | null; sector: string | null
  earnings_date: string; report_time: string | null
  p_flat: number | null; p_up: number | null; p_down: number | null
  expected_move_pct: number | null
  atm_iv: number | null; iv_rank: number | null; iv_crush_hist: number | null
}
type Brief = {
  as_of: string; horizon_days: number; personalised: boolean; watchlist_size: number
  counts: { total: number; quiet: number; loud: number; unscored: number }
  quiet: Row[]; loud: Row[]
  methodology: Record<string, unknown>
}

function Section({ title, icon, rows, tone }: { title: string; icon: React.ReactNode; rows: Row[]; tone: 'quiet' | 'loud' }) {
  const { t } = useT()
  if (!rows.length) return null
  return (
    <motion.div className="card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <h3 className="card-title">{icon}<span style={{ marginLeft: 6 }}>{title}</span>
        <span className="brief-count">{rows.length}</span>
      </h3>
      <table className="data-table brief-table">
        <thead>
          <tr>
            <th>{t('col.ticker')}</th><th>{t('col.company')}</th><th>{t('col.date')}</th>
            <th>{t('brief.quietDist')}</th>
            <th style={{ textAlign: 'right' }}>{t('col.expMove')}</th>
            <th style={{ textAlign: 'right' }}>{t('brief.col.iv')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.ticker}-${r.earnings_date}`}>
              <td><SplitFlap value={r.ticker} width={5} className="brief-flap" /></td>
              <td className="muted" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.company_name ?? '—'}
              </td>
              <td className="mono small">{formatDateShort(r.earnings_date)}{r.report_time ? ` · ${r.report_time}` : ''}</td>
              <td><OutcomeBar compact up={r.p_up} flat={r.p_flat} down={r.p_down} /></td>
              <td className="mono r">{r.expected_move_pct != null ? `±${(r.expected_move_pct * 100).toFixed(2)}%` : '—'}</td>
              <td className="mono r">{r.atm_iv != null ? `${(r.atm_iv * 100).toFixed(0)}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {tone === 'quiet' && (
        <p className="brief-note">{t('brief.note')}</p>
      )}
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="hero-headline">{t('brief.title')}</h1>
        <p className="hero-sub">
          {t('brief.sub', { days: data.horizon_days })}
          {data.personalised
            ? ` Personalised to your ${data.watchlist_size}-ticker watchlist.`
            : t('brief.signIn')}
        </p>
      </motion.div>

      <div className="grid grid-4">
        <StatCard label={t('brief.stat.ahead')} icon={<Clock size={12} />} value={data.counts.total} helper={`next ${data.horizon_days} days`} accent="cyan" delay={0.05} />
        <StatCard label={t('brief.stat.quiet')} icon={<Moon size={12} />} value={data.counts.quiet} helper="P(flat) ≥ 60%" accent="purple" delay={0.1} />
        <StatCard label={t('brief.stat.loud')} icon={<Zap size={12} />} value={data.counts.loud} helper="P(flat) ≤ 40%" accent="amber" delay={0.15} />
        <StatCard label={t('brief.stat.watchlist')} icon={<Star size={12} />} value={data.watchlist_size} helper={data.personalised ? 'personalised' : 'not signed in'} accent="emerald" delay={0.2} />
      </div>

      <Section title={t('brief.section.quiet')} icon={<Moon size={13} />} rows={data.quiet} tone="quiet" />
      <Section title={t('brief.section.loud')} icon={<Zap size={13} />} rows={data.loud} tone="loud" />

      {data.counts.total === 0 && <div className="empty-state">{t('brief.empty')}</div>}
    </div>
  )
}
