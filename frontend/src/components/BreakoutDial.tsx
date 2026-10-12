import type { CSSProperties } from 'react'
import { useT } from '../i18n'

/**
 * Breakout risk as an instrument: a half-dial with a needle.
 *
 * The scale is 30%–90% because that is where every score the model has ever produced
 * lives; a 0–100 dial would park the needle near the middle for every stock. The tick
 * on the rim is the base rate, so the reading is "how far past ordinary", and the arc
 * between the two is filled only when the report is above it.
 */
type Props = { prob: number | null | undefined; tier?: 'breakout' | 'elevated' | 'normal' | null; base?: number | null }

const LO = 0.3
const HI = 0.9
const CX = 150
const CY = 150
const R = 118

const ang = (p: number) => Math.PI * (1 - Math.max(0, Math.min(1, (p - LO) / (HI - LO))))
const pt = (p: number, r = R) => [CX + r * Math.cos(ang(p)), CY - r * Math.sin(ang(p))] as const
const arc = (a: number, b: number, r = R) => {
  const [x1, y1] = pt(a, r); const [x2, y2] = pt(b, r)
  return `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`
}

export function BreakoutDial({ prob, tier, base }: Props) {
  const { t } = useT()
  const p = prob ?? null
  const tone = tier === 'breakout' ? 'hot' : tier === 'elevated' ? 'warm' : 'calm'
  const deg = p == null ? -90 : 90 - (ang(p) * 180) / Math.PI
  return (
    <div className={`dial is-${tone}`}>
      <div className="dial__face">
        <svg viewBox="0 0 300 160" role="img" aria-label={p != null ? t('dial.aria', { p: (p * 100).toFixed(0) }) : t('move.unscored')}>
          <path d={arc(LO, HI)} className="dial__track" />
          {[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((v) => {
            const [x1, y1] = pt(v, R + 7); const [x2, y2] = pt(v, R + 13); const [tx, ty] = pt(v, R + 25)
            return <g key={v}><line x1={x1} y1={y1} x2={x2} y2={y2} className="dial__tick" /><text x={tx} y={ty + 3} className="dial__lbl">{Math.round(v * 100)}</text></g>
          })}
          {base != null && p != null && p > base && <path d={arc(base, p)} className="dial__fill" pathLength={1} />}
          {base != null && (() => {
            const [x1, y1] = pt(base, R - 12); const [x2, y2] = pt(base, R + 12)
            return <line x1={x1} y1={y1} x2={x2} y2={y2} className="dial__base" />
          })()}
          {p != null && (
            // A rim pointer, not a full needle: the bowl of the arc is where the number sits.
            <g className="dial__needle" style={{ '--deg': `${deg}deg` } as CSSProperties}>
              <path d={`M${CX} ${CY - R - 5} L${CX - 5.5} ${CY - R + 24} L${CX + 5.5} ${CY - R + 24} Z`} />
            </g>
          )}
        </svg>
        <b className="dial__num serif">{p != null ? `${(p * 100).toFixed(0)}%` : '—'}</b>
      </div>
      <div className="dial__read">
        <span className="dial__tier">{t(`move.${tier ?? 'unscored'}` as 'move.normal')}</span>
        {base != null && <span className="dial__basetxt">{t('dial.base', { v: (base * 100).toFixed(0) })}</span>}
      </div>
    </div>
  )
}
