// Farmer app API on Vercel, reading and writing Supabase directly, so the app works while the
// FastAPI backend is offline. Same contract as FastAPI's /api/me routes (fastapi/app/main.py):
//   GET  /api/me                  the farmer's calls, latest matched call, approvals and edits
//   POST /api/me/approvals        {call_id, program_id}
//   POST /api/me/details          {call_id, edits?, confirmed?}
// vercel.json rewrites /api/me/<action> to /api/me?action=<action>.
// Needs SUPABASE_URL and SUPABASE_SECRET_KEY (server-only; never a VITE_ variable).

const LOGIN_WINDOW = 600
const LOGIN_MAX_FAILURES = 30
const EDITABLE = new Set(['farmer_name', 'state', 'county', 'crops', 'total_farm_acres', 'land_control',
  'primary_problem', 'desired_project', 'project_acres', 'total_project_cost_usd', 'assistance_needed_usd'])

interface Entry { approved: string[]; edits: Record<string, string>; confirmed: boolean }
interface Farmer { phone: string; state: Record<string, Partial<Entry>> | null }
interface CallRow {
  call_id: string
  status: string
  created_at: number
  profile: Record<string, unknown> | null
  matches: { program_id: string }[]
}

class HttpError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } })

async function db(path: string, init: RequestInit = {}) {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_SECRET_KEY
  if (!url || !key) throw new HttpError(503, 'Supabase is not configured')
  const response = await fetch(`${url.replace(/\/$/, '')}/rest/v1/${path}`, {
    ...init,
    headers: { apikey: key, 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) throw new HttpError(502, 'Database request failed')
  return response
}

const eq = (value: string) => `eq.${encodeURIComponent(value)}`

async function requireFarmer(request: Request): Promise<Farmer> {
  const since = Date.now() / 1000 - LOGIN_WINDOW
  const recent = await db(`login_attempts?select=id&at=gt.${since}`, { headers: { Prefer: 'count=exact', Range: '0-0' } })
  const failures = Number(recent.headers.get('content-range')?.split('/')[1] ?? 0)
  if (failures >= LOGIN_MAX_FAILURES) throw new HttpError(429, 'Too many wrong codes; try again in a few minutes')
  const code = (request.headers.get('x-farmer-code') ?? '').trim()
  const rows: Farmer[] = /^\d{6}$/.test(code)
    ? await (await db(`farmers?select=phone,state&login_code=${eq(code)}`)).json()
    : []
  if (!rows.length) {
    await db('login_attempts', { method: 'POST', body: JSON.stringify({ at: Date.now() / 1000 }) })
    throw new HttpError(401, 'Invalid login code')
  }
  return rows[0]
}

function publicProfile(profile: CallRow['profile']) {
  if (!profile) return null
  const { email_consent_statement: _e, sms_consent_statement: _s, ...rest } = profile
  return rest
}

const entryOf = (farmer: Farmer, callId: string): Entry =>
  ({ approved: [], edits: {}, confirmed: false, ...(farmer.state ?? {})[callId] })

async function me(farmer: Farmer) {
  const calls: CallRow[] = await (await db(
    `calls?select=call_id,status,created_at,profile,matches&phone=${eq(farmer.phone)}&order=created_at.desc`)).json()
  const latest = calls.find((c) => c.status === 'completed' || c.status === 'needs_information')
  return {
    phone: farmer.phone,
    calls: calls.map((c) => ({ call_id: c.call_id, status: c.status, received_at: new Date(c.created_at * 1000).toISOString() })),
    call: latest ? { call_id: latest.call_id, created_at: latest.created_at, status: latest.status,
      profile: publicProfile(latest.profile), matches: latest.matches } : null,
    state: latest ? entryOf(farmer, latest.call_id) : { approved: [], edits: {}, confirmed: false },
    disclaimer: 'Potential matches only. The agency decides eligibility.',
  }
}

function text(value: unknown, max: number) {
  if (typeof value !== 'string' || !value || value.length > max) throw new HttpError(422, 'Invalid value')
  return value
}

async function save(farmer: Farmer, callId: string, change: (entry: Entry, call: CallRow) => void) {
  const rows: CallRow[] = await (await db(
    `calls?select=call_id,status,created_at,profile,matches&call_id=${eq(callId)}&phone=${eq(farmer.phone)}`)).json()
  if (!rows.length) throw new HttpError(404, 'Call not found')
  const entry = entryOf(farmer, callId)
  change(entry, rows[0])
  await db(`farmers?phone=${eq(farmer.phone)}`, {
    method: 'PATCH',
    body: JSON.stringify({ state: { ...(farmer.state ?? {}), [callId]: entry }, updated_at: Date.now() / 1000 }),
  })
  return entry
}

async function handle(request: Request) {
  const action = new URL(request.url).searchParams.get('action') ?? ''
  const farmer = await requireFarmer(request)
  if (request.method === 'GET' && !action) return json(await me(farmer))
  if (request.method !== 'POST' || !['approvals', 'details'].includes(action)) throw new HttpError(404, 'Not found')

  const body = await request.json().catch(() => { throw new HttpError(422, 'Invalid JSON') }) as Record<string, unknown>
  const callId = text(body.call_id, 100)
  if (action === 'approvals') {
    const programId = text(body.program_id, 100)
    return json(await save(farmer, callId, (entry, call) => {
      if (!call.matches.some((m) => m.program_id === programId)) throw new HttpError(404, 'Program not in this call')
      if (!entry.approved.includes(programId)) entry.approved = [...entry.approved, programId]
    }))
  }
  const edits = (body.edits ?? {}) as Record<string, unknown>
  if (typeof edits !== 'object' || Array.isArray(edits) || Object.keys(edits).some((k) => !EDITABLE.has(k))) {
    throw new HttpError(422, 'Unknown profile field')
  }
  const clean = Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, text(v, 200).trim()]).filter(([, v]) => v))
  return json(await save(farmer, callId, (entry) => {
    entry.edits = { ...entry.edits, ...clean }
    entry.confirmed = entry.confirmed || body.confirmed === true
  }))
}

async function route(request: Request) {
  try {
    return await handle(request)
  } catch (error) {
    if (error instanceof HttpError) return json({ detail: error.message }, error.status)
    console.error('api/me failed', (error as Error).name)  // never log request bodies or codes
    return json({ detail: 'Server error' }, 500)
  }
}

export { route as GET, route as POST }
