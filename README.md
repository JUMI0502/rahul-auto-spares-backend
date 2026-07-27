# Rahul Auto Spares — Backend API

FastAPI backend for the New Rahul Auto Spares customer and store apps.

## Live URL
```
https://rahul-auto-spares-backend.onrender.com
```

## Authentication
Every endpoint (except `GET /`) requires an API key header:
```
x-api-key: <see team lead for current key>
```
Requests without a valid key return `401 Unauthorized`.

## Rate Limiting
100 requests per minute per IP address. Exceeding this returns `429 Too Many Requests`.

## Local Setup
```bash
git clone <repo-url>
cd rahul-auto-spares-backend
pip install -r requirements.txt --break-system-packages
```

Create a `.env` file (not committed) with:
```
DATABASE_URL=<Supabase Postgres connection string — see team lead>
API_SECRET_KEY=<see team lead>
```

Run locally:
```bash
uvicorn main:app --reload
```

## Database
PostgreSQL hosted on Supabase (free tier). Note: free tier pauses after 7 days
of no activity — if the API seems unresponsive, check the Supabase dashboard
and click "Resume" if paused. No automated backups on free tier; a manual
backup should be taken periodically (`pg_dump`).

## Testing Notes / Known Staff PINs
| Name | Role | PIN |
|---|---|---|
| Abdul Azeess | Owner | 9642 |
| Chand Basha | Senior | 9704 |
| Masha | Staff | 8919 |
| Hussain Basha | Staff | 4444 |
| Khaja | Staff | 1234 |

Test customer phone number used during development: `1122334455`

## Known Limitations
- No automated tests yet
- CORS is permissive (`allow_origins=["*"]`) — acceptable since mobile clients
  don't send Origin headers, but worth restricting if a web client is ever added
- Product catalog's `is_oem` field defaults to `false` for all existing
  products until manually classified by staff via the store app
- Debug/patch scripts (`add_*.py`, `fix_*.py`) may appear untracked locally —
  these are development scratch files, safe to ignore, not part of the app

## Reporting Bugs
Please include: endpoint hit, request body sent, expected vs actual response,
and timestamp (helps cross-reference Render logs).
