import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useT } from '../i18n'
/** The last eight reactions, bars coloured by sign, dashed lines at ± the usual move. */
export function ReactionHistory({ history, band }: { history: { date: string; reaction: number }[]; band: number | null | undefined }) {
  const { t } = useT()
  if (!history.length) return null
  return (
    <section className="card">
      <h3 className="card-title">{t('dd.hist.title')}</h3>
      <div style={{ height: 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={history} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
            <CartesianGrid strokeDasharray="2 5" stroke="rgba(236, 226, 205, 0.08)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: 'var(--text-tertiary)', fontSize: 10, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: 'var(--text-tertiary)', fontSize: 10, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
            <ReferenceLine y={0} stroke="var(--text-tertiary)" />
            {band != null && <ReferenceLine y={band * 100} stroke="var(--text-muted)" strokeDasharray="4 4" />}
            {band != null && <ReferenceLine y={-band * 100} stroke="var(--text-muted)" strokeDasharray="4 4" />}
            <Tooltip cursor={{ fill: 'rgba(236, 226, 205, 0.05)' }}
              contentStyle={{ background: 'var(--bg-2)', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 12 }}
              formatter={(v: number) => [`${v > 0 ? '+' : ''}${v}%`, t('dd.hist.reaction')]} />
            <Bar dataKey="reaction" radius={[2, 2, 0, 0]} maxBarSize={46}>
              {history.map((h) => <Cell key={h.date} fill={h.reaction >= 0 ? 'var(--up)' : 'var(--down)'} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="page-note">{t('dd.hist.note')}</p>
    </section>
  )
}
