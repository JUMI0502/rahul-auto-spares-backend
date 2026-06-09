# New Rahul Auto Spares — FastAPI Backend

Live production backend for a two-wheeler spare parts store in Nandyal, Andhra Pradesh.

## Live API
`https://rahul-auto-spares-backend.onrender.com`

## Tech Stack
- **FastAPI** + SQLAlchemy + PostgreSQL (Supabase)
- **Deployed** on Render (auto-deploy from GitHub)
- **42+ pytest tests** with SQLite fixtures

## Key Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /products | All spare parts catalog |
| POST | /products | Add new product |
| GET | /products/barcode/{code} | Search by barcode/SKU |
| GET | /products/brand/{prefix} | Filter by brand |
| POST | /orders | Place new order |
| PUT | /orders/{id} | Update order status |
| GET | /customers/analytics | Top spenders, monthly revenue |
| POST | /notify/broadcast | Push notification to all customers |
| GET | /reports/daily-summary | Daily sales summary |

## Run Locally
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Run Tests
```bash
pip install pytest httpx pytest-mock
python -m pytest tests/ -v
```

## Test Coverage
- Product CRUD and barcode search
- Order lifecycle (new → packing → ready → collected)
- Customer analytics and revenue calculations  
- Push notification broadcast
- SQLite NullPool isolation between tests

## Apps Using This API
- **Customer App** — Browse parts, place orders, loyalty points
- **Store Staff App** — Manage orders, inventory, analytics
