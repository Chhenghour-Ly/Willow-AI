<p align="center">
  <img src="frontend/public/icons/icon-192.png" alt="Willow" width="96" />
</p>

<h1 align="center">Willow AI</h1>

<p align="center"><em>the farmer's friend on the other end of the line.</em></p>

<p align="center">
  Willow is a voice-powered agent farmers can call to prepare crop insurance claims,
  then discover funding opportunities they may qualify for.
</p>

<p align="center">
  <a href="https://devpost.com/software/willow-ai">Devpost</a> · Built at De Anza Hackathon 5.0
</p>

---

## Inspiration

Imagine spending months growing your crops, only to lose everything overnight to a
storm, flood, or drought. Then come the complicated insurance policies, strict
deadlines (some policies require reporting damage within 72 hours), endless
paperwork, and the search for financial help.

What if getting help was as simple as making a phone call?

## What it does

Farmers call Willow and explain their situation in their own words. Willow listens,
asks follow-up questions, and gathers what's needed. It helps with insurance claims
and also searches for grants, loans, and disaster assistance the farmer may qualify
for, explaining why each one might fit and what to do next.

**One conversation. One assistant. Multiple paths to recovery.**

## How it works

```
Farmer calls Willow (Vapi voice agent)
        │  end-of-call report + structured farmer profile
        ▼
FastAPI backend  ──►  normalize profile  ──►  search official USDA program text
        │                                     check each requirement
        ▼
Supabase (Postgres)  ──►  results email with a 6-digit login code (with consent)
        │
        ▼
Farmer app (Vercel)  ──►  sign in with the code, review matches, fix details, approve
```

- **Voice agent:** Vapi assistant with a structured "Farmer Profile" output.
- **Matching:** each program's requirements are checked against what the farmer said and
  sorted into *why it fits*, *possible problems*, and *still to confirm*, each with an
  official source link. Missing information is asked for, never guessed.
  Results are potential matches, not eligibility decisions.
- **Programs today:** USDA EQIP (NRCS) and FSA Operating Microloan.
- **Results email:** if the farmer explicitly agrees on the call and confirms an address, the full
  results are emailed automatically (Resend), once per call. Nothing is sent without consent.
- **Login code:** each caller phone gets its own farmer profile and a unique 6-digit code,
  sent at the end of every results email with a link to the app.
- **App:** a phone-first web app farmers can add to their home screen. After signing in
  (from the app or the homepage hero) the farmer sees their latest call's matches, can
  correct what Willow heard, and approves the programs they want. Choices are saved to their
  profile; nothing is submitted to an agency automatically.
- **Database:** Supabase Postgres, reached only by the backend (row-level security, no
  public policies). SQLite works locally with no setup.

## Repository

| Folder | What's inside |
| --- | --- |
| [`fastapi/`](fastapi/) | Python FastAPI backend: Vapi webhook, profile extraction, program matching, results API |
| [`frontend/`](frontend/) | React + Vite website (Home, About) and the farmer app (Inbox, Cases) |

## Run it locally

**Backend** (Python 3.12+)

```powershell
cd fastapi
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # fill in WEBHOOK_SECRET and API_KEY
python -m pytest -q
python -m uvicorn app.main:create_app --factory --port 8000
```

**Frontend** (Node 20+)

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev                      # http://localhost:5173
```

More detail in [`fastapi/README.md`](fastapi/README.md) and [`frontend/README.md`](frontend/README.md).

## Deploy

| Piece | Where | Settings |
| --- | --- | --- |
| Frontend | Vercel ([willow-ai.vercel.app](https://willow-ai.vercel.app)), root `frontend/` | `VITE_API_URL` = public backend URL, `VITE_HOTLINE` |
| Backend | Runs locally, exposed with `ngrok http 8000` | `fastapi/.env`; `FRONTEND_ORIGIN=https://willow-ai.vercel.app,http://localhost:5173` |
| Database | Supabase | `DATABASE_URL` in `fastapi/.env` only (Session pooler URI) |
| Voice | Vapi | Server URL `https://<ngrok>/webhooks/vapi` |

Supabase credentials never go in Vercel: the frontend only talks to the backend.

## Challenges

Making Willow understand farmers clearly across accents and farming terms, and finding
accurate program information when every program has different requirements and
deadlines. Most of all: we didn't want Willow to invent information or give false hope
to someone already facing hardship.

## What we learned

Useful AI isn't just about powerful models. A good agent shouldn't only sound
confident; it must recognize uncertainty, verify important information, and know when
human approval is needed.

## What's next

A multilingual Willow that farmers anywhere can call in their own language, a larger
funding database, more insurance programs, and secure integrations to submit and track
applications.

*We may not be able to stop the next storm, flood, or drought. But no farmer should have
to face what comes afterward alone.*

## Team

Chhenghour Ly · Chira Sukumarnpiti · Lisa-Elisabeth Lisa · Rajiv Basnet · Vincent Galdamez
