import { relativeTime } from '../data'
import { InboxList, matchRow, type Row } from './InboxList'
import { inboxMatches, useCall } from './store'

export function Inbox() {
  const store = useCall()
  const { result, profile } = store
  const matches = inboxMatches(store)
  const first = typeof profile.farmer_name === 'string' ? profile.farmer_name.split(' ')[0] : null

  const willow: Row = {
    id: 'details', to: '/app/details', title: 'Willow', avatar: 'willow',
    time: relativeTime(result.created_at), unread: !store.isRead('details'),
    preview: store.detailsConfirmed
      ? 'Thanks for checking your details.'
      : `${first ? `Hi ${first}, ` : ''}here’s what I heard on our call. Can you check it?`,
  }
  const rows = [willow, ...matches.map((m) => matchRow(m, store.statusOf(m), result.created_at, !store.isRead(m.program_id)))]

  if (!matches.length) {
    return (
      <>
        <InboxList rows={[willow]} />
        <div className="empty">
          <h2>No programs yet</h2>
          <p>Willow is still looking. Call anytime to add details.</p>
        </div>
      </>
    )
  }
  return <InboxList rows={rows} />
}
