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
@app.get("/orders/customer/{phone}")
def get_customer_orders(phone: str, db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT 
            o.id,
            o.custom_id,
            o.status,
            o.pickup_time,
            o.total_amount,
            o.payment_type,
            o.created_at,
            COUNT(oi.id) as item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        WHERE o.customer_phone = :phone
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 20
    """), {"phone": phone})
    
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
            "item_count": row[7]
        })
    return {"orders": orders, "total": len(orders)}

@app.get("/orders/{order_id}/items")
def get_order_items(order_id: int, db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT 
            p.id,
            p.sku,
            p.name_en,
            p.name_te,
            p.name_hi,
            oi.qty,
            oi.price,
            p.selling_price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = :order_id
    """), {"order_id": order_id})
    
    items = []
    for row in result:
        items.append({
            "id": row[0],
            "sku": row[1],
            "name_en": row[2],
            "name_te": row[3],
            "name_hi": row[4],
            "qty": row[5],
            "price": float(row[6]) if row[6] else 0,
            "selling_price": float(row[7]) if row[7] else 0
        })
    return {"items": items}
@app.put("/products/{product_id}/price")
def update_price(product_id: int, update: dict,
                 db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE products
        SET selling_price = :selling_price,
            price_updated_by = :staff_id,
            price_updated_at = NOW()
        WHERE id = :id
    """), {
        "selling_price": update.get("selling_price"),
        "staff_id": update.get("staff_id"),
        "id": product_id
    })
    db.commit()
    return {"message": "Price updated successfully"}
# ═══ STAFF PROFILE ENDPOINTS ═══

@app.get("/staff/{staff_id}/profile")
def get_staff_profile(staff_id: int,
                      db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name, role, pin, phone,
               photo_url, is_clocked_in,
               clock_in_time, clock_out_time,
               total_hours_today
        FROM staff_profiles WHERE id = :id
    """), {"id": staff_id}).fetchone()

    if not result:
        return {"error": "Staff not found"}

    return {
        "id": result[0],
        "name": result[1],
        "role": result[2],
        "pin": result[3],
        "phone": result[4],
        "photo_url": result[5],
        "is_clocked_in": result[6],
        "clock_in_time": str(result[7]) if result[7] else None,
        "clock_out_time": str(result[8]) if result[8] else None,
        "total_hours_today": float(result[9]) if result[9] else 0
    }

@app.put("/staff/{staff_id}/profile")
def update_staff_profile(staff_id: int,
                         update: dict,
                         db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE staff_profiles
        SET name = COALESCE(:name, name),
            phone = COALESCE(:phone, phone),
            photo_url = COALESCE(:photo_url, photo_url)
        WHERE id = :id
    """), {
        "name": update.get("name"),
        "phone": update.get("phone"),
        "photo_url": update.get("photo_url"),
        "id": staff_id
    })
    db.commit()
    return {"message": "Profile updated!"}

@app.post("/staff/{staff_id}/clockin")
def clock_in(staff_id: int, db: Session = Depends(get_db)):
    # Check already clocked in
    result = db.execute(text("""
        SELECT is_clocked_in FROM staff_profiles
        WHERE id = :id
    """), {"id": staff_id}).fetchone()

    if result and result[0]:
        return {"error": "Already clocked in!"}

    now = "NOW()"
    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = TRUE,
            clock_in_time = NOW(),
            clock_out_time = NULL
        WHERE id = :id
    """), {"id": staff_id})

    db.execute(text("""
        INSERT INTO attendance_log
        (staff_id, clock_in, date)
        VALUES (:staff_id, NOW(), CURRENT_DATE)
    """), {"staff_id": staff_id})

    db.commit()
    return {"message": "Clocked in successfully!",
            "clock_in_time": "NOW()"}

@app.post("/staff/{staff_id}/clockout")
def clock_out(staff_id: int, db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT is_clocked_in, clock_in_time
        FROM staff_profiles WHERE id = :id
    """), {"id": staff_id}).fetchone()

    if not result or not result[0]:
        return {"error": "Not clocked in!"}

    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = FALSE,
            clock_out_time = NOW(),
            total_hours_today = EXTRACT(
              EPOCH FROM (NOW() - clock_in_time)
            ) / 3600
        WHERE id = :id
    """), {"id": staff_id})

    db.execute(text("""
        UPDATE attendance_log
        SET clock_out = NOW(),
            hours_worked = EXTRACT(
              EPOCH FROM (NOW() - clock_in)
            ) / 3600
        WHERE staff_id = :staff_id
        AND clock_out IS NULL
        ORDER BY id DESC LIMIT 1
    """), {"staff_id": staff_id})

    db.commit()
    return {"message": "Clocked out successfully!"}

