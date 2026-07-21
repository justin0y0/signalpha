import { useEffect, useState } from 'react'

/**
 * How much visual work this device should be asked to do.
 *
 * Four pages are getting WebGL scenes at once. Without a gate that means a mid-range
 * phone runs a particle field, a fluid shader and a physics rope, and the site becomes
 * unusable on exactly the hardware most visitors have. Every scene reads this and
 * degrades on its own terms rather than each one inventing its own heuristic.
 *
 *   full  — discrete-ish GPU, wide viewport: the real thing
 *   lite  — mobile or modest hardware: fewer particles, no post-processing, capped DPR
 *   still — prefers-reduced-motion, no WebGL, or a device that failed the probe:
 *           a static rendering carrying the same information
 *
 * `still` must always be a complete experience, never an empty box. Someone with
 * vestibular sensitivity should get the data, just not the movement.
 */

export type RenderTier = 'full' | 'lite' | 'still'

function probe(): RenderTier {
  if (typeof window === 'undefined') return 'still'

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 'still'

  // Save-Data is an explicit request not to burn the user's bandwidth.
  const conn = (navigator as unknown as { connection?: { saveData?: boolean } }).connection
  if (conn?.saveData) return 'still'

  let gl: WebGLRenderingContext | null = null
  try {
    const canvas = document.createElement('canvas')
    gl = (canvas.getContext('webgl2') || canvas.getContext('webgl')) as WebGLRenderingContext | null
  } catch {
    return 'still'
  }
  if (!gl) return 'still'

  const cores = navigator.hardwareConcurrency ?? 4
  const memory = (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? 4
  const narrow = window.matchMedia('(max-width: 820px)').matches
  const coarse = window.matchMedia('(pointer: coarse)').matches

  if (narrow || coarse || cores <= 4 || memory <= 4) return 'lite'
  return 'full'
}

export function useRenderTier(): RenderTier {
  const [tier, setTier] = useState<RenderTier>('still')

  useEffect(() => {
    setTier(probe())
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setTier(probe())
    mq.addEventListener('change', onChange)
    window.addEventListener('resize', onChange)
    return () => {
      mq.removeEventListener('change', onChange)
      window.removeEventListener('resize', onChange)
    }
  }, [])

  return tier
}

/** Particle/sample budget for a scene, scaled to the tier. */
export function budgetFor(tier: RenderTier, full: number): number {
  if (tier === 'full') return full
  if (tier === 'lite') return Math.round(full * 0.35)
  return 0
}
