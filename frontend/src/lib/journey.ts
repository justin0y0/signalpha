/**
 * The earnings loop, in the order a report actually happens.
 *
 * The site's pages are not a flat list: five of them are one story told in sequence —
 * what is coming, what matters this week, what everyone called, what to do after the
 * number is out, having it done for you, and whether any of it works. Navigation, page headers and the rail at
 * the foot of each page all read this one list, so the numbering can never drift.
 */
export const JOURNEY = [
  { to: '/', key: 'calendar', nav: 'nav.calendar', step: '01', phase: 'journey.before' },
  { to: '/brief', key: 'brief', nav: 'nav.brief', step: '02', phase: 'journey.before' },
  { to: '/arena', key: 'arena', nav: 'nav.arena', step: '03', phase: 'journey.call' },
  { to: '/strategy', key: 'strategy', nav: 'nav.strategy', step: '04', phase: 'journey.after' },
  { to: '/autopilot', key: 'autopilot', nav: 'nav.autopilot', step: '05', phase: 'journey.act' },
  { to: '/model', key: 'model', nav: 'nav.model', step: '06', phase: 'journey.proof' },
] as const

// Pulse (/pulse) is off the menu since 2026-10-21: its intraday signals were backtested on
// the consolidated tape and lose before costs (Autopilot → strategy lab). The page stays
// reachable for old links, with that verdict on top.
export const DESKS = [
  { to: '/markets', nav: 'nav.markets' },
  { to: '/oracle', nav: 'nav.oracle' },
] as const

export const META = [
  { to: '/about', nav: 'nav.about' },
  { to: '/pro', nav: 'nav.pro' },
] as const

export function journeyIndex(pathname: string): number {
  if (pathname === '/') return 0
  return JOURNEY.findIndex((j, i) => i > 0 && pathname.startsWith(j.to))
}
