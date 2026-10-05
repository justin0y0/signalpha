import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Notices when a newer frontend has been deployed and moves the tab onto it.
 *
 * Vite fingerprints the entry bundle (/assets/index-<hash>.js), so comparing the one
 * this tab booted with against the one the server's index.html now references is an
 * exact "is there a new build" test. When there is, the next in-app navigation becomes
 * a full page load of the same URL — the visitor was changing page anyway, so the
 * reload costs nothing and they never sit on a bundle the API no longer matches.
 *
 * Checked at most every 5 minutes, and only on navigation, so an idle tab makes no
 * requests at all.
 */

const ENTRY = /\/assets\/index-[\w-]+\.js/
const INTERVAL_MS = 5 * 60 * 1000

function currentEntry(): string | null {
  for (const s of Array.from(document.scripts)) {
    const m = s.src.match(ENTRY)
    if (m) return m[0]
  }
  return null
}

export async function newerBuildAvailable(): Promise<boolean> {
  const mine = currentEntry()
  if (!mine) return false // dev server: no fingerprinted entry
  try {
    const r = await fetch('/', { cache: 'no-store', headers: { Accept: 'text/html' } })
    if (!r.ok) return false
    const live = (await r.text()).match(ENTRY)?.[0]
    return !!live && live !== mine
  } catch {
    return false
  }
}

export function useBuildCheck() {
  const { pathname } = useLocation()
  const stale = useRef(false)
  const lastCheck = useRef(Date.now())
  const first = useRef(true)

  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (stale.current) { window.location.reload(); return }
    if (Date.now() - lastCheck.current < INTERVAL_MS) return
    lastCheck.current = Date.now()
    newerBuildAvailable().then((newer) => { if (newer) stale.current = true })
  }, [pathname])
}
