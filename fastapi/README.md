# Willow matching API

Vapi end-of-call report → farmer profile → retrieval over official USDA program
text → requirement checks → results API. Matches are **potential fits, not
eligibility decisions**; the agency decides.

## Pipeline

1. `POST /webhooks/vapi` checks the secret (`X-Vapi-Secret` or `Authorization: Bearer`).
   Only `message.type == "end-of-call-report"` is processed; every other event gets
   `{"status": "ignored"}`. The call is stored as `received` and acknowledged at once.
   A repeat delivery for the same `message.call.id` returns the stored status.
2. In the background (`app/main.py: process_call`), `app/profile.py` reads the
   structured output from `message.artifact.structuredOutputs[<id>].result`
   (also `message.call.artifact…` and the legacy `analysis.structuredData`).
   `"unknown"` and `0` become `null`; enums outside the schema become `null`;
   `needs` keeps only the allowed categories. Nothing is inferred from the transcript.
3. If the webhook had no structured output and `VAPI_API_KEY` is set,
   `app/vapi.py` fetches `GET https://api.vapi.ai/call/{id}` with backoff
   (`VAPI_RETRY_DELAYS`, default 2,4,8,16 s).
4. `app/matching.py` retrieves the most relevant passages from
   `fixtures/programs.json` (official sources, verified 2026-10-17) and checks each
   requirement: **reasons** (what fits), **obstacles** (conflicts with what the farmer
   said), **missing_requirements** (unknown, to confirm). Every item carries a
   `source_url` where one applies.
5. Status: `received` → `processing` → `completed` | `needs_information` (no state or
   needs captured) | `failed`.

Programs: EQIP (NRCS) and FSA Operating Microloan. `fit_status` is
`potential_fit`, `needs_information` or `unlikely_fit` (only when something the farmer
said conflicts with a rule). `relevance` scores retrieved text, not eligibility.

## API

| Endpoint | Auth | Returns |
| --- | --- | --- |
| `POST /webhooks/vapi` | `X-Vapi-Secret` | `{status, call_id}` |
| `GET /api/matches/{call_id}` | `X-Api-Key` | `{status, profile, matches[...]}` |
| `GET /api/calls/{call_id}` | `X-Api-Key` | receipt check: status, transcript length, raw structured output |

Each match: `program_id, program_name, fit_status, reasons, obstacles,
missing_requirements, application_deadline, official_source_urls, evidence,
next_action`.

## Structured output schema (Vapi)

`farmer_name, state, county, crops[], primary_problem, desired_project, needs[],
land_control (owned|leased|other|unknown), project_status
(not_started|in_progress|completed|unknown), project_acres, total_farm_acres,
total_project_cost_usd, assistance_needed_usd, funding_preference
(nonrepayable_only|prefer_nonrepayable_open_to_loan|loan_ok|unknown), call_summary`.
Optional: `irrigated_years_of_last_5` (EQIP irrigation history rule).

## Run locally (PowerShell, from this folder)

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # fill WEBHOOK_SECRET and API_KEY (random 32+ chars)
python -m pytest -q
python -m uvicorn app.main:create_app --factory --port 8000
ngrok http 8000               # Vapi Server URL: https://<ngrok>/webhooks/vapi
```

Inspect calls from the terminal:

```powershell
python -m app.show                     # list calls and status
python -m app.show <call_id>           # structured output, profile, cited matches
python -m app.show <call_id> --rematch # re-run with current code
```

Fixtures: `carolina-end-of-call.json` (simulated full call),
`recorded-with-structured-outputs.json` and `recorded-no-structured-outputs.json`
(sanitized real Vapi payloads: phone replaced, URLs and costs removed).

## Known limits

- One shared `API_KEY` protects reads; farmer-facing pages need per-farmer sign-in.
- Retrieval is keyword-based over the stored official passages.
- Tables are created with `create_all`; no migrations.
