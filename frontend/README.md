# Willow frontend

Website (Home, About) and the phone-shaped Willow app (Inbox, Cases,
case pages, "Your details") in one Vite + React app.

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev        # http://localhost:5173
npm test
```

- `/` `/about`: the website. The hero has a 6-digit code sign-in that opens the app.
- `/app`: the farmer app. Full screen on a phone; inside a phone frame on wide screens.
  Asks for the login code from the results email, then loads the farmer's latest call
  from `GET /api/me` (header `X-Farmer-Code`).

Approving a program, editing a detail and "Looks right" are saved to the farmer's
profile in Willow's database (`POST /api/me/approvals`, `POST /api/me/details`).
Approving records the farmer's choice; nothing is submitted to an agency. Which
messages were opened is remembered in the browser only. The homepage phone preview
uses sample data (`src/sample-matches.json`).

## Environment

Only public values go here; every `VITE_` variable is visible in the browser.
Never put Supabase or other backend secrets in the frontend.

| Variable | Value |
| --- | --- |
| `VITE_API_URL` | Public URL of the FastAPI backend (e.g. the ngrok URL) |
| `VITE_HOTLINE` | Hotline in E.164, e.g. `+14086862433` |

On Vercel, set both under Project → Settings → Environment Variables and redeploy:
Vite bakes them in at build time.
