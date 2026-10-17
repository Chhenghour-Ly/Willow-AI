import { Link } from 'react-router'
import { displayName, preview, relativeTime, type CaseStatus, type Match } from '../data'

export interface Row {
  id: string
  to: string
  title: string
  preview: string
  time: string
  unread: boolean
  avatar: 'willow' | Match['kind']
}

// One 24px grid, 1.75 stroke, round caps: aid = coin, grant = sprout, loan = bank, insurance = shield.
const ICON: Record<Exclude<Row['avatar'], 'willow'>, string> = {
  aid: 'M12 3v18M16.5 7.5c-.8-1.2-2.4-2-4.5-2-2.5 0-4 1.3-4 3.1 0 4.4 9 2.4 9 6.8 0 1.9-1.7 3.1-4.5 3.1-2.2 0-3.9-.8-4.8-2.1',
  grant: 'M12 21v-9M12 12c0-4 2.5-6.5 7-6.5 0 4.2-2.6 6.5-7 6.5zM12 14c0-3.2-2-5.2-5.5-5.2 0 3.3 2 5.2 5.5 5.2z',
  loan: 'M3.5 9.5 12 4l8.5 5.5M5.5 10v7.5M9.8 10v7.5M14.2 10v7.5M18.5 10v7.5M3.5 20h17',
  insurance: 'M12 3.5 5 6.2v5.3c0 4.3 2.9 7.6 7 9 4.1-1.4 7-4.7 7-9V6.2L12 3.5zM8.8 12.2l2.2 2.2 4.3-4.4',
}

export function matchRow(m: Match, status: CaseStatus, createdAt: number, unread: boolean): Row {
  return {
    id: m.program_id, to: `/app/case/${m.program_id}`, title: displayName(m),
    preview: preview(m, status), time: relativeTime(createdAt), unread, avatar: m.kind,
  }
}

export function InboxList({ rows, interactive = true }: { rows: Row[]; interactive?: boolean }) {
  return (
    <ul className="inbox" role="list">
      {rows.map((row) => {
        const body = (
          <>
            <span className={`dot${row.unread ? ' on' : ''}`} aria-label={row.unread ? 'Unread' : undefined} />
            <span className={`avatar avatar-${row.avatar}`} aria-hidden="true">
              {row.avatar === 'willow' ? <img src="/img/mark.png" alt="" width="22" height="24" /> : (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round"><path d={ICON[row.avatar]} /></svg>
              )}
            </span>
            <span className="row-main">
              <span className="row-top">
                <span className="row-title">{row.title}</span>
                <span className="row-time">{row.time}</span>
              </span>
              <span className="row-preview">{row.preview}</span>
            </span>
          </>
        )
        return (
          <li key={row.id}>
            {interactive ? <Link className="row" to={row.to}>{body}</Link> : <div className="row">{body}</div>}
          </li>
        )
      })}
    </ul>
  )
}
