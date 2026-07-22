import { useEffect, useRef } from 'react'
import { useRenderTier } from '../hooks/useRenderTier'
import { useT } from '../i18n'

/**
 * Concept F — the IV crush chamber, for a single stock's deep dive.
 *
 * This draws the one mechanic an options seller is actually trading. Implied vol
 * climbs into a print because nobody knows what the number will be; the moment it is
 * published the uncertainty is gone and IV collapses, regardless of which way the
 * stock went. That collapse is where premium sellers make their money, and it is the
 * one thing this model speaks to — it estimates whether the move will justify the vol
 * being priced in.
 *
 * So: a vessel that visibly strains as the date approaches, and either ruptures (the
 * move broke the band) or sighs (it did not). Pressure is days-to-earnings scaled by
 * the expected move; the release is decided by the model's own quiet score.
 */

type Props = {
  /** Days until the print. Negative once it has happened. */
  daysUntil: number
  /** Model's expected absolute move, as a fraction. */
  expectedMove: number
  /** P(FLAT) — decides whether the vessel sighs or ruptures. */
  quiet: number
}

export function CrushChamber({ daysUntil, expectedMove, quiet }: Props) {
  const { t } = useT()
  const ref = useRef<HTMLCanvasElement | null>(null)
  const tier = useRenderTier()

  useEffect(() => {
    if (tier === 'still') return
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0
    let h = 0
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const r = canvas.getBoundingClientRect()
      w = r.width
      h = r.height
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      paint(0)
    }

    // Pressure: full at the print, easing off the further out we are. A bigger
    // expected move means more vol priced in, so the vessel starts more loaded.
    const proximity = Math.max(0, Math.min(1, 1 - Math.min(daysUntil, 30) / 30))
    const load = Math.max(0.12, Math.min(1, proximity * (0.5 + Math.min(expectedMove, 0.12) * 5)))
    const ruptures = quiet < 0.5

    let t = 0
    function paint(time: number) {
      if (w < 2 || h < 2) return
      ctx!.clearRect(0, 0, w, h)
      const cx = w / 2
      const cy = h / 2

      // Release cycle: strain, then let go, then reset.
      const cycle = (time % 7) / 7
      const strain = cycle < 0.78 ? cycle / 0.78 : 0
      const release = cycle >= 0.78 ? (cycle - 0.78) / 0.22 : 0
      const p = load * (0.55 + strain * 0.45)

      const rw = Math.min(w * 0.34, 120) * (1 + p * 0.16)
      const rh = Math.min(h * 0.3, 74) * (1 + p * 0.11)

      // Vessel walls — more rings and more glow the harder it is loaded.
      for (let k = 3; k >= 0; k--) {
        ctx!.beginPath()
        ctx!.ellipse(cx, cy, rw + k * 6, rh + k * 5, 0, 0, Math.PI * 2)
        ctx!.strokeStyle = `rgba(56, 189, 248, ${0.42 - k * 0.09 + p * 0.28})`
        ctx!.lineWidth = k === 0 ? 2 : 1
        ctx!.stroke()
      }

      // Contained particles, agitating with pressure.
      const n = tier === 'full' ? 16 : 7
      for (let s = 0; s < n; s++) {
        const a = (s / n) * Math.PI * 2 + time * 0.5
        const jitter = Math.sin(time * 5 + s) * p * 5
        const px = cx + Math.cos(a) * (rw * 0.72 + jitter)
        const py = cy + Math.sin(a) * (rh * 0.72 + jitter)
        ctx!.beginPath()
        ctx!.arc(px, py, 1.6 + p * 2, 0, Math.PI * 2)
        ctx!.fillStyle = p > 0.72 ? 'rgba(251, 191, 36, 0.75)' : 'rgba(167, 139, 250, 0.6)'
        ctx!.fill()
      }

      // The release. A rupture throws the contents outward; a sigh exhales gently
      // inward — the same event, told two different ways by the model's own call.
      if (release > 0) {
        const count = ruptures ? 26 : 14
        for (let b = 0; b < count; b++) {
          const a = (b / count) * Math.PI * 2
          const dist = ruptures ? release * Math.min(w, h) * 0.55 : (1 - release) * rw * 0.9
          ctx!.beginPath()
          ctx!.arc(cx + Math.cos(a) * dist, cy + Math.sin(a) * dist * 0.72, (ruptures ? 2.6 : 1.8) * (1 - release), 0, Math.PI * 2)
          ctx!.fillStyle = ruptures
            ? `rgba(251, 113, 133, ${1 - release})`
            : `rgba(52, 211, 153, ${(1 - release) * 0.8})`
          ctx!.fill()
        }
      }

      ctx!.font = '600 10px ui-monospace, monospace'
      ctx!.textAlign = 'center'
      ctx!.fillStyle = 'rgba(148, 163, 214, 0.8)'
      const label = release > 0
        ? (ruptures ? 'BREAKS THE BAND' : 'VOL COLLAPSES')
        : `IV LOAD ${Math.round(p * 100)}%`
      ctx!.fillText(label, cx, h - 10)
    }

    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()

    let raf = 0
    let running = true
    const io = new IntersectionObserver(([e]) => {
      const was = running
      running = e.isIntersecting
      if (running && !was) raf = requestAnimationFrame(loop)
    })
    io.observe(canvas)

    function loop() {
      if (!running || document.hidden) return
      t += 0.016
      paint(t)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
    }
  }, [tier, daysUntil, expectedMove, quiet])

  return (
    <div className="chamber">
      {tier !== 'still' && <canvas ref={ref} className="chamber__canvas" aria-hidden="true" />}
      <div className="chamber__meta">
        <span className="chamber__kicker">{t('crush.ivInto')}</span>
        <p className="chamber__copy">
          Vol builds while the number is unknown and collapses the moment it is published,
          whichever way the stock goes. The model reads this one as{' '}
          <b>{quiet >= 0.6 ? 'likely to stay inside its band' : quiet >= 0.5 ? 'borderline' : 'likely to break out'}</b>.
        </p>
      </div>
    </div>
  )
}
