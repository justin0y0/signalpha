import { useState } from 'react'

interface Props {
  ticker: string
  size?: number
  className?: string
}

// Multi-source logo with monogram fallback.
const SOURCES = [
  (t: string) => `https://financialmodelingprep.com/image-stock/${t}.png`,
  (t: string) => `https://eodhd.com/img/logos/US/${t}.png`,
  (t: string) => `https://assets.parqet.com/logos/symbol/${t}`,
]

const COLORS = ['#38bdf8', '#a78bfa', '#4ade80', '#fbbf24', '#f87171', '#ec4899', '#06b6d4', '#fb923c']

export function StockLogo({ ticker, size = 36, className = '' }: Props) {
  const [srcIdx, setSrcIdx] = useState(0)
  const [failed, setFailed] = useState(false)
  const symbol = ticker.replace('-', '.').toUpperCase()
  const hashCode = symbol.split('').reduce((a, c) => ((a << 5) - a) + c.charCodeAt(0), 0)
  const bg = COLORS[Math.abs(hashCode) % COLORS.length]

  if (failed || srcIdx >= SOURCES.length) {
    return (
      <div className={`stock-logo stock-logo--mono ${className}`}
        style={{ width: size, height: size, background: bg, fontSize: size * 0.42 }}>
        {symbol.substring(0, Math.min(symbol.length, 3))}
      </div>
    )
  }

  return (
    <img
      src={SOURCES[srcIdx](symbol)}
      alt={ticker}
      className={`stock-logo ${className}`}
      style={{ width: size, height: size }}
      onError={() => {
        if (srcIdx < SOURCES.length - 1) setSrcIdx(srcIdx + 1)
        else setFailed(true)
      }}
    />
  )
}
