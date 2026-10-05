import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Headline } from '../types'

/**
 * The live capability figures, fetched once per page load and shared.
 *
 * Copy used to hardcode its accuracy claims ("76.3% vs 60.6%", "59.9% three-class",
 * "47 folds") and every retrain left some page quoting a model that no longer existed.
 * Any sentence that states what the model can do now takes its numbers from here.
 */
let cached: Headline | null = null
let inflight: Promise<Headline | null> | null = null

function load(): Promise<Headline | null> {
  if (cached) return Promise.resolve(cached)
  if (!inflight) {
    inflight = api.getHeadline()
      .then((h) => { cached = h; return h })
      .catch(() => null)
      .finally(() => { inflight = null })
  }
  return inflight
}

export function useHeadline(): Headline | null {
  const [h, setH] = useState<Headline | null>(cached)
  useEffect(() => {
    let alive = true
    if (!cached) load().then((v) => { if (alive) setH(v) })
    return () => { alive = false }
  }, [])
  return h
}

/** 0.6785 -> "68%" ; null -> "—" */
export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? '—' : `${(v * 100).toFixed(digits)}%`
