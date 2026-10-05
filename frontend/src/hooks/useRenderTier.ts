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

// WebGL availability is probed ONCE per page load and the probe context is released
// immediately. This hook runs in every Superposition row on the calendar, and each call
// used to create a fresh WebGL context — on every resize too. Browsers cap live contexts
// at ~16 and silently kill the oldest ("Too many active WebGL contexts"), which is how
// a calendar render could knock out the real scenes on the same page.
let webglAvailable: boolean | null = null
function hasWebGL(): boolean {
  if (webglAvailable !== null) return webglAvailable
  try {
    const canvas = document.createElement('canvas')
    const gl = (canvas.getContext('webgl2') || canvas.getContext('webgl')) as WebGLRenderingContext | null
    webglAvailable = !!gl
    gl?.getExtension('WEBGL_lose_context')?.loseContext()
  } catch {
    webglAvailable = false
  }
  return webglAvailable
}

function probe(): RenderTier {
  if (typeof window === 'undefined') return 'still'

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 'still'

  // Save-Data is an explicit request not to burn the user's bandwidth.
  const conn = (navigator as unknown as { connection?: { saveData?: boolean } }).connection
  if (conn?.saveData) return 'still'

  if (!hasWebGL()) return 'still'

  const cores = navigator.hardwareConcurrency ?? 4
  const memory = (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? 4
  const narrow = window.matchMedia('(max-width: 820px)').matches
  const coarse = window.matchMedia('(pointer: coarse)').matches

  if (narrow || coarse || cores <= 4 || memory <= 4) return 'lite'
  return 'full'
}

// One shared tier and one set of listeners for the whole app, however many
// components ask for it.
let currentTier: RenderTier | null = null
const subscribers = new Set<(t: RenderTier) => void>()
let listening = false
function startListening() {
  if (listening || typeof window === 'undefined') return
  listening = true
  let timer = 0
  const recompute = () => {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      const next = probe()
      if (next === currentTier) return
      currentTier = next
      subscribers.forEach((fn) => fn(next))
    }, 150)
  }
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', recompute)
  window.addEventListener('resize', recompute)
}

export function useRenderTier(): RenderTier {
  const [tier, setTier] = useState<RenderTier>(currentTier ?? 'still')

  useEffect(() => {
    if (currentTier === null) currentTier = probe()
    setTier(currentTier)
    subscribers.add(setTier)
    startListening()
    return () => {
      subscribers.delete(setTier)
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
