import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { HOTLINE, displayName, statusLabel, type Match } from '../data'
import { CallButton } from './CallButton'
import { useCall } from './store'

export function CasePage() {
  const { programId } = useParams()
  const store = useCall()
  const match = store.result.matches.find((m) => m.program_id === programId)
  const { markRead } = store
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (match) markRead(match.program_id)
  }, [match, markRead])

  if (!match) {
    return (
      <div className="sheet">
        <BackLink />
        <div className="empty"><h2>This program isn’t in your case.</h2></div>
      </div>
    )
  }

  const status = store.statusOf(match)
  const approve = async () => {
    setSending(true)
    setFailed(false)
    try {
      await store.approve(match.program_id)
    } catch {
      setFailed(true)
    }
    setSending(false)
  }

  return (
    <div className="sheet">
      <BackLink />
      <div className="case-head">
        <span className={`pill pill-${status}`}>{statusLabel(status)}</span>
        <h1>{displayName(match)}</h1>
        <p className="case-sub">{match.agency}</p>
        {match.amount && <p className="case-money">Up to <strong>${match.amount.max.toLocaleString()}</strong></p>}
      </div>

      {match.synthetic && <p className="note">Sample program for the Willow demo, not a real USDA offer.</p>}

      <Reasons title="Why it fits" items={match.met} tone="met" />
      <Reasons title="Still need from you" items={match.unknown} tone="unknown" />
      <Reasons title="Why it doesn’t fit" items={match.blocked} tone="blocked" />

      {match.required_documents.length > 0 && (
        <section className="group">
          <h2 className="group-label">Documents to gather</h2>
          <ul className="card-list" role="list">
            {match.required_documents.map((d) => <li key={d}>{d}</li>)}
          </ul>
        </section>
      )}
      {match.deadline && <p className="deadline">Deadline: {new Date(`${match.deadline}T12:00:00`).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}</p>}

      {match.next_action && (
        <section className="group">
          <h2 className="group-label">Next step</h2>
          <ul className="card-list" role="list"><li>{match.next_action}</li></ul>
        </section>
      )}
      {!!match.sources?.length && (
        <section className="group">
          <h2 className="group-label">Official sources</h2>
          <ul className="card-list sources" role="list">
            {match.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></li>)}
          </ul>
        </section>
      )}
      <p className="note">Willow finds programs that may fit. The agency decides who qualifies.</p>

      <div className="actions">
        {status === 'likely' && (
          <>
            {!store.detailsConfirmed && (
              <Link className="check-first" to="/app/details">Check your details first →</Link>
            )}
            {failed && <p className="save-error" role="alert">Couldn’t save your approval. Check your connection and try again.</p>}
            <button className="btn btn-leaf" onClick={approve} disabled={sending}>
              {sending ? 'Saving…' : 'Approve this program'}
            </button>
          </>
        )}
        {status === 'submitted' && <p className="sent">You approved this. Willow will follow up with next steps.</p>}
        <CallButton number={HOTLINE} label={status === 'possible' ? 'Call Willow to answer' : 'Call Willow about this'}
          variant={status === 'possible' ? 'btn-dark' : 'btn-ghost'} />
      </div>
    </div>
  )
}

function BackLink() {
  return <Link className="back" to="/app">‹ Inbox</Link>
}

function Reasons({ title, items, tone }: { title: string; items: Match['met']; tone: 'met' | 'unknown' | 'blocked' }) {
  if (!items.length) return null
  return (
    <section className="group">
      <h2 className="group-label">{title}</h2>
      <ul className={`card-list reasons ${tone}`} role="list">
        {items.map((r) => <li key={r}>{r}</li>)}
      </ul>
    </section>
  )
}
