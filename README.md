## Before You Start
Request the following from the project owner before setup:
- `.env` file (DATABASE_URL, API_SECRET_KEY)
- Confirm Python 3.x and pip installed

## Note on Supabase Free Tier
The database pauses after 7 days of inactivity. If the API seems unresponsive,
check the Supabase dashboard and click "Resume."

## Questions or Blockers
Contact Amini Masthan Reddy (aminimasthanreddy@gmail.com) if setup fails or
this README is outdated.
# Rahul Auto Spares — Backend API

FastAPI backend for the New Rahul Auto Spares customer and store apps.

## Live URL
```
https://rahul-auto-spares-backend.onrender.com
```

## Authentication
Every endpoint (except `GET /` and `GET /privacy-policy`) requires an API key header:
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

**Customer accounts now require a 4-digit PIN** (set on first login). This is
new — customers created before this feature will be prompted to create a PIN
on their next login.

## Feature Endpoints Added Since Initial Build
- **Mechanic Approvals**: `/mechanics/*` — registration, approval, edit, delete
- **OEM Classification**: `products.is_oem` field, `/products/{id}/oem`
- **Service Reminders**: `/customers/service-due`, nudges customers 60+ days inactive
- **Warranty & Returns**: `/warranty-claims/*` — log, track, resolve defect claims
- **Referral Program**: built into `/orders` — first-order referrals earn bonus points automatically
- **Business Health KPIs**: `/reports/business-health` — staff productivity, warranty rate, retention
- **Abandoned Cart Recovery**: `/cart/save`, `/carts/abandoned` — tracks carts idle 3+ hours
- **Inventory Forecasting**: `/products/forecast` — predicts days-until-stockout from sales velocity
- **Customer PIN Verification**: `/customers/set-pin`, `/customers/verify-pin` — closes a real privacy gap (previously any phone number could access anyone's order history/points)
- **Account Deletion**: `DELETE /customers/{phone}/account` — required for Play Store compliance
- **Privacy Policy**: `GET /privacy-policy` — public HTML page, no API key needed

## Known Limitations
- No automated tests yet
- CORS is permissive (`allow_origins=["*"]`) but `allow_credentials=False` —
  acceptable since mobile clients don't send Origin headers
- Product catalog's `is_oem` field defaults to `false` for all existing
  products until manually classified by staff via the store app
- Delivery feature exists but is disabled (`DELIVERY_ENABLED = false` in
  customer app) — business decision, not a bug
- Debug/patch scripts (`add_*.py`, `fix_*.py`, `remove_*.py`) may appear
  untracked locally — these are development scratch files, safe to ignore

## Reporting Bugs
Please include: endpoint hit, request body sent, expected vs actual response,
and timestamp (helps cross-reference Render logs).
# dual-push test Sun Aug  2 00:40:57 EDT 2026
