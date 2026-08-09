import pytest
import os
import sys

# CI provides a real Postgres DATABASE_URL (via a service container) so
# tests catch Postgres-specific bugs - like the strftime() bug found in
# production tonight, which a SQLite-based test run would never catch.
# Local runs default to SQLite for fast iteration when no DATABASE_URL
# is already set.
USING_POSTGRES = "DATABASE_URL" in os.environ and "postgres" in os.environ["DATABASE_URL"]

if not USING_POSTGRES:
    os.environ["DATABASE_URL"] = "sqlite:///./test_rahul.db"

os.environ["SUPABASE_URL"] = "http://test.local"
os.environ["SUPABASE_KEY"] = "test-key"
os.environ["API_SECRET_KEY"] = "test-api-key-for-ci-only"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from fastapi.testclient import TestClient

if USING_POSTGRES:
    engine = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
else:
    engine = create_engine(
        "sqlite:///./test_rahul.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
Session = sessionmaker(bind=engine)

from main import app, get_db

def test_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = test_db

def setup_db():
    if USING_POSTGRES:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path) as f:
            schema_sql = f.read()
        with engine.connect() as c:
            c.execute(text(schema_sql))
            c.commit()
    else:
        # Minimal SQLite fallback for quick local iteration only - not
        # a substitute for the real Postgres schema used in CI.
        with engine.connect() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name_en TEXT NOT NULL, name_te TEXT, name_hi TEXT, sku TEXT UNIQUE NOT NULL, mrp REAL NOT NULL, selling_price REAL NOT NULL, stock_qty INTEGER DEFAULT 0, category_id INTEGER, is_oem BOOLEAN DEFAULT 0, barcode TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
            c.execute(text("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, custom_id TEXT, customer_name TEXT, customer_phone TEXT, total_amount REAL, status TEXT DEFAULT 'new', payment_type TEXT DEFAULT 'pending', pickup_time TEXT, collected_by TEXT, packed_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
            c.execute(text("CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_id INTEGER, product_name TEXT, sku TEXT, quantity INTEGER, unit_price REAL)"))
            c.execute(text("CREATE TABLE IF NOT EXISTS customer_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, token TEXT)"))
            c.commit()

setup_db()

TABLES_TO_CLEAN = [
    "order_items", "customer_tokens", "orders", "products",
    "warranty_claims", "service_reminders_sent", "active_carts",
    "customer_loyalty_points", "customer_profiles", "mechanic_profiles",
]

@pytest.fixture(autouse=True)
def clean():
    with engine.connect() as c:
        for t in TABLES_TO_CLEAN:
            try: c.execute(text(f"DELETE FROM {t}"))
            except: pass
        c.commit()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        # The API-key middleware rejects any request without this header,
        # so every test needs it - set once here rather than per-test.
        c.headers.update({"x-api-key": os.environ["API_SECRET_KEY"]})
        yield c

@pytest.fixture
def add_product(client):
    r = client.post("/products", json={
        "name_en": "Hero Splendor Brake Shoe",
        "sku": "HRO-SPL-001",
        "mrp": 250.0,
        "selling_price": 210.0,
        "stock_qty": 15
    })
    return r.json()

@pytest.fixture
def add_order(client):
    r = client.post("/orders", json={
        "customer_name": "Ravi Kumar",
        "customer_phone": "9876543210",
        "total_amount": 450.0,
        "pickup_time": "Today 5PM",
        "items": []
    })
    return r.json()

def pytest_sessionfinish(session, exitstatus):
    if not USING_POSTGRES:
        try: os.remove("test_rahul.db")
        except: pass
