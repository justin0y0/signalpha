type Props = {
  data: number[]
  width?: number
  height?: number
  positive?: boolean
}

export function Sparkline({ data, width = 120, height = 32, positive }: Props) {
  if (!data || data.length < 2) {
    return <div style={{ width, height }} />
  }
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const step = width / (data.length - 1)
  const points = data
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`)
    .join(' ')

  const isPositive = positive ?? data[data.length - 1] >= data[0]
  const stroke = isPositive ? 'var(--up)' : 'var(--down)'
  const fill = isPositive ? 'rgba(52,211,153,0.12)' : 'rgba(251,113,133,0.12)'

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={`spark-${isPositive ? 'u' : 'd'}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
      />
      <polygon
        fill={fill}
        points={`0,${height} ${points} ${width},${height}`}
      />
    </svg>
  )
}
