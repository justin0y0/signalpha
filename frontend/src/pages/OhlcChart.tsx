import { useEffect, useState, type MouseEvent } from 'react'

type Candle = { t: string; o: number; h: number; l: number; c: number }
const isNum = (x: any): x is number => typeof x === 'number' && isFinite(x)

export function OhlcChart({ ticker, since, entry, dir }: { ticker: string; since?: string; entry?: number; dir?: string }) {
  const [data, setData] = useState<Candle[] | null>(null)
  const [err, setErr] = useState(false)
  const [hov, setHov] = useState<number | null>(null)
  useEffect(() => {
    let on = true
    setHov(null); setData(null); setErr(false)
    fetch(`/api/v1/oracle/ohlc?ticker=${encodeURIComponent(ticker)}&since=${encodeURIComponent(since || '')}`)
      .then(r => r.json())
      .then(d => {
        if (!on) return
        const clean = (d.candles || []).filter(
          (c: Candle) => isNum(c.o) && isNum(c.h) && isNum(c.l) && isNum(c.c)
        )
        setData(clean)
      })
      .catch(() => { if (on) setErr(true) })
    return () => { on = false }
  }, [ticker, since])

  if (err) return <div className="orc2-chart-msg">chart unavailable</div>
  if (!data) return <div className="orc2-chart-msg">loading…</div>
  if (data.length < 2) return <div className="orc2-chart-msg">no price history</div>

  const W = 760, H = 244, padR = 56, padT = 22, padB = 26
  let lo = Math.min(...data.map(d => d.l)), hi = Math.max(...data.map(d => d.h))
  if (isNum(entry)) { lo = Math.min(lo, entry); hi = Math.max(hi, entry) }
  const mg = (hi - lo) * 0.08 || 1; lo -= mg; hi += mg
  const span = hi - lo || 1
  const iw = W - padR
  const X = (i: number) => 6 + i * (iw - 12) / (data.length - 1)
  const Y = (p: number) => padT + (1 - (p - lo) / span) * (H - padT - padB)
  const last = data[data.length - 1].c
  const base = isNum(entry) ? entry : data[0].c
  const col = last >= base ? 'var(--up)' : 'var(--down)'
  const P = data.map((d, i) => [X(i), Y(d.c)] as [number, number])

  let sigI = -1
  if (since) sigI = data.findIndex(d => d.t >= since)
  const sincePct = isNum(entry) && entry !== 0 ? (last - entry) / entry * 100 : null
  const sgnPct = sincePct == null ? null : (dir === 'bearish' ? -sincePct : sincePct)

  let line = `M ${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] || P[i], p1 = P[i], p2 = P[i + 1], p3 = P[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6
    line += ` C ${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`
  }
  const area = `${line} L ${P[P.length - 1][0].toFixed(1)},${H - padB} L ${P[0][0].toFixed(1)},${H - padB} Z`
  const band = `M ${data.map((d, i) => `${X(i).toFixed(1)},${Y(d.h).toFixed(1)}`).join(' L ')} L ${data.map((d, i) => `${X(i).toFixed(1)},${Y(d.l).toFixed(1)}`).reverse().join(' L ')} Z`

  const gid = 'grad_' + ticker.replace(/[^A-Za-z0-9]/g, '')
  const grid = [0, 0.25, 0.5, 0.75, 1].map(f => lo + f * span)
  let hiI = 0, loI = 0
  data.forEach((d, i) => { if (d.h > data[hiI].h) hiI = i; if (d.l < data[loI].l) loI = i })
  const fmt = (p: number) => p >= 1000 ? (p / 1000).toFixed(2) + 'k' : p.toFixed(2)

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const xv = (e.clientX - r.left) / r.width * W
    let best = 0, bd = 1e9
    data.forEach((_, i) => { const dx = Math.abs(X(i) - xv); if (dx < bd) { bd = dx; best = i } })
    setHov(best)
  }
  const hv = hov != null ? data[hov] : null
  const tipLeft = hov != null && X(hov) > iw * 0.6
  const tipX = hov != null ? (tipLeft ? X(hov) - 104 : X(hov) + 10) : 0
  const dPct = hv && isNum(entry) && entry !== 0 ? (hv.c - entry) / entry * 100 : null

  return (
    <svg className="orc2-chart" viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHov(null)}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.30" />
          <stop offset="70%" stopColor={col} stopOpacity="0.05" />
          <stop offset="100%" stopColor={col} stopOpacity="0" />
        </linearGradient>
      </defs>
      {grid.map((p, k) => (
        <g key={k}>
          <line className="orc2-grid" x1={0} x2={iw} y1={Y(p)} y2={Y(p)} />
          <text className="orc2-axis" x={iw + 6} y={Y(p) + 3}>{fmt(p)}</text>
        </g>
      ))}
      {sigI > 0 && (
        <g>
          <rect x={X(sigI)} y={padT} width={iw - X(sigI)} height={H - padT - padB} fill={col} opacity="0.05" />
          <line x1={X(sigI)} x2={X(sigI)} y1={padT} y2={H - padB} stroke={col} strokeOpacity="0.5" strokeWidth="1" strokeDasharray="3 3" />
          <text className="orc2-axis" x={X(sigI) + 4} y={padT + 10} style={{ fill: col }}>▶ signal</text>
        </g>
      )}
      <path d={band} fill={col} fillOpacity="0.07" stroke={col} strokeOpacity="0.12" strokeWidth="1" />
      {isNum(entry) && (
        <g>
          <line className="orc2-entry" x1={0} x2={iw} y1={Y(entry)} y2={Y(entry)} />
          <text className="orc2-entry-lbl" x={4} y={Y(entry) - 5}>entry ${entry.toFixed(2)}</text>
          <circle cx={X(0)} cy={Y(data[0].c)} r="3" fill={col} opacity="0.7" />
        </g>
      )}
      <path d={area} fill={`url(#${gid})`} />
      <path className="orc2-line" d={line} fill="none" stroke={col} strokeWidth="2.4" style={{ filter: `drop-shadow(0 1px 6px ${col})` }} />
      <g>
        <circle cx={X(hiI)} cy={Y(data[hiI].h)} r="2.5" fill="var(--up)" />
        <text className="orc2-axis" x={X(hiI)} y={Y(data[hiI].h) - 6} textAnchor="middle" style={{ fill: 'var(--up)' }}>H {data[hiI].h.toFixed(2)}</text>
        <circle cx={X(loI)} cy={Y(data[loI].l)} r="2.5" fill="var(--down)" />
        <text className="orc2-axis" x={X(loI)} y={Y(data[loI].l) + 12} textAnchor="middle" style={{ fill: 'var(--down)' }}>L {data[loI].l.toFixed(2)}</text>
      </g>
      <circle cx={X(data.length - 1)} cy={Y(last)} r="4.5" fill={col} stroke="var(--bg-1)" strokeWidth="1.5" />
      {sgnPct != null && (
        <text className="orc2-axis" x={4} y={14} style={{ fill: sgnPct >= 0 ? 'var(--up)' : 'var(--down)', fontSize: '12px', fontWeight: 600 }}>{sgnPct >= 0 ? '+' : ''}{sgnPct.toFixed(1)}% since signal</text>
      )}
      {hv && (
        <g>
          <line x1={X(hov!)} x2={X(hov!)} y1={padT} y2={H - padB} stroke={col} strokeOpacity="0.35" strokeWidth="1" strokeDasharray="3 3" />
          <circle cx={X(hov!)} cy={Y(hv.c)} r="4" fill="none" stroke={col} strokeWidth="1.6" />
          <g transform={`translate(${tipX},${padT + 2})`}>
            <rect width="96" height="62" rx="6" fill="var(--bg-1)" stroke="var(--border)" opacity="0.96" />
            <text x="8" y="15" style={{ fill: 'var(--text, #e5e7eb)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>{hv.t}</text>
            <text x="8" y="30" style={{ fill: 'var(--text-muted, #94a3b8)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>O {hv.o.toFixed(2)} H {hv.h.toFixed(2)}</text>
            <text x="8" y="43" style={{ fill: 'var(--text-muted, #94a3b8)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>L {hv.l.toFixed(2)} C {hv.c.toFixed(2)}</text>
            {dPct != null && <text x="8" y="56" style={{ fill: dPct >= 0 ? 'var(--up)' : 'var(--down)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>{dPct >= 0 ? '+' : ''}{dPct.toFixed(1)}% vs entry</text>}
          </g>
        </g>
      )}
      <text className="orc2-axis" x={0} y={H - 8}>{data[0].t}</text>
      <text className="orc2-axis" x={iw} y={H - 8} textAnchor="end">{data[data.length - 1].t} · ${last.toFixed(2)}</text>
    </svg>
  )
}
