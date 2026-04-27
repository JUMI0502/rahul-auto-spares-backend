from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import get_db
from sqlalchemy import text

app = FastAPI(
    title="New Rahul Auto Spares API",
    description="Backend for New Rahul Auto Spares, Nandyal",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "message": "New Rahul Auto Spares API is LIVE!",
        "store": "New Rahul Auto Spares",
        "location": "Telugu Peta, Nandyal, Andhra Pradesh",
        "phone": "08514-244944",
        "status": "open"
    }

@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, sku, name_en, name_te,
               name_hi, price, mrp, 
               selling_price, stock_qty
        FROM products
        ORDER BY id
    """))
    products = []
    for row in result:
        products.append({
            "id": row[0],
            "sku": row[1],
            "name_en": row[2],
            "name_te": row[3],
            "name_hi": row[4],
            "price": float(row[5]),
            "mrp": float(row[6]),
            "selling_price": float(row[7]),
            "stock_qty": row[8]
        })
    return {
        "store": "New Rahul Auto Spares",
        "total_products": len(products),
        "products": products
    }

@app.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, name FROM vehicle_brands ORDER BY id"
    ))
    brands = []
    for row in result:
        brands.append({
            "id": row[0],
            "name": row[1]
        })
    return {"brands": brands}

@app.get("/staff")
def get_staff(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT name, phone, role 
        FROM staff_profiles
        ORDER BY id
    """))
    staff = []
    for row in result:
        staff.append({
            "name": row[0],
            "phone": row[1],
            "role": row[2]
        })
    return {
        "store": "New Rahul Auto Spares",
        "team": staff
    }