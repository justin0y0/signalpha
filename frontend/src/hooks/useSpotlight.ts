import { useEffect } from 'react'

/**
 * Cursor spotlight for every card on the site, from one listener.
 *
 * Writes --mx / --my (pixels inside the hovered surface) onto the nearest .card or
 * .stat-card; the CSS in index.css turns that into a soft highlight under the pointer.
 * rAF-throttled, pointer-fine only, off under reduced motion.
 */
export function useSpotlight() {
  useEffect(() => {
    if (!window.matchMedia('(pointer: fine)').matches) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    let last: PointerEvent | null = null
    const paint = () => {
      raf = 0
      if (!last) return
      const el = (last.target as Element | null)?.closest?.('.card, .stat-card') as HTMLElement | null
      if (!el) return
      const r = el.getBoundingClientRect()
      el.style.setProperty('--mx', `${last.clientX - r.left}px`)
      el.style.setProperty('--my', `${last.clientY - r.top}px`)
    }
    const move = (e: PointerEvent) => { last = e; if (!raf) raf = requestAnimationFrame(paint) }
    document.addEventListener('pointermove', move, { passive: true })
    return () => { document.removeEventListener('pointermove', move); if (raf) cancelAnimationFrame(raf) }
  }, [])
}
