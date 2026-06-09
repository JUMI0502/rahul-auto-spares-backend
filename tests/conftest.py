import pytest
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_rahul.db"
os.environ["SUPABASE_URL"] = "http://test.local"
os.environ["SUPABASE_KEY"] = "test-key"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from fastapi.testclient import TestClient

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
    with engine.connect() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name_en TEXT NOT NULL, name_te TEXT, sku TEXT UNIQUE NOT NULL, mrp REAL NOT NULL, selling_price REAL NOT NULL, stock_qty INTEGER DEFAULT 0, barcode TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, custom_id TEXT, customer_name TEXT, customer_phone TEXT, total_amount REAL, status TEXT DEFAULT 'new', payment_type TEXT DEFAULT 'pending', pickup_time TEXT, collected_by TEXT, packed_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_id INTEGER, product_name TEXT, sku TEXT, quantity INTEGER, unit_price REAL)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS customer_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, token TEXT)"))
        c.commit()

setup_db()

@pytest.fixture(autouse=True)
def clean():
    with engine.connect() as c:
        for t in ["order_items","customer_tokens","orders","products"]:
            try: c.execute(text(f"DELETE FROM {t}"))
            except: pass
        c.commit()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
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
    try: os.remove("test_rahul.db")
    except: pass
