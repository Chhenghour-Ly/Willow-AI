import { useState, type FormEvent } from 'react'
import { formatPhone, HOTLINE, LOGIN_ERRORS as MESSAGES } from '../data'
import { CallButton } from './CallButton'

export function Login({ onLogin }: { onLogin: (code: string) => Promise<void> }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onLogin(code)
    } catch (err) {
      setError(MESSAGES[(err as Error).message] ?? MESSAGES.unavailable)
      setBusy(false)
    }
  }

  return (
    <main className="app-body">
      <form className="sheet login" onSubmit={submit}>
        <img src="/img/mark.png" alt="" width="44" height="49" />
        <div className="case-head">
          <h1>Open your Willow case</h1>
          <p className="case-sub">Enter the 6-digit code from your Willow results email.</p>
        </div>
        <label className="field-label" htmlFor="login-code">Login code</label>
        <input id="login-code" className="code-input" value={code} inputMode="numeric" autoComplete="one-time-code"
          pattern="\d{6}" maxLength={6} required autoFocus aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'login-error' : undefined}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        {error && <p id="login-error" className="login-error" role="alert">{error}</p>}
        <div className="actions">
          <button className="btn btn-leaf" disabled={busy || code.length !== 6}>{busy ? 'Opening…' : 'Open my case'}</button>
          <p className="check-first">No code yet? Call Willow at {formatPhone(HOTLINE)} and ask for your results by email.</p>
          <CallButton number={HOTLINE} variant="btn-ghost" />
        </div>
      </form>
    </main>
  )
}
