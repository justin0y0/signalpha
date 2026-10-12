import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { LayoutGroup, motion } from 'framer-motion'
import { Menu, Search, X } from 'lucide-react'
import { LocaleToggle } from './ui/LocaleToggle'
import { useT } from '../i18n'
import { AuthWidget } from './AuthWidget'
import { RouteBoundary } from './RouteBoundary'
import { Tape } from './Tape'
import { CommandPalette } from './CommandPalette'
import { JourneyRail } from './JourneyRail'
import { useBuildCheck } from '../hooks/useBuildCheck'
import { useSpotlight } from '../hooks/useSpotlight'
import { DESKS, JOURNEY, META } from '../lib/journey'

/**
 * The shell every page lives in: masthead, tape, page, journey rail.
 *
 * Navigation is grouped by what the pages are — the five-step earnings loop (numbered,
 * because order is the point), the two side desks, and the meta pages — instead of
 * nine equal tabs.
 */

function marketClock(now: Date): { label: string; cls: string } {
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const mins = et.getHours() * 60 + et.getMinutes()
  const wk = et.getDay() >= 1 && et.getDay() <= 5
  const hhmm = et.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (wk && mins >= 570 && mins < 960) return { label: `${hhmm} ET · OPEN`, cls: 'is-open' }
  if (wk && ((mins >= 240 && mins < 570) || (mins >= 960 && mins < 1200))) return { label: `${hhmm} ET · EXT`, cls: 'is-ext' }
  return { label: `${hhmm} ET · CLOSED`, cls: '' }
}

export function Layout() {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [palette, setPalette] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const location = useLocation()
  useBuildCheck()
  useSpotlight()

  useEffect(() => { setOpen(false); window.scrollTo({ top: 0 }) }, [location.pathname])
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(id) }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p) }
      else if (e.key === '/' && !/input|textarea|select/i.test((e.target as HTMLElement)?.tagName ?? '')) { e.preventDefault(); setPalette(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const clock = marketClock(now)
  const all = [...JOURNEY, ...DESKS, ...META]

  const link = (l: { to: string; nav: string; step?: string }) => (
    <NavLink key={l.to} to={l.to} end={l.to === '/'}>
      {({ isActive }) => (
        <>
          {l.step && <span className="nav__step">{l.step}</span>}
          {t(l.nav as 'nav.calendar')}
          {isActive && <motion.span layoutId="nav-ink" className="nav__ink" transition={{ type: 'spring', stiffness: 520, damping: 40 }} />}
        </>
      )}
    </NavLink>
  )

  return (
    <div className="app-shell">
      <header className="masthead">
        <div className="masthead__row">
          <NavLink to="/" className="brand" aria-label="SignAlpha">
            <div className="brand-mark">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M2 14 H8 L10 9 L13 19 L15.5 5 L17.5 14 H22" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="brand-name">
              <span className="brand-name__sign">Sign</span><span className="brand-name__al">Alpha</span>
            </div>
          </NavLink>

          <LayoutGroup>
            <nav className="nav" aria-label="Primary">
              {JOURNEY.map(link)}
              <span className="nav__sep" />
              {DESKS.map(link)}
              <span className="nav__sep" />
              {META.map(link)}
            </nav>
          </LayoutGroup>

          <div className="masthead__right">
            <span className={`mast-clock ${clock.cls}`}><i />{clock.label}</span>
            <button type="button" className="kbd-btn" onClick={() => setPalette(true)} aria-label={t('cmdk.aria')}>
              <Search size={13} /> <span className="kbd-btn__txt">{t('cmdk.button')}</span> <kbd>⌘K</kbd>
            </button>
            <LocaleToggle />
            <AuthWidget />
            <button className="nav-burger" onClick={() => setOpen((o) => !o)} aria-label="Menu">
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
        <Tape />
      </header>

      {open && <div className="nav-overlay" onClick={() => setOpen(false)} />}
      <nav className={`nav--mobile ${open ? 'nav--mobile-open' : ''}`}>
        <div className="nav--mobile-inner">
          <button type="button" className="nav--mobile-search" onClick={() => { setOpen(false); setPalette(true) }}>
            <Search size={15} /> {t('cmdk.button')}
          </button>
          {all.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === '/'} className="nav--mobile-link">
              {'step' in l && <span className="nav__step">{l.step}</span>}{t(l.nav as 'nav.calendar')}
            </NavLink>
          ))}
          <div className="nav--mobile-foot"><LocaleToggle /></div>
        </div>
      </nav>

      <main className="app-main">
        <RouteBoundary key={location.pathname}>
          <div className="route-enter" key={location.pathname}>
            <Outlet />
            <JourneyRail />
          </div>
        </RouteBoundary>
      </main>

      <footer className="colophon">
        <span className="serif">SignAlpha</span>
        <span>{t('footer.line')}</span>
        <NavLink to="/contact">{t('nav.contact')}</NavLink>
      </footer>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  )
}
