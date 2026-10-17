import { Link } from 'react-router'
import { amountLine, displayName, statusLabel, type CaseStatus } from '../data'
import { useCall } from './store'

const KIND = { aid: 'Disaster aid', grant: 'Grant', loan: 'Loan', insurance: 'Insurance' }

const GROUPS: { status: CaseStatus; title: string }[] = [
  { status: 'likely', title: 'Ready to send' },
  { status: 'possible', title: 'Needs your answers' },
  { status: 'submitted', title: 'Sent' },
  { status: 'not_eligible', title: 'Not a fit this time' },
]

export function Cases() {
  const store = useCall()
  return (
    <div className="cases">
      {GROUPS.map(({ status, title }) => {
        const items = store.result.matches.filter((m) => store.statusOf(m) === status)
        if (!items.length) return null
        return (
          <section key={status} className="case-group">
            <h2 className="group-title">{title} <span>{items.length}</span></h2>
            <ul role="list">
              {items.map((m) => (
                <li key={m.program_id}>
                  <Link className={`case-card${status === 'not_eligible' ? ' muted' : ''}`} to={`/app/case/${m.program_id}`}>
                    <span className="case-card-top">
                      <span className={`pill pill-${status}`}>{statusLabel(status)}</span>
                      {amountLine(m) && <span className="case-amount">{amountLine(m)}</span>}
                    </span>
                    <span className="case-name">{displayName(m)}</span>
                    <span className="case-agency">{m.agency} · {KIND[m.kind]}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
