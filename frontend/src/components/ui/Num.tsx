import { useEffect, useRef, useState } from 'react'

/**
 * A number that counts up to its value when it first appears, and glides when it
 * changes. Formatting is the caller's (`format`), so percentages, prices and counts
 * all share one motion.
 */
type Props = { value: number | null | undefined; format?: (v: number) => string; duration?: number; className?: string }

const still = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function Num({ value, format = (v) => Math.round(v).toLocaleString(), duration = 900, className }: Props) {
  const [shown, setShown] = useState<number | null>(value == null ? null : still() ? value : 0)
  const from = useRef(0)
  useEffect(() => {
    if (value == null || !Number.isFinite(value)) { setShown(null); return }
    if (still()) { setShown(value); from.current = value; return }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const e = 1 - Math.pow(1 - t, 4)
      setShown(a + (value - a) * e)
      if (t < 1) raf = requestAnimationFrame(tick)
      else from.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); from.current = value }
  }, [value, duration])
  return <span className={className}>{shown == null ? '—' : format(shown)}</span>
}
