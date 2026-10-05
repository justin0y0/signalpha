import { motion } from 'framer-motion'
import { Flame } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { BreakoutMetrics } from '../types'
import { pct } from '../hooks/useHeadline'
import { useT } from '../i18n'

/**
 * The model's one out-of-sample skill, shown as evidence rather than asserted.
 *
 * Ten bars: every out-of-sample report, sorted into deciles by predicted breakout risk,
 * with the share that actually moved more than that stock usually does. If the model
 * knew nothing the bars would be flat at the base-rate line. They climb at the right
 * end and are close to the line at the left — which is exactly the claim the site
 * makes: good at flagging breakouts, not at promising quiet ones.
 */
export function BreakoutPanel({ m }: { m: BreakoutMetrics }) {
  const { t } = useT()
  const data = m.deciles.map((d) => ({ name: `D${d.decile}`, rate: +(d.move_rate * 100).toFixed(1), n: d.n, p: d.mean_p }))
  return (
    <motion.div className="card breakout-panel" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12, duration: 0.3 }}>
      <h3 className="card-title">
        <Flame size={12} style={{ marginRight: 6, verticalAlign: 'middle', color: 'var(--accent-amber)' }} />
        {t('model.breakout.title')}
      </h3>
      <p className="breakout-panel__lede">{t('model.breakout.lede')}</p>

      <div className="baseline-panel__grid">
        <div className="baseline-panel__cell baseline-panel__cell--verdict is-good">
          <span>{t('model.breakout.top')}</span><b>{pct(m.top_decile.move_rate, 1)}</b>
        </div>
        <div className="baseline-panel__cell">
          <span>{t('model.breakout.base')}</span><b>{pct(m.base_rate, 1)}</b>
        </div>
        <div className="baseline-panel__cell">
          <span>{t('model.breakout.auc')}</span><b>{m.auc.toFixed(3)}</b>
        </div>
        <div className="baseline-panel__cell">
          <span>{t('model.breakout.n')}</span><b>{m.n.toLocaleString()}</b>
        </div>
      </div>

      <div style={{ height: 220, marginTop: '1rem' }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.08)" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis domain={[30, 80]} tickFormatter={(v) => `${v}%`} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              contentStyle={{ background: 'var(--bg-elevated, #0f172a)', border: '1px solid rgba(148,163,184,0.2)', borderRadius: 10, fontSize: 12 }}
              formatter={(v: number, _k, item) => [`${v}% moved more than usual · n=${item.payload.n}`, `mean P(move) ${(item.payload.p * 100).toFixed(0)}%`]}
            />
            <ReferenceLine y={+(m.base_rate * 100).toFixed(1)} stroke="rgba(226,232,240,0.45)" strokeDasharray="4 4"
              label={{ value: t('model.breakout.baseLine'), fill: 'var(--text-tertiary)', fontSize: 10, position: 'insideTopLeft' }} />
            <Bar dataKey="rate" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={d.name} fill={i === 9 ? 'var(--accent-amber)' : i === 8 ? 'var(--accent-purple)' : 'rgba(168,179,209,0.45)'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="baseline-panel__note">
        {t('model.breakout.note', {
          z: m.top_decile.z.toFixed(1),
          quiet: pct(m.bottom_decile.quiet_rate, 1),
          quietBase: pct(m.bottom_decile.quiet_base, 1),
          since: m.first_oos_date,
          features: m.features,
        })}
      </p>
    </motion.div>
  )
}
