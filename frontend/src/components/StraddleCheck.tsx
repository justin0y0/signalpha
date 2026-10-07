import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Crosshair } from 'lucide-react'
import { useT } from '../i18n'

/**
 * Straddle Check — "is the move priced?" for one stock.
 *
 * Every past earnings reaction is a dot, placed by its size; colour is the direction.
 * Two reference lines: the stock's usual move (its band) and what the straddle is
 * pricing for the next report. Drag anywhere on the plot to ask "how often has this
 * name moved more than X?".
 *
 * This is description, not prediction — the honest version of the comparison options
 * traders pay data vendors for. The one forward-looking number on the card is the
 * breakout model's, labelled as such.
 */

type Payload = {
  ticker: string
  band: number | null
  history: { date: string; move: number }[]
  next: { earnings_date: string; implied_move_pct: number | null; prob_move: number | null; move_tier: string | null } | null
}

const W = 640
const H = 150
const PAD = 18
const R = 4.2

export function StraddleCheck({ ticker }: { ticker: string }) {
  const { t } = useT()
  const [data, setData] = useState<Payload | null>(null)
  const [thr, setThr] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const svgRef = useRef<SVGSVGElement | null>(null)

  useEffect(() => {
    let alive = true
    fetch(`/api/v1/moves/${encodeURIComponent(ticker)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive) setData(d) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [ticker])

  const implied = data?.next?.implied_move_pct ?? null
  const band = data?.band ?? null
  const moves = useMemo(() => (data?.history ?? []).map((h) => ({ ...h, abs: Math.abs(h.move) })), [data])

  const xmax = useMemo(() => {
    const m = Math.max(0.02, ...moves.map((x) => x.abs), implied ?? 0, band ?? 0)
    return Math.min(0.3, m * 1.08)
  }, [moves, implied, band])
  const x = (v: number) => PAD + (Math.min(v, xmax) / xmax) * (W - 2 * PAD)
  const inv = (px: number) => Math.max(0, Math.min(xmax, ((px - PAD) / (W - 2 * PAD)) * xmax))

  // Beeswarm: stack dots in columns so ties stay visible instead of overprinting.
  const dots = useMemo(() => {
    const cols = new Map<number, number>()
    const sorted = [...moves].sort((a, b) => a.abs - b.abs)
    return sorted.map((m) => {
      const cx = PAD + (Math.min(m.abs, xmax) / xmax) * (W - 2 * PAD)
      const col = Math.round(cx / (R * 2.1))
      const k = cols.get(col) ?? 0
      cols.set(col, k + 1)
      const lane = k % 2 === 0 ? k / 2 : -(k + 1) / 2
      return { ...m, cx, cy: H / 2 + lane * (R * 2.15) }
    })
  }, [moves, xmax])

  const active = thr ?? implied ?? band ?? null
  const n = moves.length
  const over = active != null ? moves.filter((m) => m.abs > active).length : 0
  const meanAbs = n ? moves.reduce((s, m) => s + m.abs, 0) / n : null
  const overImplied = implied != null ? moves.filter((m) => m.abs > implied).length : null
  const recent = moves.slice(-8)
  const recentMean = recent.length ? recent.reduce((s, m) => s + m.abs, 0) / recent.length : null

  if (!data || n < 4) return null

  const pointer = (clientX: number) => {
    const svg = svgRef.current
    if (!svg) return
    const r = svg.getBoundingClientRect()
    setThr(inv(((clientX - r.left) / r.width) * W))
  }

  const ratio = implied && meanAbs ? meanAbs / implied : null

  return (
    <motion.div className="card straddle" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="straddle__head">
        <h3 className="card-title"><Crosshair size={12} style={{ marginRight: 6, verticalAlign: 'middle' }} />{t('straddle.title')}</h3>
        <span className="straddle__pro">{t('pro.badge.beta')}</span>
      </div>
      <p className="straddle__lede">{t('straddle.lede', { n })}</p>

      <div className="straddle__cells">
        <div><span>{t('straddle.cell.usual')}</span><b>{band != null ? `±${(band * 100).toFixed(1)}%` : '—'}</b></div>
        <div><span>{t('straddle.cell.avg')}</span><b>{meanAbs != null ? `±${(meanAbs * 100).toFixed(1)}%` : '—'}</b>
          {recentMean != null && <i>{t('straddle.cell.recent', { v: (recentMean * 100).toFixed(1) })}</i>}</div>
        <div className="is-amber"><span>{t('straddle.cell.implied')}</span><b>{implied != null ? `±${(implied * 100).toFixed(1)}%` : '—'}</b>
          {overImplied != null && <i>{t('straddle.cell.exceeded', { k: overImplied, n })}</i>}</div>
        <div><span>{t('straddle.cell.ratio')}</span><b>{ratio != null ? `${ratio.toFixed(2)}×` : '—'}</b>
          {ratio != null && <i>{ratio >= 1 ? t('straddle.cell.ratioHi') : t('straddle.cell.ratioLo')}</i>}</div>
      </div>

      <svg
        ref={svgRef}
        className="straddle__plot"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t('straddle.aria', { ticker: data.ticker })}
        onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag(true); pointer(e.clientX) }}
        onPointerMove={(e) => { if (drag || e.pointerType === 'mouse') pointer(e.clientX) }}
        onPointerUp={() => setDrag(false)}
        onPointerLeave={() => { if (!drag) setThr(null) }}
      >
        <line x1={PAD} x2={W - PAD} y1={H / 2} y2={H / 2} className="straddle__axis" />
        {active != null && (
          <rect x={x(active)} y={6} width={Math.max(0, W - PAD - x(active))} height={H - 28} className="straddle__over" />
        )}
        {band != null && <g><line x1={x(band)} x2={x(band)} y1={8} y2={H - 22} className="straddle__band" /><text x={x(band)} y={H - 8} className="straddle__lbl">{t('straddle.lbl.usual')}</text></g>}
        {implied != null && <g><line x1={x(implied)} x2={x(implied)} y1={8} y2={H - 22} className="straddle__implied" /><text x={x(implied)} y={H - 8} className="straddle__lbl straddle__lbl--amber">{t('straddle.lbl.implied')}</text></g>}
        {dots.map((d) => (
          <circle key={d.date} cx={d.cx} cy={d.cy} r={R}
            className={`straddle__dot ${d.move >= 0 ? 'is-up' : 'is-down'}${active != null && d.abs > active ? ' is-over' : ''}`}>
            <title>{`${d.date}: ${d.move >= 0 ? '+' : ''}${(d.move * 100).toFixed(2)}%`}</title>
          </circle>
        ))}
        {active != null && (
          <g pointerEvents="none">
            <line x1={x(active)} x2={x(active)} y1={4} y2={H - 22} className="straddle__thr" />
            <text x={Math.min(x(active) + 6, W - 120)} y={16} className="straddle__thrlbl">±{(active * 100).toFixed(1)}%</text>
          </g>
        )}
        {[0, xmax / 2, xmax].map((v) => <text key={v} x={x(v)} y={H - 22 + 12} className="straddle__tick">{(v * 100).toFixed(0)}%</text>)}
      </svg>

      <p className="straddle__read">
        {active != null && t('straddle.read', { v: (active * 100).toFixed(1), k: over, n, p: Math.round((over / n) * 100) })}
        {thr == null && <span className="tertiary"> {t('straddle.hint')}</span>}
      </p>
      {data.next?.prob_move != null && (
        <p className="straddle__model">
          {t('straddle.model', { p: Math.round(data.next.prob_move * 100), tier: t(`move.${data.next.move_tier ?? 'normal'}` as 'move.normal') })}
        </p>
      )}
      <p className="straddle__fine">{t('straddle.fine')}</p>
    </motion.div>
  )
}
