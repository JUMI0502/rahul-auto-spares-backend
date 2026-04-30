from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal, engine
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root():
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
               name_hi, price, mrp, selling_price, stock_qty
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
            "price": float(row[5]) if row[5] else 0,
            "mrp": float(row[6]) if row[6] else 0,
            "selling_price": float(row[7]) if row[7] else 0,
            "stock_qty": row[8]
        })
    return {"store": "New Rahul Auto Spares",
            "total_products": len(products),
            "products": products}

@app.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT id, name FROM vehicle_brands"))
    return {"brands": [{"id": r[0], "name": r[1]} for r in result]}

@app.get("/staff")
def get_staff(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, name, role FROM staff_profiles WHERE is_active=true"
    ))
    return {"staff": [{"id": r[0], "name": r[1], "role": r[2]}
                      for r in result]}

@app.post("/orders")
def create_order(order: dict, db: Session = Depends(get_db)):
    # Generate custom order ID like RAS-001
    count_result = db.execute(text("SELECT COUNT(*) FROM orders"))
    count = count_result.fetchone()[0]
    custom_id = f"RAS-{str(count + 1).zfill(3)}"

    result = db.execute(text("""
        INSERT INTO orders
        (custom_id, status, pickup_time, total_amount,
         customer_name, customer_phone, created_at)
        VALUES
        (:custom_id, :status, :pickup_time, :total_amount,
         :customer_name, :customer_phone, NOW())
        RETURNING id
    """), {
        "custom_id": custom_id,
        "status": "new",
        "pickup_time": order.get("pickup_time"),
        "total_amount": order.get("total_amount"),
        "customer_name": order.get("customer_name", "Customer"),
        "customer_phone": order.get("customer_phone", ""),
    })
    order_id = result.fetchone()[0]

    for item in order.get("items", []):
        db.execute(text("""
            INSERT INTO order_items
            (order_id, product_id, qty, price)
            VALUES (:order_id, :product_id, :qty, :price)
        """), {
            "order_id": order_id,
            "product_id": item["id"],
            "qty": item["qty"],
            "price": item["selling_price"]
        })

    db.commit()
    return {
        "order_id": order_id,
        "custom_id": custom_id,
        "status": "created"
    }

@app.get("/orders")
def get_orders(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT
            o.id,
            o.custom_id,
            o.status,
            o.pickup_time,
            o.total_amount,
            o.payment_type,
            o.created_at,
            o.collected_by,
            o.customer_name,
            o.customer_phone,
            COUNT(oi.id) as item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 50
    """))
    orders = []
    for row in result:
        orders.append({
            "id": row[0],
            "custom_id": row[1] or f"RAS-{row[0]}",
            "status": row[2],
            "pickup_time": row[3],
            "total_amount": float(row[4]) if row[4] else 0,
            "payment_type": row[5],
            "created_at": str(row[6]),
            "collected_by": row[7],
            "customer_name": row[8] or "Customer",
            "customer_phone": row[9] or "",
            "item_count": row[10]
        })
    return {"orders": orders}

@app.put("/orders/{order_id}")
def update_order(order_id: int, update: dict,
                 db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE orders
        SET status = :status,
            payment_type = :payment_type,
            payment_time = NOW(),
            collected_by = :collected_by
        WHERE id = :id
    """), {
        "status": update.get("status"),
        "payment_type": update.get("payment_type"),
        "collected_by": update.get("staff_id"),
        "id": order_id
    })
    db.commit()
    return {"message": "Order updated successfully"}