@app.get("/staff/{staff_id}/attendance")
def get_attendance(staff_id: int,
                   db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT date, clock_in, clock_out,
               hours_worked
        FROM attendance_log
        WHERE staff_id = :staff_id
        ORDER BY date DESC
        LIMIT 30
    """), {"staff_id": staff_id})

    logs = []
    for row in result:
        logs.append({
            "date": str(row[0]),
            "clock_in": str(row[1]) if row[1] else None,
            "clock_out": str(row[2]) if row[2] else None,
            "hours_worked": float(row[3]) if row[3] else 0
        })
    return {"logs": logs}
import requests as http_requests

# ═══ REPORTS ═══

@app.get("/reports/summary")
def get_reports_summary(
  period: str = "daily",
  db: Session = Depends(get_db)
):
    if period == "daily":
        date_filter = "DATE(created_at) = CURRENT_DATE"
    elif period == "weekly":
        date_filter = "created_at >= NOW() - INTERVAL '7 days'"
    else:
        date_filter = "created_at >= NOW() - INTERVAL '30 days'"

    result = db.execute(text(f"""
        SELECT
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COALESCE(SUM(CASE WHEN payment_type='cash'
              THEN total_amount ELSE 0 END), 0) as cash_revenue,
            COALESCE(SUM(CASE WHEN payment_type='upi'
              THEN total_amount ELSE 0 END), 0) as upi_revenue,
            COALESCE(SUM(CASE WHEN payment_type='pending'
              THEN total_amount ELSE 0 END), 0) as pending_revenue,
            COUNT(CASE WHEN status='collected' THEN 1 END)
              as completed_orders
        FROM orders
        WHERE {date_filter}
    """)).fetchone()

    daily = db.execute(text("""
        SELECT
            DATE(created_at) as date,
            COALESCE(SUM(total_amount), 0) as revenue,
            COUNT(*) as orders
        FROM orders
        WHERE created_at >= NOW() - INTERVAL '7 days'
        AND status = 'collected'
        GROUP BY DATE(created_at)
        ORDER BY date ASC
    """))

    daily_data = []
    for row in daily:
        daily_data.append({
            "date": str(row[0]),
            "revenue": float(row[1]),
            "orders": row[2]
        })

    return {
        "total_orders": result[0] or 0,
        "total_revenue": float(result[1] or 0),
        "cash_revenue": float(result[2] or 0),
        "upi_revenue": float(result[3] or 0),
        "pending_revenue": float(result[4] or 0),
        "completed_orders": result[5] or 0,
        "daily_data": daily_data
    }

@app.get("/reports/bestsellers")
def get_bestsellers(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT
            p.id, p.name_en, p.name_te, p.sku,
            p.selling_price,
            COALESCE(SUM(oi.qty), 0) as total_sold,
            COALESCE(SUM(oi.qty * oi.price), 0) as total_revenue
        FROM products p
        LEFT JOIN order_items oi ON p.id = oi.product_id
        LEFT JOIN orders o ON oi.order_id = o.id
          AND o.status = 'collected'
        GROUP BY p.id, p.name_en, p.name_te,
                 p.sku, p.selling_price
        ORDER BY total_sold DESC
        LIMIT 10
    """))

    items = []
    for row in result:
        items.append({
            "id": row[0],
            "name_en": row[1],
            "name_te": row[2],
            "sku": row[3],
            "selling_price": float(row[4]),
            "total_sold": row[5],
            "total_revenue": float(row[6])
        })
    return {"bestsellers": items}

# ═══ STOCK MANAGEMENT ═══

