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
@app.post("/orders")
def create_order(order: dict, db: Session = Depends(get_db)):
    result = db.execute(text("""
        INSERT INTO orders 
        (status, pickup_time, total_amount, created_at)
        VALUES 
        (:status, :pickup_time, :total_amount, NOW())
        RETURNING id
    """), {
        "status": "new",
        "pickup_time": order.get("pickup_time"),
        "total_amount": order.get("total_amount")
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
    return {"order_id": order_id, "status": "created"}

@app.get("/orders")
def get_orders(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT 
            o.id,
            o.status,
            o.pickup_time,
            o.total_amount,
            o.payment_type,
            o.created_at,
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
            "status": row[1],
            "pickup_time": row[2],
            "total_amount": float(row[3]) if row[3] else 0,
            "payment_type": row[4],
            "created_at": str(row[5]),
            "item_count": row[6]
        })
    return {"orders": orders}

@app.put("/orders/{order_id}")
def update_order(order_id: int, update: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE orders 
        SET status = :status,
            payment_type = :payment_type,
            payment_time = NOW()
        WHERE id = :id
    """), {
        "status": update.get("status"),
        "payment_type": update.get("payment_type"),
        "id": order_id
    })
    db.commit()
    return {"message": "Order updated successfully"}