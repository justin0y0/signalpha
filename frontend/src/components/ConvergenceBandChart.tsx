import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type Props = {
  lower?: number | null
  upper?: number | null
  currentPrice?: number | null
  horizonDays: number
}

export function ConvergenceBandChart({ lower, upper, currentPrice, horizonDays }: Props) {
  const startLower = currentPrice ?? lower ?? 0
  const startUpper = currentPrice ?? upper ?? 0
  const data = Array.from({ length: horizonDays }, (_, index) => {
    const t = index + 1
    const alpha = t / horizonDays
    return {
      day: `T+${t}`,
      lower: lower == null ? startLower : startLower + (lower - startLower) * alpha,
      upper: upper == null ? startUpper : startUpper + (upper - startUpper) * alpha,
    }
  })

  return (
    <div className="card chart-card">
      <h3>Convergence zone</h3>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="day" />
          <YAxis domain={['auto', 'auto']} />
          <Tooltip />
          <Area dataKey="upper" type="monotone" fillOpacity={0.1} />
          <Area dataKey="lower" type="monotone" fillOpacity={0.25} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
