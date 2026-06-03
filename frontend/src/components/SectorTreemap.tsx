import { useEffect, useRef, useState, useMemo } from 'react'
import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy'
import { motion } from 'framer-motion'
import { StockLogo } from './StockLogo'

interface Ticker {
  ticker: string; sector: string; price: number
  score: number; s_score: number | null; market_cap?: number
}
interface Props { tickers: Ticker[]; onSelect: (t: string) => void; selectedSector?: string | null; onHover?: (t: any) => void }

const SECTOR_ORDER = ['Technology','Communication','Consumer','Healthcare','Financial','Industrials','Staples','Energy','Utilities','Materials','Real Estate']
const SECTOR_COLOR: Record<string,string> = {
  Technology:'#38bdf8', Communication:'#a78bfa', Consumer:'#fb923c',
  Healthcare:'#4ade80', Financial:'#fbbf24', Industrials:'#94a3b8',
  Staples:'#ec4899', Energy:'#f87171', Utilities:'#06b6d4',
  Materials:'#84cc16', 'Real Estate':'#c084fc'
}

function cellGradient(score: number): string {
  if (Math.abs(score) < 0.05) {
    return 'linear-gradient(135deg, rgba(38,58,86,0.55), rgba(22,38,60,0.7))'
  }
  const a = Math.min(0.85, Math.abs(score) * 0.95 + 0.25)
  const b = Math.max(0.20, Math.abs(score) * 0.55 + 0.18)
  return score > 0
    ? `linear-gradient(135deg, rgba(74,222,128,${a}), rgba(22,163,74,${b}))`
    : `linear-gradient(135deg, rgba(248,113,113,${a}), rgba(185,28,28,${b}))`
}

export function SectorTreemap({ tickers, onSelect, selectedSector, onHover }: Props) {
  const visible = selectedSector ? tickers.filter(t => t.sector === selectedSector) : tickers
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 1200, h: 800 })

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      const r = entries[0].contentRect
      setSize({ w: Math.max(600, r.width), h: Math.max(600, Math.min(950, r.width * 0.66)) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(() => {
    const bySector: Record<string, Ticker[]> = {}
    visible.forEach(t => {
      const s = t.sector || 'Other'
      ;(bySector[s] = bySector[s] || []).push(t)
    })
    const sectorList = SECTOR_ORDER.filter(s => bySector[s])
      .concat(Object.keys(bySector).filter(s => !SECTOR_ORDER.includes(s)))
    const data: any = {
      name: 'root',
      children: sectorList.map(sec => ({
        name: sec,
        children: (bySector[sec] || []).map(t => ({
          ...t, name: t.ticker, value: Math.max(25, t.market_cap || 50)
        }))
      }))
    }
    const root = hierarchy(data)
      .sum((d: any) => d.value || 0)
      .sort((a: any, b: any) => (b.value || 0) - (a.value || 0))
    treemap()
      .tile(treemapSquarify.ratio(1.4))
      .size([size.w, size.h])
      .paddingOuter(4)
      .paddingTop((d: any) => d.depth === 0 ? 0 : 26)
      .paddingInner(3)
      .round(true)(root)
    return root
  }, [visible, size])

  const leaves = layout.leaves() as any[]
  const sectors = layout.descendants().filter((d: any) => d.depth === 1)

  return (
    <div ref={containerRef} className="stm-wrap">
      <svg width={size.w} height={size.h} className="stm-svg">
        {sectors.map((sec: any) => {
          const w = sec.x1 - sec.x0, h = sec.y1 - sec.y0
          const color = SECTOR_COLOR[sec.data.name] || '#94a3b8'
          return (
            <g key={sec.data.name}>
              <rect x={sec.x0} y={sec.y0} width={w} height={h}
                fill="rgba(6,14,28,0.85)"
                stroke={color} strokeOpacity={0.65} strokeWidth={1}
                rx={8} />
              {w > 60 && (
                <text x={sec.x0 + 10} y={sec.y0 + 17}
                  fill={color} fontSize={11} fontWeight={800}
                  fontFamily="JetBrains Mono, monospace"
                  letterSpacing={1.8}>
                  {sec.data.name.toUpperCase()}
                </text>
              )}
            </g>
          )
        })}
        {leaves.map((leaf: any, idx: number) => {
          const w = leaf.x1 - leaf.x0, h = leaf.y1 - leaf.y0
          if (w < 8 || h < 8) return null
          const ticker: string = leaf.data.ticker
          const score: number = leaf.data.score || 0
          const sScore: number | null = leaf.data.s_score
          const price: number = leaf.data.price || 0
          const mcap: number = leaf.data.market_cap || 0
          return (
            <motion.foreignObject
              key={ticker}
              x={leaf.x0} y={leaf.y0} width={w} height={h}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.35, delay: Math.min(0.6, idx * 0.004) }}>
              <div style={{ width: '100%', height: '100%' }}>
                <TmCell w={w} h={h} ticker={ticker} score={score}
                  sScore={sScore} price={price} mcap={mcap}
                  onClick={() => onSelect(ticker)} onHover={onHover} />
              </div>
            </motion.foreignObject>
          )
        })}
      </svg>
    </div>
  )
}

function TmCell({ w, h, ticker, score, sScore, price, mcap, onClick, onHover }: any) {
  const minDim = Math.min(w, h)
  const showLogo = minDim >= 56
  const showMcap = w >= 68 && h >= 60
  const showScore = w >= 42 && h >= 38
  const showSScore = sScore !== null && Math.abs(sScore) >= 1.0 && w >= 75 && h >= 75
  const logoSize = showLogo ? Math.min(minDim * 0.38, 60) : 0
  const tickerSize = Math.max(10, Math.min(18, Math.sqrt(w * h) / 8.5))

  return (
    <div className={`tmc ${Math.abs(score) > 0.8 ? (score > 0 ? "tmc--pulse-pos" : "tmc--pulse-neg") : ""}`} onClick={onClick} onMouseEnter={() => onHover && onHover({ticker, score, sScore, price, mcap})} onMouseLeave={() => onHover && onHover(null)}
      style={{ background: cellGradient(score) }}
      title={`${ticker}  ·  $${price.toFixed(2)}  ·  score ${score >= 0 ? '+' : ''}${score.toFixed(2)}`}>
      <div className="tmc__shine" />
      {showLogo && (
        <div className="tmc__logo">
          <StockLogo ticker={ticker} size={logoSize} />
        </div>
      )}
      <div className="tmc__name" style={{ fontSize: `${tickerSize}px` }}>{ticker}</div>
      {showMcap && mcap > 0 && (
        <div className="tmc__mcap" style={{ fontSize: `${tickerSize * 0.58}px` }}>
          {mcap >= 1000 ? `$${(mcap/1000).toFixed(1)}T` : `$${mcap}B`}
        </div>
      )}
      {showScore && (
        <div className={`tmc__score ${score > 0 ? 'pos' : 'neg'}`}
          style={{ fontSize: `${tickerSize * 0.78}px` }}>
          {score > 0 ? '+' : ''}{score.toFixed(2)}
        </div>
      )}
      {showSScore && (
        <div className="tmc__sscore">s {sScore >= 0 ? '+' : ''}{sScore.toFixed(2)}</div>
      )}
    </div>
  )
}
