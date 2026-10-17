import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { approveProgram, CODE_KEY, DEMO_CODE, HOTLINE, loadMe, saveDetails, type FarmerState, type Match, type Me } from '../data'
import { CallContext, type CallStore } from './store'
import { CallButton } from './CallButton'
import { Login } from './Login'

function stored(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}

function store(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value) } catch { /* private mode */ }
}

// Which messages were opened is a per-device nicety; approvals and edits live in the database.
function useRead() {
  const [read, setRead] = useState<string[]>(() => JSON.parse(stored('willow.read') ?? '[]') as string[])
  useEffect(() => { store('willow.read', JSON.stringify(read)) }, [read])
  return [read, setRead] as const
}

export function AppShell() {
  const [code, setCode] = useState(() => stored(CODE_KEY))
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [read, setRead] = useRead()
  const { pathname } = useLocation()
  const isRoot = pathname === '/app' || pathname === '/app/cases'

  const signOut = useCallback(() => {
    store(CODE_KEY, null)
    setCode(null)
    setMe(null)
    setError(null)
  }, [])

  const refresh = useCallback(() => {
    if (!code) return
    loadMe(code).then((m) => { setMe(m); setError(null) }, (e: Error) => {
      if (e.message === 'bad_code') signOut()
      else setError(e.message)
    })
  }, [code, signOut])

  // Load on sign-in, and again whenever the farmer comes back to the app, so new calls show up.
  useEffect(() => {
    refresh()
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  const login = async (entered: string) => {
    const m = await loadMe(entered)
    store(CODE_KEY, entered)
    setCode(entered)
    setMe(m)
  }

  const callStore = useMemo<CallStore | null>(() => {
    if (!me?.call || !code) return null
    const call = me.call
    const setState = (state: FarmerState) => setMe((m) => m && { ...m, state })
    return {
      result: call,
      profile: { ...call.profile, ...me.state.edits },
      statusOf: (m: Match) => (me.state.approved.includes(m.program_id) ? 'submitted' : m.status),
      isRead: (id) => read.includes(id),
      markRead: (id) => setRead((r) => (r.includes(id) ? r : [...r, id])),
      approve: async (id) => setState(await approveProgram(code, call.call_id, id)),
      editProfile: async (key, value) => setState(await saveDetails(code, call.call_id, { edits: { [key]: value } })),
      detailsConfirmed: me.state.confirmed,
      confirmDetails: async () => setState(await saveDetails(code, call.call_id, { confirmed: true })),
    }
  }, [me, code, read, setRead])

  if (!code) {
    return <Frame><Login onLogin={login} /></Frame>
  }

  return (
    <Frame>
      {isRoot && (
        <header className="app-head">
          <div className="app-title-row">
            <img src="/img/mark.png" alt="" width="28" height="31" />
            <h1 className="app-title">Willow</h1>
            {code === DEMO_CODE && <small>Sample case</small>}
            <button className="link-btn sign-out" onClick={signOut}>Sign out</button>
          </div>
          <nav className="segmented" aria-label="Sections">
            <NavLink to="/app" end>Inbox</NavLink>
            <NavLink to="/app/cases">Cases</NavLink>
          </nav>
        </header>
      )}
      <main className="app-body">
        {error && !me ? (
          <div className="empty">
            <h2>{error === 'too_many' ? 'Too many tries. Wait a few minutes.' : 'Willow is out of reach right now.'}</h2>
            <p><button className="link-btn strong" onClick={refresh}>Try again</button></p>
          </div>
        ) : !me ? (
          <div className="loading" aria-live="polite">Loading your case…</div>
        ) : callStore ? (
          <CallContext.Provider value={callStore}>
            <Outlet />
          </CallContext.Provider>
        ) : (
          <div className="empty">
            <h2>{me.calls.length ? 'Willow is still working on your call.' : 'No calls yet.'}</h2>
            <p>{me.calls.length ? 'Your programs will show up here in a minute.' : 'Call Willow and your results will show up here.'}</p>
            <p><button className="link-btn strong" onClick={refresh}>Refresh</button></p>
          </div>
        )}
      </main>
      {isRoot && (
        <footer className="app-foot">
          <CallButton number={HOTLINE} />
        </footer>
      )}
    </Frame>
  )
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="device-stage">
      <div className="device">
        <div className="app">{children}</div>
      </div>
    </div>
  )
}
