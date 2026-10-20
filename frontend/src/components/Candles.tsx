import { useMemo, useRef, useState, type PointerEvent } from 'react'

/**
 * A return K-line: one candle per period (month for backtests, session for live
 * records), values in per cent from the start. Up candles mint, down coral — colour
 * carries meaning and nothing else. `log` draws growth on a log scale (1 + v/100), which
 * is the only honest way to show a compounding curve that runs from 0% to four digits.
 * An optional benchmark (SPY) is a dashed line on the same scale.
 */
export type Candle = { t: string; o: number; h: number; l: number; c: number }
type Props = {
  data: Candle[]
  bench?: { t: string; v: number }[]
  log?: boolean
  height?: number
  empty?: string
  benchLabel?: string
}

const fmt = (v: number) => `${v >= 0 ? '+' : ''}${Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(Math.abs(v) >= 100 ? 0 : 2)}%`
const tickFmt = (v: number) => (v === 0 ? '0%' : `${v > 0 ? '+' : ''}${Math.abs(v) >= 1 ? Math.round(v).toLocaleString() : v.toFixed(Math.abs(v) >= 0.1 ? 1 : 2)}%`)

export function Candles({ data, bench, log = false, height = 180, empty = '—', benchLabel = 'SPY' }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const [hov, setHov] = useState<number | null>(null)
  const W = 640, H = height, padL = 4, padR = 52, padT = 10, padB = 18

  const m = useMemo(() => {
    if (!data.length) return null
    const f = (v: number) => (log ? Math.log(Math.max(1 + v / 100, 1e-4)) : v)
    const bmap = new Map((bench ?? []).map((b) => [b.t, b.v]))
    const vals = data.flatMap((d) => [d.h, d.l]).concat(data.map((d) => bmap.get(d.t)).filter((v): v is number => v != null)).concat([0])
    let lo = Math.min(...vals.map(f)), hi = Math.max(...vals.map(f))
    const mg = (hi - lo) * 0.06 || 0.5
    lo -= mg; hi += mg
    const iw = W - padL - padR
    const step = iw / data.length
    const X = (i: number) => padL + step * (i + 0.5)
    const Y = (v: number) => padT + (1 - (f(v) - lo) / (hi - lo)) * (H - padT - padB)
    // y ticks: a few round values in the visible range
    const ticks: number[] = []
    if (log) {
      for (const g of [-0.9, -0.5, -0.25, 0, 0.5, 1, 3, 9, 49, 99, 499, 999, 4999, 9999, 99999]) {
        const v = g * 100
        if (f(v) >= lo && f(v) <= hi) ticks.push(v)
      }
    } else {
      const span = hi - lo
      const raw = span / 4
      const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)))
      const unit = [1, 2, 5, 10].map((k) => k * mag).find((u) => u >= raw) ?? raw
      for (let v = Math.ceil(lo / unit) * unit; v <= hi; v += unit) ticks.push(+v.toFixed(6))
    }
    // keep labels at least 16px apart, zero first
    const kept: number[] = []
    for (const v of [...ticks].sort((a, b) => (a === 0 ? -1 : b === 0 ? 1 : 0))) {
      if (kept.every((k) => Math.abs(Y(k) - Y(v)) >= 16)) kept.push(v)
    }
    const bpts = data.map((d, i) => (bmap.has(d.t) ? `${X(i).toFixed(1)},${Y(bmap.get(d.t)!).toFixed(1)}` : null)).filter(Boolean)
    return { X, Y, step, ticks: kept, bpts }
  }, [data, bench, log, H])

  if (!m) return <div className="kl-empty">{empty}</div>
  const { X, Y, step, ticks, bpts } = m
  const bw = Math.max(1, Math.min(10, step * 0.62))
  const last = data[data.length - 1]

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const x = ((e.clientX - r.left) / r.width) * W
    const i = Math.round((x - padL) / step - 0.5)
    setHov(i >= 0 && i < data.length ? i : null)
  }
  const h = hov != null ? data[hov] : null

  return (
    <div className="kl">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="kl-svg" onPointerMove={onMove} onPointerLeave={() => setHov(null)} role="img"
        aria-label={`${fmt(last.c)}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={Y(v)} y2={Y(v)} className={v === 0 ? 'kl-zero' : 'kl-grid'} />
            <text x={W - padR + 6} y={Y(v) + 3} className="kl-tick">{tickFmt(v)}</text>
          </g>
        ))}
        {bpts.length > 1 && <polyline points={bpts.join(' ')} className="kl-bench" />}
        {data.map((d, i) => {
          const up = d.c >= d.o
          const y1 = Y(Math.max(d.o, d.c)), y2 = Y(Math.min(d.o, d.c))
          return (
            <g key={d.t} className={up ? 'kl-up' : 'kl-down'} opacity={hov == null || hov === i ? 1 : 0.55}>
              <line x1={X(i)} x2={X(i)} y1={Y(d.h)} y2={Y(d.l)} className="kl-wick" />
              <rect x={X(i) - bw / 2} y={y1} width={bw} height={Math.max(1, y2 - y1)} className="kl-body" />
            </g>
          )
        })}
        <text x={padL} y={H - 4} className="kl-tick">{data[0].t}</text>
        <text x={W - padR} y={H - 4} className="kl-tick" textAnchor="end">{last.t}</text>
      </svg>
      <div className="kl-read">
        {h ? (
          <>
            <b>{h.t}</b>
            <span>O {fmt(h.o)}</span><span>H {fmt(h.h)}</span><span>L {fmt(h.l)}</span>
            <span className={h.c >= h.o ? 'is-up' : 'is-down'}>C {fmt(h.c)}</span>
          </>
        ) : (
          <>
            <b>{last.t}</b>
            <span className={last.c >= 0 ? 'is-up' : 'is-down'}>{fmt(last.c)}</span>
            {bpts.length > 1 && <span className="kl-read__bench"><i />{benchLabel}</span>}
          </>
        )}
      </div>
    </div>
  )
}
