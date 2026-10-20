import { useMemo, useRef, useState, type PointerEvent } from 'react'

/**
 * A backtest, drawn calmly: one line of cumulative return (log scale, so a compounding
 * curve reads as steady growth instead of a hockey stick), the benchmark dashed behind
 * it, and the drawdown as a shallow band underneath — how far below its last high the
 * strategy stood at each point. Under the chart, one small bar per calendar year.
 *
 * Monthly K-lines over nineteen years were 220 candles of noise; live records keep the
 * K-line (Candles.tsx), where each candle is a session someone can check.
 */
type Pt = { t: string; v: number }
type Props = { series: Pt[]; bench?: Pt[]; years?: { y: number; ret: number }[]; benchLabel?: string; empty?: string }

const W = 640, H = 170, DDH = 38, padR = 50, padT = 8
const pctS = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v) >= 1000 ? Math.round(Math.abs(v)).toLocaleString() : Math.abs(v).toFixed(Math.abs(v) >= 100 ? 0 : 1)}%`

export function EquityLine({ series, bench, years, benchLabel = 'SPY', empty = '—' }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const [hov, setHov] = useState<number | null>(null)
  const m = useMemo(() => {
    if (series.length < 2) return null
    const g = (v: number) => Math.log(Math.max(1 + v / 100, 1e-3))
    const bmap = new Map((bench ?? []).map((b) => [b.t, b.v]))
    const all = series.map((p) => g(p.v)).concat(series.map((p) => bmap.get(p.t)).filter((v): v is number => v != null).map(g)).concat([0])
    let lo = Math.min(...all), hi = Math.max(...all)
    const pad = (hi - lo) * 0.06 || 0.05
    lo -= pad; hi += pad
    const iw = W - padR
    const X = (i: number) => (i / (series.length - 1)) * iw
    const Y = (v: number) => padT + (1 - (g(v) - lo) / (hi - lo)) * (H - padT - 6)
    let peak = -Infinity
    const dd = series.map((p) => { const e = 1 + p.v / 100; peak = Math.max(peak, e); return e / peak - 1 })
    const ddMin = Math.min(-0.05, ...dd)
    const DY = (d: number) => H + 6 + (d / ddMin) * DDH
    const line = series.map((p, i) => `${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(' ')
    const bl = series.map((p, i) => (bmap.has(p.t) ? `${X(i).toFixed(1)},${Y(bmap.get(p.t)!).toFixed(1)}` : null)).filter(Boolean).join(' ')
    const ddPath = `M0,${H + 6} ` + dd.map((d, i) => `L${X(i).toFixed(1)},${DY(d).toFixed(1)}`).join(' ') + ` L${X(series.length - 1).toFixed(1)},${H + 6} Z`
    const ticks: number[] = []
    for (const v of [-50, 0, 100, 300, 900, 4900, 9900, 99900]) if (g(v) > lo && g(v) < hi) ticks.push(v)
    const kept = ticks.filter((v, i) => i === 0 || Math.abs(Y(v) - Y(ticks[i - 1])) > 14)
    return { X, Y, line, bl, ddPath, dd, ddMin, kept, bmap }
  }, [series, bench])

  if (!m) return <div className="kl-empty">{empty}</div>
  const last = series[series.length - 1]
  const i = hov ?? series.length - 1
  const p = series[i]
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const x = ((e.clientX - r.left) / r.width) * W
    const k = Math.round((x / (W - padR)) * (series.length - 1))
    setHov(k >= 0 && k < series.length ? k : null)
  }
  const ymax = years?.length ? Math.max(0.05, ...years.map((y) => Math.abs(y.ret))) : 1

  return (
    <div className="eq">
      <svg ref={ref} viewBox={`0 0 ${W} ${H + DDH + 10}`} className="kl-svg" onPointerMove={onMove} onPointerLeave={() => setHov(null)}
        role="img" aria-label={pctS(last.v)}>
        {m.kept.map((v) => (
          <g key={v}>
            <line x1={0} x2={W - padR} y1={m.Y(v)} y2={m.Y(v)} className={v === 0 ? 'kl-zero' : 'kl-grid'} />
            <text x={W - padR + 6} y={m.Y(v) + 3} className="kl-tick">{v === 0 ? '0%' : pctS(v)}</text>
          </g>
        ))}
        {m.bl && <polyline points={m.bl} className="kl-bench" />}
        <polyline points={m.line} className="eq-line" />
        <path d={m.ddPath} className="eq-dd" />
        <text x={W - padR + 6} y={H + 6 + DDH} className="kl-tick">{pctS(m.ddMin * 100)}</text>
        {hov != null && <line x1={m.X(i)} x2={m.X(i)} y1={padT} y2={H + 6 + DDH} className="eq-cursor" />}
        <circle cx={m.X(i)} cy={m.Y(p.v)} r={2.6} className="eq-dot" />
      </svg>
      <div className="kl-read">
        <b>{p.t}</b>
        <span className={p.v >= 0 ? 'is-up' : 'is-down'}>{pctS(p.v)}</span>
        {m.bmap.has(p.t) && <span className="kl-read__bench"><i />{benchLabel} {pctS(m.bmap.get(p.t)!)}</span>}
        <span className="eq-ddread">DD {pctS(m.dd[i] * 100)}</span>
      </div>
      {years && years.length > 1 && (
        <div className="eq-years" role="list">
          {years.map((y) => (
            <span key={y.y} role="listitem" title={`${y.y}: ${pctS(y.ret * 100)}`} className={y.ret >= 0 ? 'is-up' : 'is-down'}>
              <i style={{ height: `${Math.max(2, (Math.abs(y.ret) / ymax) * 26)}px` }} />
              <em>{String(y.y).slice(2)}</em>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
