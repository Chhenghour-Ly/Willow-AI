import { useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { HOTLINE, formatPhone } from '../data'

export function SiteLayout() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])

  return (
    <div className="site">
      <header className="nav-wrap">
        <nav className="nav" aria-label="Main">
          <Link to="/" className="brand">
            <img src="/img/mark.png" alt="" width="26" height="29" />
            <span>Willow</span>
          </Link>
          <div className="nav-links">
            <NavLink to="/about">About</NavLink>
          </div>
          <a className="btn btn-dark nav-call" href={`tel:${HOTLINE}`}>Call now</a>
        </nav>
      </header>
      <Outlet />
      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-top">
            <p className="footer-tag">the farmer’s friend on the other end of the line.</p>
            <div className="footer-links">
              <Link to="/">Home</Link>
              <Link to="/about">About</Link>
              <Link to="/app">Open the app</Link>
              <a href={`tel:${HOTLINE}`}>{formatPhone(HOTLINE)}</a>
            </div>
          </div>
          <p className="footer-fine">
            Willow helps you prepare and file. It does not approve claims or pay benefits.
            Program details in this demo are sample data.
          </p>
          <p className="wordmark" aria-hidden="true">Willow</p>
        </div>
      </footer>
    </div>
  )
}
