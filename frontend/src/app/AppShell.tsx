import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { HOTLINE, loadCall, type CallResult, type Match } from '../data'
import { CallContext, type CallStore } from './store'
import { CallButton } from './CallButton'

const KEY = 'willow.call'

// ponytail: approvals and edits live in this browser only; send them to the backend once it has write endpoints.
function useSaved<T>(name: string, initial: T) {
  const storageKey = `willow.${name}`
  const [value, setValue] = useState<T>(() => {
    const raw = localStorage.getItem(storageKey)
    return raw ? (JSON.parse(raw) as T) : initial
  })
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify(value)) }, [storageKey, value])
  return [value, setValue] as const
}

export function AppShell() {
  const [result, setResult] = useState<CallResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [approved, setApproved] = useSaved<string[]>('approved', [])
  const [read, setRead] = useSaved<string[]>('read', [])
  const [edits, setEdits] = useSaved<Record<string, string>>('edits', {})
  const [detailsConfirmed, setDetailsConfirmed] = useSaved('confirmed', false)
  const { pathname } = useLocation()
  const isRoot = pathname === '/app' || pathname === '/app/cases'

  useEffect(() => {
    loadCall(localStorage.getItem(KEY)).then(setResult, (e: Error) => setError(e.message))
  }, [])

  const store = useMemo<CallStore | null>(() => {
    if (!result) return null
    return {
      result,
      profile: { ...result.profile, ...edits },
      statusOf: (m: Match) => (approved.includes(m.program_id) ? 'submitted' : m.status),
      isRead: (id) => read.includes(id),
      markRead: (id) => setRead((r) => (r.includes(id) ? r : [...r, id])),
      approve: (id) => setApproved((a) => (a.includes(id) ? a : [...a, id])),
      editProfile: (key, value) => setEdits((e) => ({ ...e, [key]: value })),
      detailsConfirmed,
      confirmDetails: () => setDetailsConfirmed(true),
    }
  }, [result, edits, approved, read, detailsConfirmed, setApproved, setRead, setEdits, setDetailsConfirmed])

  return (
    <div className="device-stage">
      <div className="device">
        <div className="app">
          {isRoot && (
            <header className="app-head">
              <div className="app-title-row">
                <img src="/img/mark.png" alt="" width="28" height="31" />
                <h1 className="app-title">Willow</h1>
              </div>
              <nav className="segmented" aria-label="Sections">
                <NavLink to="/app" end>Inbox</NavLink>
                <NavLink to="/app/cases">Cases</NavLink>
              </nav>
            </header>
          )}
          <main className="app-body">
            {error ? (
              <div className="empty">
                <h2>{error === 'not_found' ? 'We couldn’t find that call.' : 'Willow is out of reach right now.'}</h2>
                <p>Call Willow and we’ll pick up where you left off.</p>
              </div>
            ) : store ? (
              <CallContext.Provider value={store}>
                <Outlet />
              </CallContext.Provider>
            ) : (
              <div className="loading" aria-live="polite">Loading your case…</div>
            )}
          </main>
          {isRoot && (
            <footer className="app-foot">
              <CallButton number={HOTLINE} />
            </footer>
          )}
        </div>
      </div>
    </div>
  )
}
