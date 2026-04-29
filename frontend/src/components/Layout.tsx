import { NavLink, Outlet } from 'react-router-dom'

export function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M16 8.5C14.2 6.3 11.2 5.8 9 7.2C6.8 8.6 6 11.2 7 13.5C8 15.8 10.5 16.8 13 16C14.8 15.4 16 13.8 16 12V18"
                stroke="white" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round"
              />
              <path
                d="M16 16 Q17.5 13.2 19 16 Q20.5 18.8 22 16"
                stroke="rgba(255,255,255,0.55)" strokeWidth="1.6" strokeLinecap="round" fill="none"
              />
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
        <nav className="nav">
          <NavLink to="/" end>Calendar</NavLink>
          <NavLink to="/backtest">Backtest</NavLink>
          <NavLink to="/performance">Performance</NavLink>
          <NavLink to="/simulator">Simulator</NavLink>
          <NavLink to="/track-record">Track Record</NavLink>
          <NavLink to="/about">About</NavLink>
          <NavLink to="/contact">Contact</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
