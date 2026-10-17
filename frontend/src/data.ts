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
  next_action?: string
  sources?: { title: string; url: string }[]
}

export type Profile = Record<string, string | number | boolean | string[] | null>

export interface CallResult {
  call_id: string
  created_at: number
  profile: Profile
  matches: Match[]
}

/** What the farmer has done in the app for one call, saved in Willow's database. */
export interface FarmerState {
  approved: string[]
  edits: Record<string, string>
  confirmed: boolean
}

export interface Me {
  phone: string
  calls: { call_id: string; status: string; received_at: string }[]
  call: CallResult | null
  state: FarmerState
}

export const SAMPLE = sample as CallResult

export const HOTLINE = import.meta.env.VITE_HOTLINE || '+14086862433'
// Empty means same origin: on Vercel that is the api/me.ts function, which reads Supabase directly.
const API_URL = import.meta.env.VITE_API_URL ?? ''

export function formatPhone(e164: string) {
  const d = e164.replace(/\D/g, '').slice(-10)
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : e164
}

interface ApiItem { text: string }
export interface ApiMatch {
  program_id: string
  program_name: string
  agency: string
  description: string | null
  repayable: boolean
  fit_status: 'potential_fit' | 'needs_information' | 'unlikely_fit'
  reasons: ApiItem[]
  obstacles: ApiItem[]
  missing_requirements: ApiItem[]
  application_deadline: { date: string } | null
  official_source_urls: { title: string; url: string }[]
  next_action: string
  relevance: number
}

const FIT: Record<ApiMatch['fit_status'], MatchStatus> = {
  potential_fit: 'likely', needs_information: 'possible', unlikely_fit: 'not_eligible',
}

/** Backend match (USDA wording, sources) into the shape the app screens use. */
export function fromApi(m: ApiMatch): Match {
  const text = (items: ApiItem[]) => items.map((i) => i.text)
  return {
    program_id: m.program_id, name: m.program_name, agency: m.agency,
    kind: m.repayable ? 'loan' : 'grant', status: FIT[m.fit_status], score: m.relevance,
    met: text(m.reasons), blocked: text(m.obstacles), unknown: text(m.missing_requirements),
    explanation: m.description ?? '', amount: null, deadline: m.application_deadline?.date ?? null,
    required_documents: [], synthetic: false, next_action: m.next_action,
    sources: m.official_source_urls ?? [],
  }
}

async function api<T>(path: string, code: string, body?: object): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: body ? 'POST' : 'GET',
      // ngrok's free tunnel answers browsers with a warning page unless this header is present.
      headers: { 'X-Farmer-Code': code, 'ngrok-skip-browser-warning': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error('unavailable')
  }
  if (response.status === 401) throw new Error('bad_code')
  if (response.status === 429) throw new Error('too_many')
  if (!response.ok) throw new Error('unavailable')
  return response.json() as Promise<T>
}

export const CODE_KEY = 'willow.code'

export const LOGIN_ERRORS: Record<string, string> = {
  bad_code: 'That code didn’t work. Check the latest email from Willow.',
  too_many: 'Too many tries. Wait a few minutes, then try again.',
  unavailable: 'Willow is out of reach right now. Try again in a minute.',
}

/** Always-working demo sign-in: sample farmer and programs, kept in this tab only. No backend needed. */
export const DEMO_CODE = '000000'

const DEMO_PROFILE: Profile = {
  ...SAMPLE.profile,
  farmer_name: 'Dale Hansen', phone: '+15555550100', state: 'IA', county: 'Story County', crops: ['corn', 'soybeans'],
  total_farm_acres: 300, land_control: 'owned', primary_problem: 'Hail destroyed about 60% of 120 acres of corn',
  desired_project: 'Replant and recover the lost crop', project_acres: 120, total_project_cost_usd: 72000,
  assistance_needed_usd: 45000,
}
let demoState: FarmerState = { approved: [], edits: {}, confirmed: false }

function demoMe(): Me {
  return {
    phone: String(DEMO_PROFILE.phone),
    calls: [{ call_id: SAMPLE.call_id, status: 'completed', received_at: new Date(SAMPLE.created_at * 1000).toISOString() }],
    call: { ...SAMPLE, profile: DEMO_PROFILE },
    state: demoState,
  }
}

function demoSave(change: (s: FarmerState) => FarmerState) {
  demoState = change(demoState)
  return Promise.resolve(demoState)
}

export async function loadMe(code: string): Promise<Me> {
  if (code === DEMO_CODE) return demoMe()
  const me = await api<Omit<Me, 'call'> & { call: (Omit<CallResult, 'matches'> & { matches: ApiMatch[] }) | null }>('/api/me', code)
  return { ...me, call: me.call && { ...me.call, profile: me.call.profile ?? {}, matches: me.call.matches.map(fromApi) } }
}

export const approveProgram = (code: string, call_id: string, program_id: string) => code === DEMO_CODE
  ? demoSave((s) => ({ ...s, approved: s.approved.includes(program_id) ? s.approved : [...s.approved, program_id] }))
  : api<FarmerState>('/api/me/approvals', code, { call_id, program_id })

export const saveDetails = (code: string, call_id: string, change: { edits?: Record<string, string>; confirmed?: boolean }) =>
  code === DEMO_CODE
    ? demoSave((s) => ({ ...s, edits: { ...s.edits, ...change.edits }, confirmed: s.confirmed || !!change.confirmed }))
    : api<FarmerState>('/api/me/details', code, { call_id, ...change })

export function displayName(match: Match) {
  return match.name.replace(/\s*\(synthetic\)$/, '')
}

export function statusLabel(status: CaseStatus) {
  return { likely: 'Good fit', possible: 'Needs answers', not_eligible: 'Not a fit', submitted: 'Approved' }[status]
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
  if (status === 'submitted') return 'You approved this. Willow will follow up with next steps.'
  if (status === 'possible') return `You may qualify. ${match.unknown.length} question${match.unknown.length === 1 ? '' : 's'} left.`
  if (status === 'not_eligible') return 'Probably not a fit right now. Tap to see why.'
  const amount = amountLine(match)
  return `This may fit your farm${amount ? ` — ${amount.toLowerCase()}` : ''}. Tap to review and approve.`
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

/** Profile fields shown on "Your details", grouped the way a farmer talks about them. Keys match the backend. */
export const PROFILE_SECTIONS: { title: string; fields: [string, string][] }[] = [
  { title: 'You', fields: [['farmer_name', 'Name'], ['phone', 'Phone']] },
  {
    title: 'Your farm',
    fields: [['state', 'State'], ['county', 'County'], ['crops', 'Crops'], ['total_farm_acres', 'Total acres'],
      ['land_control', 'Own or lease']],
  },
  {
    title: 'Your project',
    fields: [['primary_problem', 'Problem'], ['desired_project', 'What you want to do'], ['project_acres', 'Acres in project']],
  },
  { title: 'Money', fields: [['total_project_cost_usd', 'Project cost'], ['assistance_needed_usd', 'Help needed']] },
]

const WORDS: Record<string, string> = { owned: 'Own', leased: 'Lease', other: 'Other' }

export function showValue(key: string, value: Profile[string]) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return null
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.map(cap).join(', ')
  if (key.endsWith('_usd') && typeof value === 'number') return `$${value.toLocaleString()}`
  if (key === 'phone') return formatPhone(String(value))
  return WORDS[String(value)] ?? String(value)
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
