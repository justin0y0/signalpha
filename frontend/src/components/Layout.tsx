import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { AuthWidget } from './AuthWidget'

export function Layout() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => { setOpen(false) }, [location.pathname])

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  const links = [
    // Eleven entries collapsed to seven. Backtest/Performance/Simulator/Track
    // Record/Showdown were five views of one ML signal; they now live as sections
    // under Model and Strategy (see ModelPage.tsx / StrategyPage.tsx). The old paths
    // still resolve via redirects in App.tsx.
    { to: '/', label: 'Calendar', end: true },
    { to: '/model', label: 'Model' },
    { to: '/strategy', label: 'Strategy' },
    { to: '/pulse', label: 'Pulse' },
    { to: '/oracle', label: 'Oracle' },
    { to: '/about', label: 'About' },
    { to: '/contact', label: 'Contact' },
  ]

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M16 8.5C14.2 6.3 11.2 5.8 9 7.2C6.8 8.6 6 11.2 7 13.5C8 15.8 10.5 16.8 13 16C14.8 15.4 16 13.8 16 12V18"
                stroke="white" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M16 16 Q17.5 13.2 19 16 Q20.5 18.8 22 16"
                stroke="rgba(255,255,255,0.55)" strokeWidth="1.6" strokeLinecap="round" fill="none"/>
            </svg>
          </div>
          <div>
            <div className="brand-name">
              <span className="brand-name__sign">Sign</span>
              <span className="brand-name__al">al</span>
              <span className="brand-name__pha">pha</span>
            </div>
            <div className="brand-tag">Signal · Alpha · ML</div>
          </div>
        </NavLink>

        {/* Desktop nav */}
        <nav className="nav">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} end={l.end}>{l.label}</NavLink>
          ))}
        </nav>

        <AuthWidget />

        {/* Mobile hamburger */}
        <button className="nav-burger" onClick={() => setOpen(o => !o)} aria-label="Menu">
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      {/* Mobile drawer overlay */}
      {open && (
        <div className="nav-overlay" onClick={() => setOpen(false)} />
      )}

      {/* Mobile drawer */}
      <nav className={`nav--mobile ${open ? 'nav--mobile-open' : ''}`}>
        <div className="nav--mobile-inner">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} end={l.end} className="nav--mobile-link">
              {l.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
