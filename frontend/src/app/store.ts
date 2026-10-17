import { createContext, useContext } from 'react'
import type { CallResult, CaseStatus, Match, Profile } from '../data'

export interface CallStore {
  result: CallResult
  profile: Profile
  statusOf: (match: Match) => CaseStatus
  isRead: (id: string) => boolean
  markRead: (id: string) => void
  // These save to Willow's database and reject if the save fails.
  approve: (id: string) => Promise<void>
  editProfile: (key: string, value: string) => Promise<void>
  detailsConfirmed: boolean
  confirmDetails: () => Promise<void>
}

export const CallContext = createContext<CallStore | null>(null)

export function useCall() {
  const store = useContext(CallContext)
  if (!store) throw new Error('useCall must be used inside AppShell')
  return store
}

/** Programs that belong in the inbox: anything the farmer might act on. */
export function inboxMatches(store: CallStore) {
  return store.result.matches.filter((m) => store.statusOf(m) !== 'not_eligible')
}
