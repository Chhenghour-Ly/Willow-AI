# Willow matching API

After a farmer calls Willow, Vapi sends an end-of-call report here. The API
cleans up the farmer's details, searches the program list, checks every
eligibility rule, and saves a ranked list of grants, loans, aid and insurance
options under the call ID for the website to show.

**Program data is synthetic.** Every program in `fixtures/programs.json` is
made up for the demo and marked `"synthetic": true`. Do not show results as real
advice until real USDA data replaces it.

## How it works

1. `POST /webhooks/vapi` receives Vapi's `end-of-call-report`. Other event types
   are ignored.
2. `app/profile.py` reads `message.analysis.structuredData` and cleans loose
   values ("about 120 acres", "Iowa", "180k", "yes"). Anything unclear becomes
   unknown; nothing is guessed.
3. `app/matching.py` ranks programs by how well their text fits the farmer's
   story, then checks each rule (state, crop, damage type, loss %, income, farm
   size, insurance, years farming, organic, deadline) as met, blocked or unknown.
4. Status: any blocked rule = `not_eligible`, any unknown = `possible` (with the
   follow-up questions), otherwise `likely`. Results are sorted by status, then
   relevance, then amount.
5. The profile and matches are saved under the call ID. Replaying the same call
   returns the saved result.
6. `GET /api/matches/{call_id}` returns `{call_id, created_at, profile, matches}`.

## Fields expected from Vapi

Configure these in the assistant's structured data. Free-form answers are fine.

| Field | Example |
| --- | --- |
| `farmer_name` | Dale Hansen |
| `state` | Iowa |
| `county` | Story County |
| `crops` | corn and some soybeans |
| `damage_type` | hail storm |
| `acres_damaged` | about 120 acres |
| `total_acres` | 300 |
| `loss_percent` | 60% |
| `loss_date` | 2026-10-03 (ISO date) |
| `annual_income` | $180,000 |
| `has_crop_insurance` | yes |
| `years_farming` | 22 |
| `is_organic` | no |

The caller's number comes from `message.call.customer.number`. The analysis
summary and transcript are used as the story for search.
`fixtures/sample-end-of-call.json` is our own sample, not a captured Vapi event.
Update `app/profile.py` once a real payload is available.

## Local setup (PowerShell, Python 3.12+)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "from pathlib import Path; import secrets; p=Path('.env'); p.write_text(p.read_text().replace('WEBHOOK_SECRET=','WEBHOOK_SECRET='+secrets.token_urlsafe(32),1))"
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Send the sample call:

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); import os,json,httpx; from pathlib import Path; r=httpx.post('http://127.0.0.1:8000/webhooks/vapi',headers={'X-Vapi-Secret':os.environ['WEBHOOK_SECRET']},json=json.loads(Path('fixtures/sample-end-of-call.json').read_text())); print(r.json())"
curl http://127.0.0.1:8000/api/matches/sample-call-0001
```

Programs are loaded from `PROGRAMS_PATH` into the `programs` table on every
start, so editing the JSON and restarting is enough.

## Supabase

Set `DATABASE_URL` to the Supabase Postgres connection string. Tables are
created on start, and row-level security is turned on with no policies, so the
Supabase public API cannot read them; only this backend can.

## Vapi setup

Point the assistant's server URL at `https://<host>/webhooks/vapi` and set the
same secret as `WEBHOOK_SECRET`, either as the server secret (`X-Vapi-Secret`
header) or as a Bearer token credential. Without a secret the webhook returns 503.

## Tests

```powershell
python -m pytest -q
```

## Known limits

- Anyone with a call ID can read its results. Call IDs are long random values,
  which is acceptable for the hackathon demo; add farmer sign-in before real use.
- Search is keyword-based. Meaning-based search can be added later.
- Tables are created with SQLAlchemy `create_all`; there are no migrations.
