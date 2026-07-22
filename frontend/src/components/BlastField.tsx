import { useEffect, useRef } from 'react'
import type { CalendarEvent } from '../types'
import { useRenderTier, budgetFor } from '../hooks/useRenderTier'
import { useT } from '../i18n'

/**
 * The calendar as a field of pending detonations.
 *
 * Every upcoming earnings event is a cluster of particles. The model's P(FLAT) sets
 * how tightly that cluster holds together: an event it reads as a non-event is a
 * dense, still knot; one it expects to be violent is a loose, agitated cloud. Depth
 * is time — the nearest earnings sit closest to the camera and drift past as the page
 * scrolls, so the hero is literally the next three months coming at you.
 *
 * The cursor is a repulsor: pushing through the field displaces particles with falloff,
 * and they spring back. That is the whole interaction — no controls, no instructions,
 * and it makes the field feel like a substance rather than a background video.
 *
 * Written against canvas 2D with additive compositing rather than three.js: this is a
 * point cloud with no meshes, materials or lighting, so a 150 KB dependency would buy
 * nothing, and hand-rolling the projection keeps the depth mapping tied to the data.
 */

type Props = { events: CalendarEvent[] }

type Particle = { bx: number; by: number; bz: number; x: number; y: number; vx: number; vy: number; hue: number; seed: number }

