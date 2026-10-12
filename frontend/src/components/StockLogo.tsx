import { useState } from 'react'

interface Props { ticker: string; size?: number; className?: string }
const COLORS = ['#f5b544','#8fc7ff','#63e6a8','#f5b544','#ff7d6b','#ff7d6b','#e09a2b','#f08c3a']

export function StockLogo({ ticker, size = 36, className = '' }: Props) {
  const [failed, setFailed] = useState(false)
  const sym = (ticker || '?').replace('-', '.').toUpperCase()
  const hash = sym.split('').reduce((a, c) => ((a << 5) - a) + c.charCodeAt(0), 0)
  const bg = COLORS[Math.abs(hash) % COLORS.length]
  if (failed) {
    return (<div className={`stock-logo stock-logo--mono ${className}`}
      style={{ width: size, height: size, background: bg,
               fontSize: size * (sym.length > 3 ? 0.32 : 0.40) }}>
      {sym.substring(0, Math.min(sym.length, 4))}</div>)
  }
  return (<img src={`/api/v1/logos/${sym.replace('.', '-')}.png`} alt={ticker}
    className={`stock-logo ${className}`} style={{ width: size, height: size }}
    loading="lazy" onError={() => setFailed(true)} />)
}
