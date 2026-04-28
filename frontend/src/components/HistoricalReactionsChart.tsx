import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { HistoricalReaction } from '../types'

type Props = {
  items: HistoricalReaction[]
}

export function HistoricalReactionsChart({ items }: Props) {
  const data = [...items]
    .sort((a, b) => a.earnings_date.localeCompare(b.earnings_date))
    .map((item) => ({
      label: item.earnings_date.slice(2, 10),
      reaction: item.reaction_pct ?? 0,
    }))

  return (
    <div className="card chart-card">
      <h3>Last 8 quarters</h3>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" />
          <YAxis tickFormatter={(value) => `${(value * 100).toFixed(0)}%`} />
          <Tooltip formatter={(value: number) => `${(value * 100).toFixed(2)}%`} />
          <Bar dataKey="reaction">
            {data.map((entry, index) => (
              <Cell key={`${entry.label}-${index}`} fillOpacity={entry.reaction >= 0 ? 0.75 : 0.35} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
