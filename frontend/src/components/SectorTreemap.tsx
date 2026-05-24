import { useEffect, useRef, useState, useMemo } from 'react'
import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy'
import { motion } from 'framer-motion'

interface Ticker {
  ticker: string; sector: string; price: number
  score: number; s_score: number | null; market_cap?: number
}
interface Props { tickers: Ticker[]; onSelect: (ticker: string) => void }

const SECTOR_ORDER = ['Technology','Communication','Consumer','Healthcare','Financial','Industrials','Staples','Energy','Utilities','Materials','Real Estate']
const SECTOR_COLOR: Record<string,string> = { Technology:'#38bdf8', Communication:'#a78bfa', Consumer:'#fb923c', Healthcare:'#4ade80', Financial:'#fbbf24', Industrials:'#94a3b8', Staples:'#ec4899', Energy:'#f87171', Utilities:'#06b6d4', Materials:'#84cc16', 'Real Estate':'#c084fc' }

function colorFor(score: number): string {
  if (Math.abs(score) < 0.05) return 'rgba(56, 90, 130, 0.25)'
  const a = Math.min(0.75, Math.abs(score) * 0.85 + 0.20)
  return score > 0 ? `rgba(74, 222, 128, ${a})` : `rgba(248, 113, 113, ${a})`
}

export function SectorTreemap({ tickers, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 1200, h: 720 })
  const [hovered, setHovered] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      const r = entries[0].contentRect
      setSize({ w: Math.max(600, r.width), h: Math.max(500, Math.min(900, r.width * 0.62)) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(() => {
    const bySector: Record<string, Ticker[]> = {}
    tickers.forEach(t => { const s = t.sector || 'Other'; if (!bySector[s]) bySector[s] = []; bySector[s].push(t) })
    const sectorList = SECTOR_ORDER.filter(s => bySector[s]).concat(Object.keys(bySector).filter(s => !SECTOR_ORDER.includes(s)))
    const data: any = { name: 'root', children: sectorList.map(sec => ({ name: sec, children: (bySector[sec] || []).map(t => ({ ...t, name: t.ticker, value: Math.max(20, t.market_cap || 50) })) })) }
    const root = hierarchy(data).sum((d: any) => d.value || 0).sort((a: any, b: any) => (b.value || 0) - (a.value || 0))
    treemap().tile(treemapSquarify.ratio(1.3)).size([size.w, size.h]).paddingOuter(3).paddingTop((d: any) => d.depth === 0 ? 0 : 22).paddingInner(2).round(true)(root)
    return root
  }, [tickers, size])

  const leaves = layout.leaves() as any[]
  const sectors = layout.descendants().filter((d: any) => d.depth === 1)

  return (
    <div ref={containerRef} className="stm-wrap">
      <svg width={size.w} height={size.h} style={{ display: 'block', width: '100%', height: 'auto' }}>
        {sectors.map((sec: any) => {
          const w = sec.x1 - sec.x0, h = sec.y1 - sec.y0
          const color = SECTOR_COLOR[sec.data.name] || '#94a3b8'
          return (
            <g key={sec.data.name}>
              <rect x={sec.x0} y={sec.y0} width={w} height={h} fill="rgba(13,24,41,0.4)" stroke={color} strokeOpacity={0.4} strokeWidth={1.5} rx={6} />
              {w > 50 && <text x={sec.x0+7} y={sec.y0+15} fill={color} fontSize={10} fontWeight={700} fontFamily="JetBrains Mono,monospace" letterSpacing={1}>{sec.data.name.toUpperCase()}</text>}
            </g>
          )
        })}
        {leaves.map((leaf: any) => {
          const w = leaf.x1 - leaf.x0, h = leaf.y1 - leaf.y0
          if (w < 6 || h < 6) return null
          const score = leaf.data.score || 0
          const ticker: string = leaf.data.ticker
          const isHov = hovered === ticker
          const showLogo = w > 48 && h > 48
          const logoSize = Math.min(Math.min(w,h)*0.36, 44)
          const cx = leaf.x0 + w / 2
          const labelSize = Math.max(8, Math.min(15, Math.sqrt(w*h)/9))
          const mcap = leaf.data.market_cap || 0
          return (
            <motion.g key={ticker} style={{ cursor: 'pointer' }} onClick={() => onSelect(ticker)}
              onMouseEnter={() => setHovered(ticker)} onMouseLeave={() => setHovered(null)}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.25 }}>
              <rect x={leaf.x0+1} y={leaf.y0+1} width={w-2} height={h-2} fill={colorFor(score)}
                stroke={isHov ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.07)'} strokeWidth={isHov ? 1.5 : 0.5} rx={3} />
              {showLogo && <image href={`/api/v1/logos/${ticker}.png`} x={cx-logoSize/2} y={leaf.y0+6} width={logoSize} height={logoSize} preserveAspectRatio="xMidYMid meet" />}
              <text x={cx} y={showLogo ? leaf.y0+6+logoSize+labelSize+1 : leaf.y0+h/2+(Math.abs(score)>=0.05?-4:labelSize/3)}
                textAnchor="middle" fill="#fff" fontSize={labelSize} fontWeight={700}
                fontFamily="JetBrains Mono,monospace" style={{ pointerEvents:'none' }}>
                {ticker}
              </text>
              {w > 55 && h > 50 && mcap > 0 && (
                <text x={cx} y={(showLogo ? leaf.y0+6+logoSize+labelSize+1 : leaf.y0+h/2-3)+labelSize*0.9}
                  textAnchor="middle" fill="rgba(255,255,255,0.45)" fontSize={labelSize*0.62}
                  fontFamily="JetBrains Mono,monospace" style={{ pointerEvents:'none' }}>
                  {mcap>=1000 ? `$${(mcap/1000).toFixed(1)}T` : `$${mcap}B`}
                </text>
              )}
              {Math.abs(score)>=0.05 && w>45 && h>36 && (
                <text x={cx} y={leaf.y1-6} textAnchor="middle"
                  fill={score>0 ? '#4ade80' : '#f87171'} fontSize={labelSize*0.72} fontWeight={700}
                  fontFamily="JetBrains Mono,monospace" style={{ pointerEvents:'none' }}>
                  {score>0?'+':''}{score.toFixed(2)}
                </text>
              )}
            </motion.g>
          )
        })}
      </svg>
      {hovered && (() => {
        const t = tickers.find(x => x.ticker === hovered)
        if (!t) return null
        return (
          <div className="stm-hover">
            <div className="stm-hover__head"><b>{t.ticker}</b><span style={{color: SECTOR_COLOR[t.sector]||'#94a3b8'}}>{t.sector}</span></div>
            <div className="stm-hover__body">
              <span>${t.price.toFixed(2)} · {(t.market_cap||0)>=1000?`$${((t.market_cap||0)/1000).toFixed(1)}T`:`$${t.market_cap||0}B`}</span>
              <span style={{color:t.score>0?'#4ade80':t.score<0?'#f87171':'#94a3b8'}}>score {t.score>=0?'+':''}{(t.score||0).toFixed(2)}{t.s_score!==null?` · s ${t.s_score>=0?'+':''}${t.s_score.toFixed(2)}`:''}</span>
              <span style={{fontSize:'0.65rem',color:'#94a3b8'}}>click for full details →</span>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
