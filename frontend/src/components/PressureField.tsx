import { useEffect, useRef } from 'react'
import { useRenderTier } from '../hooks/useRenderTier'

/**
 * Concept C — ambient turbulence behind the Pulse page, driven by live market state.
 *
 * Pulse is the intraday scanner: its whole subject is how agitated the market is right
 * now. So the background is not decoration here, it is the same number the page is
 * already reporting. Breadth and average volatility set the amplitude and speed of a
 * layered flow field — a calm tape barely moves, a violent one churns.
 *
 * Deliberately low-contrast and behind everything: it must never compete with a number
 * someone is trying to read. On the still tier it renders nothing at all, and the page
 * loses only atmosphere.
 */

type Props = {
  /** 0..1 — how agitated the tape is. Drives amplitude and speed. */
  intensity: number
}

export function PressureField({ intensity }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const tier = useRenderTier()
  const intensityRef = useRef(intensity)
  intensityRef.current = intensity

  useEffect(() => {
    if (tier === 'still') return
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const lines = tier === 'full' ? 22 : 10
    const step = tier === 'full' ? 6 : 12

    let w = 0
    let h = 0
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, tier === 'full' ? 2 : 1.5)
      const r = canvas.getBoundingClientRect()
      w = r.width
      h = r.height
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      paint()
    }

    let t = 0
    function paint() {
      if (w < 2 || h < 2) return
      // Floor the intensity: a dead-calm tape should still show a living field.
      const k = Math.min(1, Math.max(0.22, intensityRef.current))
      ctx!.clearRect(0, 0, w, h)
      for (let i = 0; i < lines; i++) {
        const y0 = (h / (lines - 1)) * i
        ctx!.beginPath()
        for (let x = 0; x <= w; x += step) {
          const a = Math.sin(x * 0.004 + t + i * 0.4) * (10 + k * 46)
          const b = Math.sin(x * 0.0012 - t * 1.5 + i * 0.19) * (14 + k * 30)
          const y = y0 + a * 0.5 + b * 0.5
          if (x === 0) ctx!.moveTo(x, y)
          else ctx!.lineTo(x, y)
        }
        // Calm tape reads cool and thin; agitation warms and thickens it.
        //
        // The first pass peaked at alpha 13/255 — technically present, visually absent.
        // Ambient does not mean invisible: the field has to be legible as motion while
        // still losing to any number on top of it.
        const alpha = 0.16 + k * 0.30
        ctx!.strokeStyle = k > 0.55
          ? `rgba(251, 191, 36, ${alpha})`
          : `rgba(56, 189, 248, ${alpha})`
        ctx!.lineWidth = 1 + k * 1.4
        ctx!.shadowColor = k > 0.55 ? 'rgba(251,191,36,0.5)' : 'rgba(56,189,248,0.5)'
        ctx!.shadowBlur = 6 + k * 10
        ctx!.stroke()
        ctx!.shadowBlur = 0
      }
    }

    // Paint on size, not only on rAF: a background tab or a throttled window must
    // still show the field rather than an empty rectangle.
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
      t += 0.002 + intensityRef.current * 0.006
      paint()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
    }
  }, [tier])

  if (tier === 'still') return null
  return <canvas ref={ref} className="pressure" aria-hidden="true" />
}