export function BlastField({ events }: Props) {
  const { t } = useT()
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const tier = useRenderTier()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || tier === 'still') return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const scored = events.filter((e) => e.direction_prob_flat != null).slice(0, 40)
    if (!scored.length) return

    const perCluster = budgetFor(tier, 26)
    const dprCap = tier === 'full' ? 2 : 1.5

    let w = 0
    let h = 0
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, dprCap)
      const rect = canvas.getBoundingClientRect()
      w = rect.width
      h = rect.height
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    // ResizeObserver, not a one-shot measure. The canvas mounts the moment the render
    // tier resolves from 'still' to 'full', which is before layout has settled, so a
    // single getBoundingClientRect() reads 0x0 and every particle lands off-screen —
    // a live canvas painting nothing, which is exactly what shipped first.
    // Paint on every size change, not just measure. Together with the synchronous
    // first frame this makes the field independent of requestAnimationFrame entirely:
    // whenever the canvas has area, something is on it. rAF then only supplies motion.
    const ro = new ResizeObserver(() => { resize(); drawFrame() })
    ro.observe(canvas)
    resize()

    // Build clusters. z is time-to-earnings, so scrolling moves through the calendar.
    const particles: Particle[] = []
    scored.forEach((e, i) => {
      const quiet = e.direction_prob_flat as number
      // Tight when quiet, diffuse when the model expects a move.
      const spread = 6 + (1 - quiet) * 46
      const cx = (i % 8) / 7
      const cy = Math.floor(i / 8) / Math.max(1, Math.ceil(scored.length / 8) - 1 || 1)
      const cz = i / scored.length
      for (let k = 0; k < perCluster; k++) {
        const a = Math.random() * Math.PI * 2
        const r = Math.pow(Math.random(), 0.55) * spread
        particles.push({
          bx: cx, by: cy, bz: cz,
          x: Math.cos(a) * r, y: Math.sin(a) * r,
          vx: 0, vy: 0,
          hue: quiet,
          seed: Math.random() * 6.283,
        })
      }
    })

    const pointer = { x: -9999, y: -9999 }
    const onMove = (ev: PointerEvent) => {
      const r = canvas.getBoundingClientRect()
      pointer.x = ev.clientX - r.left
      pointer.y = ev.clientY - r.top
    }
    const onLeave = () => { pointer.x = -9999; pointer.y = -9999 }

    let scroll = 0
    const onScroll = () => { scroll = window.scrollY }

    let raf = 0
    let running = true
    let t = 0

    const io = new IntersectionObserver(([entry]) => {
      const was = running
      running = entry.isIntersecting
      if (running && !was) raf = requestAnimationFrame(draw)
    })
    io.observe(canvas)

    function draw() {
      if (!running || document.hidden) return
      if (w < 2 || h < 2) { raf = requestAnimationFrame(draw); return }
      t += 0.006
      drawFrame()
      raf = requestAnimationFrame(draw)
    }

    function drawFrame() {
      if (w < 2 || h < 2) return
      ctx!.clearRect(0, 0, w, h)
      ctx!.globalCompositeOperation = 'lighter'

      // Camera advances with scroll: the calendar comes toward you.
      const camZ = (scroll / 900) % 1

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]
        // Wrap depth so the field is endless in both directions.
        let z = p.bz - camZ
        if (z < 0) z += 1
        const persp = 1 / (0.35 + z * 1.9)

        const cxPix = (0.08 + p.bx * 0.84) * w
        const cyPix = (0.18 + p.by * 0.64) * h
        const breathe = Math.sin(t * 6 + p.seed) * (1 - p.hue) * 3

        let px = cxPix + (p.x + breathe + p.vx) * persp
        let py = cyPix + (p.y + p.vy) * persp

        // Cursor repulsion with spring-back — the field behaves like a substance.
        const dx = px - pointer.x
        const dy = py - pointer.y
        const d2 = dx * dx + dy * dy
        if (d2 < 26000) {
          const f = (1 - d2 / 26000) * 2.4
          p.vx += (dx / (Math.sqrt(d2) + 0.01)) * f
          p.vy += (dy / (Math.sqrt(d2) + 0.01)) * f
        }
        p.vx *= 0.9
        p.vy *= 0.9
        px += p.vx * 0.5
        py += p.vy * 0.5

        const size = Math.max(0.4, persp * (0.7 + p.hue * 0.7))
        // Quiet clusters read cyan and calm; loud ones push toward the warning hue.
        const alpha = Math.min(0.85, persp * 0.5) * (0.45 + p.hue * 0.55)
        ctx!.beginPath()
        ctx!.arc(px, py, size, 0, 6.283)
        ctx!.fillStyle = p.hue >= 0.6
          ? `rgba(56, 189, 248, ${alpha})`
          : p.hue >= 0.45
            ? `rgba(167, 139, 250, ${alpha})`
            : `rgba(251, 191, 36, ${alpha * 0.9})`
        ctx!.fill()
      }

      ctx!.globalCompositeOperation = 'source-over'
    }

    window.addEventListener('resize', resize)
    window.addEventListener('scroll', onScroll, { passive: true })
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerleave', onLeave)

    // Paint frame one synchronously. requestAnimationFrame does not fire while the
    // document is hidden — a background tab, a throttled window, some low-power modes —
    // so scheduling the first frame through rAF leaves the canvas blank until the page
    // is looked at. Drawing once up front means the field is always there on arrival
    // and the loop only ever adds motion.
    drawFrame()
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      io.disconnect()
      ro.disconnect()
      window.removeEventListener('resize', resize)
      window.removeEventListener('scroll', onScroll)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerleave', onLeave)
    }
  }, [events, tier])

  const scored = events.filter((e) => e.direction_prob_flat != null)
  const quiet = scored.filter((e) => (e.direction_prob_flat as number) >= 0.6).length
  const loud = scored.filter((e) => (e.direction_prob_flat as number) <= 0.4).length

  return (
    <div className="blast">
      {tier !== 'still' && <canvas ref={canvasRef} className="blast__canvas" aria-hidden="true" />}
      <div className="blast__overlay">
        <h1 className="blast__title">{t('cal.hero.title')}</h1>
        <p className="blast__sub">{t('cal.hero.sub', { n: scored.length })}</p>
        <div className="blast__stats">
          <span><b>{scored.length}</b> {t('cal.tracked')}</span>
          <span><b>{quiet}</b> {t('cal.readsQuiet')}</span>
          <span><b>{loud}</b> {t('cal.readsLoud')}</span>
        </div>
      </div>
    </div>
  )
}