@app.put("/products/{product_id}/stock")
def update_stock(
  product_id: int,
  update: dict,
  db: Session = Depends(get_db)
):
    new_qty = update.get("stock_qty", 0)
    staff_id = update.get("staff_id")

    db.execute(text("""
        UPDATE products SET stock_qty = :qty WHERE id = :id
    """), {"qty": new_qty, "id": product_id})

    try:
        db.execute(text("""
            INSERT INTO stock_movements
            (product_id, qty_change, new_qty, staff_id, reason)
            VALUES (:pid, :qc, :nq, :sid, 'manual_update')
        """), {
            "pid": product_id,
            "qc": new_qty,
            "nq": new_qty,
            "sid": staff_id
        })
    except:
        pass

    db.commit()
    return {"message": "Stock updated!", "new_qty": new_qty}

@app.get("/products/low-stock")
def get_low_stock(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name_en, name_te, sku,
               stock_qty, selling_price
        FROM products
        WHERE stock_qty <= 5
        ORDER BY stock_qty ASC
    """))

    items = []
    for row in result:
        items.append({
            "id": row[0],
            "name_en": row[1],
            "name_te": row[2],
            "sku": row[3],
            "stock_qty": row[4],
            "selling_price": float(row[5])
        })
    return {"low_stock": items, "count": len(items)}

# ═══ PUSH NOTIFICATIONS ═══

@app.post("/push-tokens")
def save_push_token(
  data: dict,
  db: Session = Depends(get_db)
):
    token = data.get("token")
    staff_id = data.get("staff_id")
    if not token:
        return {"error": "No token"}

    db.execute(text("""
        INSERT INTO push_tokens (staff_id, token, updated_at)
        VALUES (:sid, :token, NOW())
        ON CONFLICT (token) DO UPDATE
        SET staff_id = :sid, updated_at = NOW()
    """), {"sid": staff_id, "token": token})
    db.commit()
    return {"message": "Token saved!"}

@app.post("/notify/new-order")
def notify_new_order(
  data: dict,
  db: Session = Depends(get_db)
):
    customer_name = data.get("customer_name", "Customer")
    total = data.get("total", 0)
    pickup_time = data.get("pickup_time", "")
    custom_id = data.get("custom_id", "")

    result = db.execute(text(
        "SELECT DISTINCT token FROM push_tokens WHERE token IS NOT NULL"
    ))
    tokens = [row[0] for row in result]
    if not tokens:
        return {"message": "No tokens"}

    messages = [{
        "to": token,
        "title": f"🔔 New Order {custom_id}!",
        "body": f"👤 {customer_name} • ₹{total} • 📅 {pickup_time}",
        "sound": "default",
        "badge": 1
    } for token in tokens]

    try:
        resp = http_requests.post(
            "https://exp.host/--/api/v2/push/send",
            json=messages,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return {"message": f"Notified {len(tokens)} devices"}
    except Exception as e:
        return {"error": str(e)}
    # ═══ CUSTOMER TOKENS ═══
@app.post("/customer-tokens")
def save_customer_token(
  data: dict, db: Session = Depends(get_db)
):
    token = data.get("token")
    phone = data.get("phone")
    if not token or not phone:
        return {"error": "Missing data"}
    db.execute(text("""
        INSERT INTO customer_tokens (phone, token, updated_at)
        VALUES (:phone, :token, NOW())
        ON CONFLICT (phone) DO UPDATE
        SET token = :token, updated_at = NOW()
    """), {"phone": phone, "token": token})
    db.commit()
    return {"message": "Token saved!"}

@app.post("/notify/order-ready/{order_id}")
def notify_order_ready(
  order_id: int, db: Session = Depends(get_db)
):
    order = db.execute(text("""
        SELECT customer_phone, custom_id, total_amount
        FROM orders WHERE id = :id
    """), {"id": order_id}).fetchone()
    if not order:
        return {"error": "Order not found"}
    token_row = db.execute(text("""
        SELECT token FROM customer_tokens
        WHERE phone = :phone
    """), {"phone": order[0]}).fetchone()
    if not token_row:
        return {"message": "No token"}
    try:
        http_requests.post(
            "https://exp.host/--/api/v2/push/send",
            json={
                "to": token_row[0],
                "title": "🎉 Order Ready! Come Pick Up!",
                "body": f"Order {order[1] or f'RAS-{order_id}'} is ready! ₹{order[2]}",
                "sound": "default", "badge": 1
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return {"message": "Customer notified!"}
    except Exception as e:
        return {"error": str(e)}