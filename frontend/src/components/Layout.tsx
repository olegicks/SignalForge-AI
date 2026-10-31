import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

type Theme = 'system' | 'light' | 'dark'
const THEME_KEY = 'signalforge-theme'
const NEXT_THEME: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
const THEME_LABEL: Record<Theme, string> = { system: 'Auto', light: 'Light', dark: 'Dark' }

function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      if (theme === 'system') localStorage.removeItem(THEME_KEY)
      else localStorage.setItem(THEME_KEY, theme)
    } catch {
      // Storage can be unavailable (private mode); the toggle still works for this visit.
    }
  }, [theme])

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(NEXT_THEME[theme])}
      aria-label={`Theme: ${THEME_LABEL[theme]}. Click to change.`}
    >
      {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'} {THEME_LABEL[theme]}
    </button>
  )
}

export function Layout() {
  return (
    <div className="app">
      <header className="site-header">
        <div className="container header-inner">
          <NavLink to="/" className="brand">
            <img src="/favicon.svg" alt="" width={24} height={24} />
            SignalForge <span className="brand-ai">AI</span>
          </NavLink>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Overview
            </NavLink>
            <NavLink to="/track-record">Track record</NavLink>
            <NavLink to="/about">About</NavLink>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main className="container main">
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container">
          <strong>Not investment advice.</strong> SignalForge AI is a research prototype. Signals
          are generated automatically by a language model from public news and may be wrong. Do
          your own research.
        </div>
      </footer>
    </div>
  )
}
