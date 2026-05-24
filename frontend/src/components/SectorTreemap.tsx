import { useMemo } from 'react'
import { Treemap, ResponsiveContainer } from 'recharts'
import { StockLogo } from './StockLogo'

interface Ticker {
  ticker: string
  sector: string
  price: number
  score: number
  s_score: number | null
}

interface Props {
  tickers: Ticker[]
  onSelect: (ticker: string) => void
}

const SECTOR_ORDER = [
  'Technology', 'Communication', 'Healthcare', 'Financial', 'Consumer',
  'Staples', 'Industrials', 'Energy', 'Utilities', 'Materials', 'Real Estate',
]

export function SectorTreemap({ tickers, onSelect }: Props) {
  const data = useMemo(() => {
    const bySector: Record<string, Ticker[]> = {}
    tickers.forEach(t => {
      const sec = t.sector || 'Other'
      if (!bySector[sec]) bySector[sec] = []
      bySector[sec].push(t)
    })
    return SECTOR_ORDER
      .filter(s => bySector[s])
      .concat(Object.keys(bySector).filter(s => !SECTOR_ORDER.includes(s)))
      .map(sector => ({
        name: sector,
        children: bySector[sector].map(t => ({
          name: t.ticker,
          size: Math.max(0.15, Math.abs(t.score || 0)) + 0.4, // size mainly equal w/ slight boost for signals
          score: t.score || 0,
          price: t.price,
          s_score: t.s_score,
        })),
      }))
  }, [tickers])

  return (
    <div className="sector-treemap">
      <ResponsiveContainer width="100%" height={620}>
        <Treemap
          data={data}
          dataKey="size"
          stroke="#0a1628"
          fill="#0d1929"
          aspectRatio={4 / 3}
          content={<TreemapCell onSelect={onSelect} />}
        />
      </ResponsiveContainer>
    </div>
  )
}

function colorFor(score: number): string {
  const a = Math.min(0.65, Math.abs(score) * 0.7 + 0.12)
  if (score > 0.02) return `rgba(74, 222, 128, ${a})`
  if (score < -0.02) return `rgba(248, 113, 113, ${a})`
  return 'rgba(56, 90, 130, 0.22)'
}

function TreemapCell(props: any) {
  const { x, y, width, height, name, score, price, depth, onSelect, root } = props

  // Sector header
  if (depth === 1) {
    return (
      <g>
        <rect x={x} y={y} width={width} height={height} fill="rgba(0,0,0,0.2)"
          stroke="#1a2740" strokeWidth={1.5} />
        {width > 80 && height > 28 && (
          <text x={x + 8} y={y + 18} fill="#a78bfa" fontSize={11} fontFamily="JetBrains Mono, monospace"
            fontWeight={700} letterSpacing={1}>
            {name.toUpperCase()}
          </text>
        )}
      </g>
    )
  }

  // Stock leaf cell
  const showLogo = width > 60 && height > 60
  const showText = width > 40 && height > 38
  const logoSize = Math.min(width, height) * 0.32
  const ticker = name

  return (
    <g
      style={{ cursor: 'pointer' }}
      onClick={() => onSelect && onSelect(ticker)}>
      <rect x={x + 1} y={y + 1} width={width - 2} height={height - 2}
        fill={colorFor(score || 0)}
        stroke="rgba(255,255,255,0.06)" strokeWidth={1}
        rx={3} />
      {showLogo && (
        <foreignObject x={x + (width - logoSize) / 2} y={y + 8} width={logoSize} height={logoSize}>
          <div style={{ width: logoSize, height: logoSize, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <TreemapLogo ticker={ticker} size={logoSize} />
          </div>
        </foreignObject>
      )}
      {showText && (
        <text x={x + width / 2} y={showLogo ? y + 8 + logoSize + 14 : y + height / 2 - 4}
          textAnchor="middle" fill="#fff" fontSize={Math.min(13, width / 5)} fontWeight={700}
          fontFamily="JetBrains Mono, monospace">
          {ticker}
        </text>
      )}
      {showText && height > 50 && (
        <text x={x + width / 2} y={showLogo ? y + 8 + logoSize + 28 : y + height / 2 + 12}
          textAnchor="middle"
          fill={score > 0 ? '#4ade80' : score < 0 ? '#f87171' : 'var(--text-tertiary)'}
          fontSize={Math.min(11, width / 7)} fontFamily="JetBrains Mono, monospace">
          {(score || 0) >= 0 ? '+' : ''}{(score || 0).toFixed(2)}
        </text>
      )}
    </g>
  )
}

// Tiny wrapper that renders the StockLogo inside SVG foreignObject
function TreemapLogo({ ticker, size }: { ticker: string; size: number }) {
  return <StockLogo ticker={ticker} size={size} />
}
