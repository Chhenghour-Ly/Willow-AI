import { useState, type FormEvent } from 'react'
import { HOTLINE, formatPhone } from '../data'

export function Contact() {
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const message = String(new FormData(e.currentTarget).get('message') ?? '').trim()
    if (!message) {
      setError('Please write a short message.')
      return
    }
    // ponytail: no backend for contact yet; store in Supabase once it's set up.
    setError(null)
    setSent(true)
  }

  return (
    <main className="page">
      <section className="page-hero">
        <h1 className="display">Talk to a person,<br />or to Willow.</h1>
      </section>

      <section className="contact-grid">
        <a className="contact-call" href={`tel:${HOTLINE}`}>
          <span className="hotline-label">Need help with a claim?</span>
          <span className="hotline-number">{formatPhone(HOTLINE)}</span>
          <span className="contact-call-sub">Call Willow any time</span>
        </a>

        <div className="contact-form-card">
          {sent ? (
            <div className="thanks" role="status">
              <h2>Thanks, we’ve got it.</h2>
              <p>We’ll get back to you soon.</p>
            </div>
          ) : (
            <form onSubmit={submit} noValidate>
              <h2>Send the team a note</h2>
              <label>
                <span>Your name</span>
                <input name="name" autoComplete="name" maxLength={100} />
              </label>
              <label>
                <span>Phone or email</span>
                <input name="contact" autoComplete="tel" maxLength={200} />
              </label>
              <label>
                <span>Message</span>
                <textarea name="message" rows={5} maxLength={2000} aria-invalid={!!error}
                  aria-describedby={error ? 'msg-error' : undefined} />
              </label>
              {error && <p id="msg-error" className="form-error">{error}</p>}
              <button className="btn btn-dark" type="submit">Send</button>
            </form>
          )}
        </div>
      </section>
    </main>
  )
}
