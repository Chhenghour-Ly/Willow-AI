# Willow frontend

Website (Home, About, Contact) and the phone-shaped Willow app (Inbox, Cases,
case pages, "Your details") in one Vite + React app.

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev        # http://localhost:5173
npm test
```

- `/` `/about` `/contact`: the website.
- `/app`: the app. Full screen on a phone; inside a phone frame on wide screens.
- `/r/<call_id>`: link for the after-call text. Remembers the call on this
  device and opens the inbox.

With `VITE_API_URL` empty, the app shows the built-in sample results
(`src/sample-matches.json`). Set it to the FastAPI backend to load real
results from `GET /api/matches/{call_id}`.

Approvals and edits are stored in the browser only for now. Program data is
synthetic sample data.
