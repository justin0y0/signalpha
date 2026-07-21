import { useEffect, useRef } from 'react'
import type { CalendarEvent } from '../types'

/**
 * The hero: a chart-recorder trace driven by real upcoming earnings.
 *
 * This is the product drawn as the instrument it is named after. Each upcoming event
 * is a stylus deflection whose amplitude is (1 - P(FLAT)) — the model's own estimate of
 * how much is about to happen. Events it reads as non-events barely move the pen;
 * events it expects to be violent spike it. Nothing is asserted about direction,
 * because the model has no directional skill; only magnitude is drawn, which is the
 * one thing it measures.
 *
 * Canvas rather than SVG: the trace is regenerated per frame and hand-authoring that
 * much path data would be both slower and unreadable.
 */

type Props = { events: CalendarEvent[] }

export function Recorder({ events }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const raf = useRef<number>(0)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const css = getComputedStyle(document.documentElement)
    const stylus = css.getPropertyValue('--stylus').trim() || '#E2703A'
    const trace = css.getPropertyValue('--trace').trim() || '#7FA99B'
    const grid = 'rgba(127,169,155,0.10)'

    // Deflection per event: how much the model expects to happen.
    const scored = events.filter((e) => e.direction_prob_flat != null)
    const amps = scored.length
      ? scored.slice(0, 64).map((e) => 1 - (e.direction_prob_flat as number))
      : [0.2, 0.18, 0.22, 0.19]

    let t = 0
    let width = 0
    let height = 0

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    // Pause when the canvas is off-screen or the tab is hidden. An unthrottled rAF
    // that redraws forever pegs the renderer on a page the reader has scrolled past —
    // which is exactly what made scrolling stutter on first deploy.
    let visible = true
    const io = new IntersectionObserver(([e]) => {
      const wasHidden = !visible
      visible = e.isIntersecting
      if (visible && wasHidden && !reduced) raf.current = requestAnimationFrame(draw)
    }, { threshold: 0 })
    io.observe(canvas)
    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf.current)
      else if (visible && !reduced) raf.current = requestAnimationFrame(draw)
    }
    document.addEventListener('visibilitychange', onVisibility)

    const draw = () => {
      ctx.clearRect(0, 0, width, height)
      const mid = height / 2

      // Paper: faint horizontal rules, like a recorder's pre-printed chart.
      ctx.strokeStyle = grid
      ctx.lineWidth = 1
      for (let i = 1; i < 6; i++) {
        const y = (height / 6) * i
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }

      // The trace. Amplitude comes from the data; the wobble is carrier noise so a
      // quiet stretch still looks like a live pen rather than a dead line.
      ctx.beginPath()
      ctx.lineWidth = 1.6
      ctx.strokeStyle = stylus
      ctx.shadowColor = stylus
      ctx.shadowBlur = 7
      const step = width / 240
      for (let i = 0; i <= 240; i++) {
        const x = i * step
        const pos = (i + t) / 240
        const amp = amps[Math.floor(Math.abs(pos * amps.length)) % amps.length]
        const envelope = Math.exp(-Math.pow(((i + t) % 40) - 20, 2) / 90)
        const carrier = Math.sin((i + t) * 0.32) * 0.9 + Math.sin((i + t) * 0.11) * 0.5
        const y = mid - carrier * amp * envelope * (height * 0.42) - Math.sin(i * 0.05) * 1.5
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
      ctx.shadowBlur = 0

      // Baseline: where the pen rests when nothing is expected.
      ctx.strokeStyle = trace
      ctx.globalAlpha = 0.35
      ctx.setLineDash([3, 5])
      ctx.beginPath()
      ctx.moveTo(0, mid)
      ctx.lineTo(width, mid)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.globalAlpha = 1

      if (!reduced && visible && !document.hidden) {
        t += 0.55
        raf.current = requestAnimationFrame(draw)
      }
    }
    draw()

    return () => {
      cancelAnimationFrame(raf.current)
      io.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', resize)
    }
  }, [events])

  const scored = events.filter((e) => e.direction_prob_flat != null)
  const quiet = scored.filter((e) => (e.direction_prob_flat as number) >= 0.6).length
  const loud = scored.filter((e) => (e.direction_prob_flat as number) <= 0.4).length

  return (
    <div className="recorder">
      <canvas ref={ref} className="recorder__canvas" aria-hidden="true" />
      <div className="recorder__meta">
        <span className="recorder__legend">
          <i className="recorder__swatch" style={{ background: 'var(--stylus)' }} />
          deflection = 1 − P(flat)
        </span>
        <span>tracking <b>{scored.length}</b></span>
        <span>reads quiet <b>{quiet}</b></span>
        <span>reads loud <b>{loud}</b></span>
      </div>
    </div>
  )
}
