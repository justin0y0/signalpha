import { useEffect, useRef } from 'react'

/**
 * A stylus that tracks scroll position down the left edge, the way chart paper feeds
 * past a pen. Ambient only — it carries no data, so it is hidden from assistive tech
 * and held still when the viewer prefers reduced motion.
 *
 * Written against the DOM rather than React state on purpose: this updates on every
 * scroll frame, and routing it through a re-render would make the whole page pay for
 * a decoration.
 */
export function FeedRail() {
  const dot = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let ticking = false
    const update = () => {
      ticking = false
      const el = dot.current
      if (!el) return
      const max = document.documentElement.scrollHeight - window.innerHeight
      const pct = max > 0 ? window.scrollY / max : 0
      el.style.top = `${8 + pct * 84}%`
    }
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return (
    <div className="feed-rail" aria-hidden="true">
      <div ref={dot} className="feed-rail__stylus" style={{ top: '8%' }} />
    </div>
  )
}
