import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { CODE_KEY, DEMO_CODE, HOTLINE, LOGIN_ERRORS, SAMPLE, formatPhone, loadMe } from '../data'
import { InboxList, matchRow, type Row } from '../app/InboxList'

/** Already called? Check the code here, then open the farmer app signed in. */
function HeroLogin() {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await loadMe(code)
      try { localStorage.setItem(CODE_KEY, code) } catch { /* private mode: the app asks again */ }
      navigate('/app')
    } catch (err) {
      setError(LOGIN_ERRORS[(err as Error).message] ?? LOGIN_ERRORS.unavailable)
      setBusy(false)
    }
  }

  return (
    <form className="hero-login" onSubmit={submit}>
      <label htmlFor="hero-code">Already called? Enter the 6‑digit code from your email.</label>
      <div className="hero-login-row">
        <input id="hero-code" value={code} inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}"
          maxLength={6} required placeholder="000000" aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'hero-code-error' : undefined}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        <button className="btn btn-dark" disabled={busy || code.length !== 6}>{busy ? 'Opening…' : 'Sign in'}</button>
      </div>
      {error && <p id="hero-code-error" className="hero-login-error" role="alert">{error}</p>}
      <p className="hero-demo">
        Just testing? Use{' '}
        <button type="button" className="demo-code" onClick={() => setCode(DEMO_CODE)} aria-label="Fill in sample code 000000">
          {DEMO_CODE}
        </button>{' '}
        to explore a sample case.
      </p>
    </form>
  )
}

const STEPS = [
  { img: '/img/step-1.png', title: 'Talk it through', body: 'Call and tell Willow what happened, in your own words. It asks the follow-up questions so you don’t have to know them.' },
  { img: '/img/step-2.png', title: 'Your claim, prepared', body: 'Willow organizes what you said into your insurance paperwork and shows you exactly what’s still missing.' },
  { img: '/img/step-3.png', title: 'Money you may qualify for', body: 'It searches grants, loans and disaster aid that fit your farm, and explains why each one does.' },
]

function previewRows(): Row[] {
  const willow: Row = {
    id: 'w', to: '', title: 'Willow', avatar: 'willow', time: '9:12 AM', unread: true,
    preview: 'Hi Dale, here’s what I heard on our call. Can you check it?',
  }
  const matches = SAMPLE.matches.filter((m) => m.status === 'likely').slice(0, 4)
  return [willow, ...matches.map((m, i) => ({ ...matchRow(m, m.status, SAMPLE.created_at, i < 2), time: i < 2 ? '9:12 AM' : 'Yesterday' }))]
}

export function Home() {
  const number = formatPhone(HOTLINE)
  return (
    <main>
      <section className="hero">
        <h1 className="display">Crop damage?<br />Just call Willow.</h1>
        <p className="lede">
          No forms, no websites. Tell Willow what happened and it prepares your insurance claim and finds the
          help you may qualify for.
        </p>
        <a className="hotline" href={`tel:${HOTLINE}`}>
          <span className="hotline-label">Call Willow</span>
          <span className="hotline-number">{number}</span>
        </a>
        <p className="hint">Talk the way you’d talk to a neighbor.</p>
        <HeroLogin />

        <div className="hero-art">
          <div className="hero-glow" aria-hidden="true" />
          <img className="hero-farmer" src="/img/farmer.png" alt="Willow's farmer mascot waving, wearing a headset" width="600" height="789" />
          <div className="mock-phone" aria-label="Preview of the Willow app inbox" role="img">
            <div className="mock-screen">
              <div className="mock-status"><span>9:41</span><span>●●● ▮</span></div>
              <p className="mock-title">Willow</p>
              <InboxList rows={previewRows()} interactive={false} />
            </div>
          </div>
        </div>
      </section>

      <section className="steps" aria-labelledby="steps-title">
        <h2 id="steps-title" className="section-title">One call.<br />Every path to recovery.</h2>
        <div className="step-grid">
          {STEPS.map((s, i) => (
            <article key={s.title} className="step">
              <div className="step-art"><img src={s.img} alt="" width="480" height="435" loading="lazy" /></div>
              <p className="step-num">0{i + 1}</p>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="after">
        <div className="after-copy">
          <h2 className="section-title left">After the call,<br />it’s all in your pocket.</h2>
          <p className="lede left">
            Willow texts you a link. Every claim and program lands in one inbox, with what’s ready, what’s
            missing, and a button to send it when you’re happy.
          </p>
          <ul className="ticks">
            <li>Fix anything Willow got wrong before it’s sent</li>
            <li>Nothing goes out without your approval</li>
            <li>Add it to your home screen for alerts</li>
          </ul>
        </div>
      </section>

      <section className="cta">
        <div className="cta-card">
          <h2>Ready when you are.</h2>
          <p>Call from the field, the truck, or the kitchen table.</p>
          <a className="btn btn-leaf cta-btn" href={`tel:${HOTLINE}`}>Call {number}</a>
        </div>
      </section>
    </main>
  )
}
