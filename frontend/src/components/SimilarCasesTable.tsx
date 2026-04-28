import type { SimilarCase } from '../types'

type Props = {
  items: SimilarCase[]
}

function formatPct(value?: number | null) {
  if (value == null) return '—'
  return `${(value * 100).toFixed(2)}%`
}

export function SimilarCasesTable({ items }: Props) {
  return (
    <div className="card table-card">
      <h3>Comparable setups</h3>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Date</th>
            <th>Similarity</th>
            <th>T+1</th>
            <th>T+5</th>
            <th>T+20</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={`${item.ticker}-${item.earnings_date}`}>
              <td>{item.ticker}</td>
              <td>{item.earnings_date}</td>
              <td>{(item.similarity * 100).toFixed(1)}%</td>
              <td>{formatPct(item.actual_t1_return)}</td>
              <td>{formatPct(item.actual_t5_return)}</td>
              <td>{formatPct(item.actual_t20_return)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
