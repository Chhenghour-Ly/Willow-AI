import sample from './sample-matches.json'

export type MatchStatus = 'likely' | 'possible' | 'not_eligible'
export type CaseStatus = MatchStatus | 'submitted'

export interface Match {
  program_id: string
  name: string
  agency: string
  kind: 'aid' | 'loan' | 'grant' | 'insurance'
  status: MatchStatus
  score: number
  met: string[]
  blocked: string[]
  unknown: string[]
  explanation: string
  amount: { min: number; max: number } | null
  deadline: string | null
  required_documents: string[]
  synthetic: boolean
}

export type Profile = Record<string, string | number | boolean | string[] | null>

export interface CallResult {
  call_id: string
  created_at: number
  profile: Profile
  matches: Match[]
}

export const SAMPLE = sample as CallResult

export const HOTLINE = import.meta.env.VITE_HOTLINE || '+14086862433'
const API_URL = import.meta.env.VITE_API_URL || ''

export function formatPhone(e164: string) {
  const d = e164.replace(/\D/g, '').slice(-10)
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : e164
}

export async function loadCall(callId: string | null): Promise<CallResult> {
  if (!callId || !API_URL) return SAMPLE
  const response = await fetch(`${API_URL}/api/matches/${encodeURIComponent(callId)}`)
  if (response.status === 404) throw new Error('not_found')
  if (!response.ok) throw new Error('unavailable')
  return response.json()
}

export function displayName(match: Match) {
  return match.name.replace(/\s*\(synthetic\)$/, '')
}

export function statusLabel(status: CaseStatus) {
  return { likely: 'Good fit', possible: 'Needs answers', not_eligible: 'Not a fit', submitted: 'Submitted' }[status]
}

export function money(n: number) {
  if (n >= 1_000_000) return `$${+(n / 1_000_000).toFixed(1)}M`
  return n >= 1000 ? `$${Math.round(n / 1000)}k` : `$${n}`
}

export function amountLine(match: Match) {
  if (!match.amount) return null
  return `Up to ${money(match.amount.max)}`
}

/** Short inbox preview, written as Willow would say it. */
export function preview(match: Match, status: CaseStatus) {
  if (status === 'submitted') return 'Sent with your approval. We’ll text you when we hear back.'
  if (status === 'possible') return `You may qualify. ${match.unknown.length} question${match.unknown.length === 1 ? '' : 's'} left.`
  const amount = amountLine(match)
  return `You likely qualify${amount ? ` — ${amount.toLowerCase()}` : ''}. Tap to review and send.`
}

export function relativeTime(epochSeconds: number, now = new Date()) {
  const then = new Date(epochSeconds * 1000)
  const days = Math.floor((startOfDay(now) - startOfDay(then)) / 86_400_000)
  if (days <= 0) return then.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  if (days === 1) return 'Yesterday'
  if (days < 7) return then.toLocaleDateString('en-US', { weekday: 'long' })
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** Profile fields shown on "Your details", grouped the way a farmer talks about them. */
export const PROFILE_SECTIONS: { title: string; fields: [string, string][] }[] = [
  { title: 'You', fields: [['farmer_name', 'Name'], ['phone', 'Phone']] },
  {
    title: 'Your farm',
    fields: [['state', 'State'], ['county', 'County'], ['crops', 'Crops'], ['total_acres', 'Total acres'],
      ['years_farming', 'Years farming'], ['is_organic', 'Certified organic']],
  },
  {
    title: 'The damage',
    fields: [['damage_type', 'Cause'], ['loss_date', 'Date of loss'], ['acres_damaged', 'Acres damaged'],
      ['loss_percent', 'Percent lost']],
  },
  { title: 'Money', fields: [['annual_income', 'Yearly farm income'], ['has_crop_insurance', 'Crop insurance']] },
]

export function showValue(key: string, value: Profile[string]) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return null
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.map(cap).join(', ')
  if (key === 'annual_income' && typeof value === 'number') return `$${value.toLocaleString()}`
  if (key === 'loss_percent') return `${value}%`
  if (key === 'damage_type') return cap(String(value).replace('_', ' '))
  if (key === 'loss_date') return new Date(`${value}T12:00:00`).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
  if (key === 'phone') return formatPhone(String(value))
  return String(value)
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
