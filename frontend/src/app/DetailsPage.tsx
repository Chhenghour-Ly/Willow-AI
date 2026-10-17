import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { PROFILE_SECTIONS, showValue } from '../data'
import { useCall } from './store'

export function DetailsPage() {
  const store = useCall()
  const { markRead } = store
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => { markRead('details') }, [markRead])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setFailed(false)
    try {
      await action()
      setEditing(null)
    } catch {
      setFailed(true)
    }
    setBusy(false)
  }

  const save = (key: string) => (draft.trim() ? run(() => store.editProfile(key, draft.trim())) : setEditing(null))

  return (
    <div className="sheet">
      <Link className="back" to="/app">‹ Inbox</Link>
      <div className="case-head">
        <h1>Your details</h1>
        <p className="case-sub">What Willow heard on your call. Fix anything that’s wrong; nothing is sent until you approve.</p>
      </div>

      {PROFILE_SECTIONS.map((section) => (
        <section key={section.title} className="group">
          <h2 className="group-label">{section.title}</h2>
          <div className="fields">
            {section.fields.map(([key, label]) => {
              const value = showValue(key, store.profile[key])
              const isEditing = editing === key
              return (
                <div key={key} className="field">
                  {isEditing ? (
                    <form className="field-edit" onSubmit={(e) => { e.preventDefault(); save(key) }}>
                      <label htmlFor={`f-${key}`}>{label}</label>
                      <input id={`f-${key}`} value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus
                        maxLength={200} enterKeyHint="done" />
                      <div className="field-buttons">
                        <button type="button" className="link-btn" onClick={() => setEditing(null)}>Cancel</button>
                        <button type="submit" className="link-btn strong" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <div className="field-text">
                        <span className="field-label">{label}</span>
                        <span className="field-value">
                          {value ?? <span className="missing">Not mentioned</span>}
                          {value === null && <span className="flag">check</span>}
                        </span>
                      </div>
                      {!store.detailsConfirmed && key !== 'phone' && (
                        <button className="link-btn" onClick={() => { setEditing(key); setDraft(value ?? '') }}
                          aria-label={`Edit ${label}`}>Edit</button>
                      )}
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      ))}

      <div className="actions">
        {failed && <p className="save-error" role="alert">Couldn’t save. Check your connection and try again.</p>}
        {store.detailsConfirmed
          ? <p className="sent">Thanks. Willow will use these details for your applications.</p>
          : <button className="btn btn-leaf" disabled={busy} onClick={() => run(store.confirmDetails)}>Looks right</button>}
      </div>
    </div>
  )
}
