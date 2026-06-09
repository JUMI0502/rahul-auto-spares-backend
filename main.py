from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, date
import os
from dotenv import load_dotenv
import requests as http_requests

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

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

# ════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════

@app.get("/")
def root():
    return {"message": "Rahul Auto Spares API Running!"}

# ════════════════════════════════════
# PRODUCTS
# ════════════════════════════════════

@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name_en, name_te, name_hi,
               sku, mrp, selling_price,
               stock_qty, category_id
        FROM products
        ORDER BY sku ASC
    """))
    products = []
    for row in result:
        products.append({
            "id": row[0],
            "name_en": row[1],
            "name_te": row[2],
            "name_hi": row[3],
            "sku": row[4],
            "mrp": float(row[5] or 0),
            "selling_price": float(row[6] or 0),
            "stock_qty": row[7] or 0,
            "category_id": row[8]
        })
    return {"products": products}

# ── IMPORTANT: low-stock MUST come
#    BEFORE /{product_id} ──

@app.get("/products/low-stock")
def get_low_stock(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name_en, name_te,
               sku, stock_qty, selling_price
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
            "selling_price": float(row[5] or 0)
        })
    return {"low_stock": items, "count": len(items)}

@app.put("/products/{product_id}/price")
def update_price(
    product_id: int,
    update: dict,
    db: Session = Depends(get_db)
):
    new_price = update.get("selling_price", 0)
    db.execute(text("""
        UPDATE products
        SET selling_price = :price
        WHERE id = :id
    """), {"price": new_price, "id": product_id})
    db.commit()
    return {"message": "Price updated!", "new_price": new_price}

@app.put("/products/{product_id}/stock")
def update_stock(
    product_id: int,
    update: dict,
    db: Session = Depends(get_db)
):
    new_qty = update.get("stock_qty", 0)
    staff_id = update.get("staff_id")
    db.execute(text("""
        UPDATE products
        SET stock_qty = :qty WHERE id = :id
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

# ════════════════════════════════════
# ORDERS
# ════════════════════════════════════

@app.get("/orders")
def get_orders(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT
            o.id, o.custom_id, o.status,
            o.total_amount, o.pickup_time,
            o.payment_type, o.collected_by,
            o.customer_name, o.customer_phone,
            o.created_at,
            COUNT(oi.id) as item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id
        ORDER BY o.created_at DESC
    """))
    orders = []
    for row in result:
        orders.append({
            "id": row[0],
            "custom_id": row[1],
            "status": row[2],
            "total_amount": float(row[3] or 0),
            "pickup_time": row[4],
            "payment_type": row[5],
            "collected_by": row[6],
            "customer_name": row[7],
            "customer_phone": row[8],
            "created_at": str(row[9]),
            "item_count": row[10] or 0
        })
    return {"orders": orders}

@app.get("/orders/customer/{phone}")
def get_customer_orders(
    phone: str,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT id, custom_id, status,
               total_amount, pickup_time,
               payment_type, created_at
        FROM orders
        WHERE customer_phone = :phone
        ORDER BY created_at DESC
        LIMIT 20
    """), {"phone": phone})
    orders = []
    for row in result:
        orders.append({
            "id": row[0],
            "custom_id": row[1],
            "status": row[2],
            "total_amount": float(row[3] or 0),
            "pickup_time": row[4],
            "payment_type": row[5],
            "created_at": str(row[6])
        })
    return {"orders": orders}

@app.post("/orders")
def create_order(
    data: dict,
    db: Session = Depends(get_db)
):
    pickup_time = data.get("pickup_time", "")
    total_amount = data.get("total_amount", 0)
    customer_name = data.get("customer_name", "")
    customer_phone = data.get("customer_phone", "")
    items = data.get("items", [])

    count = db.execute(
        text("SELECT COUNT(*) FROM orders")
    ).fetchone()[0]
    custom_id = f"RAS-{(count + 1):03d}"

    result = db.execute(text("""
        INSERT INTO orders
        (custom_id, status, total_amount, pickup_time,
         customer_name, customer_phone, payment_type)
        VALUES (:cid, 'new', :total, :pickup,
                :cname, :cphone, 'pending')
        RETURNING id
    """), {
        "cid": custom_id,
        "total": total_amount,
        "pickup": pickup_time,
        "cname": customer_name,
        "cphone": customer_phone
    })
    order_id = result.fetchone()[0]

    for item in items:
        price = item.get("mechanic_price") or \
                item.get("selling_price", 0)
        db.execute(text("""
            INSERT INTO order_items
            (order_id, product_id, qty, price)
            VALUES (:oid, :pid, :qty, :price)
        """), {
            "oid": order_id,
            "pid": item.get("id"),
            "qty": item.get("qty", 1),
            "price": price
        })

        db.execute(text("""
            UPDATE products
            SET stock_qty = GREATEST(0, stock_qty - :qty)
            WHERE id = :pid
        """), {
            "qty": item.get("qty", 1),
            "pid": item.get("id")
        })

    db.commit()
    return {
        "message": "Order created!",
        "order_id": order_id,
        "custom_id": custom_id
    }

@app.put("/orders/{order_id}")
def update_order(
    order_id: int,
    data: dict,
    db: Session = Depends(get_db)
):
    status = data.get("status")
    payment_type = data.get("payment_type")
    staff_id = data.get("staff_id")

    db.execute(text("""
        UPDATE orders
        SET status = :status,
            payment_type = :payment_type,
            collected_by = CASE
                WHEN :status = 'collected'
                THEN :staff_id
                ELSE collected_by
            END
        WHERE id = :id
    """), {
        "status": status,
        "payment_type": payment_type,
        "staff_id": staff_id,
        "id": order_id
    })
    db.commit()
    return {"message": "Order updated!"}

@app.get("/orders/{order_id}/items")
def get_order_items(
    order_id: int,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT
            oi.id, oi.qty, oi.price,
            p.name_en, p.name_te, p.sku
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = :oid
    """), {"oid": order_id})
    items = []
    for row in result:
        items.append({
            "id": row[0],
            "qty": row[1],
            "price": float(row[2] or 0),
            "name_en": row[3],
            "name_te": row[4],
            "sku": row[5]
        })
    return {"items": items}

# ════════════════════════════════════
# STAFF
# ════════════════════════════════════

@app.get("/staff")
def get_staff(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name, role, phone,
               is_clocked_in, total_hours_today
        FROM staff_profiles
        ORDER BY id ASC
    """))
    staff = []
    for row in result:
        staff.append({
            "id": row[0],
            "name": row[1],
            "role": row[2],
            "phone": row[3],
            "is_clocked_in": row[4],
            "total_hours_today": float(row[5] or 0)
        })
    return {"staff": staff}

@app.get("/staff/{staff_id}/profile")
def get_staff_profile(
    staff_id: int,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT id, name, role, phone,
               photo_url, is_clocked_in,
               clock_in_time, total_hours_today
        FROM staff_profiles WHERE id = :id
    """), {"id": staff_id}).fetchone()

    if not result:
        return {"error": "Staff not found"}

    return {
        "id": result[0],
        "name": result[1],
        "role": result[2],
        "phone": result[3],
        "photo_url": result[4],
        "is_clocked_in": result[5],
        "clock_in_time": str(result[6]) if result[6] else None,
        "total_hours_today": float(result[7] or 0)
    }

@app.put("/staff/{staff_id}/profile")
def update_staff_profile(
    staff_id: int,
    data: dict,
    db: Session = Depends(get_db)
):
    phone = data.get("phone")
    photo_url = data.get("photo_url")
    db.execute(text("""
        UPDATE staff_profiles
        SET phone = COALESCE(:phone, phone),
            photo_url = COALESCE(:photo_url, photo_url)
        WHERE id = :id
    """), {
        "phone": phone,
        "photo_url": photo_url,
        "id": staff_id
    })
    db.commit()
    return {"message": "Profile updated!"}

@app.post("/staff/{staff_id}/clockin")
def clock_in(
    staff_id: int,
    db: Session = Depends(get_db)
):
    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = TRUE,
            clock_in_time = datetime('now')
        WHERE id = :id
    """), {"id": staff_id})
    db.execute(text("""
        INSERT INTO attendance_log
        (staff_id, clock_in, date)
        VALUES (:sid, datetime('now'), date('now'))
    """), {"sid": staff_id})
    db.commit()
    return {"message": "Clocked in!"}

@app.post("/staff/{staff_id}/clockout")
def clock_out(
    staff_id: int,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT clock_in_time FROM staff_profiles
        WHERE id = :id
    """), {"id": staff_id}).fetchone()

    hours = 0
    if result and result[0]:
        from datetime import datetime, date
        now = datetime.now()
        diff = now - result[0].replace(tzinfo=None)
        hours = round(diff.total_seconds() / 3600, 2)

    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = FALSE,
            clock_out_time = datetime('now'),
            total_hours_today = :hours
        WHERE id = :id
    """), {"hours": hours, "id": staff_id})

    db.execute(text("""
        UPDATE attendance_log
        SET clock_out = datetime('now'),
            hours_worked = :hours
        WHERE staff_id = :sid
          AND date = date('now')
          AND clock_out IS NULL
    """), {"hours": hours, "sid": staff_id})

    db.commit()
    return {"message": "Clocked out!", "hours_worked": hours}

@app.get("/staff/{staff_id}/attendance")
def get_attendance(
    staff_id: int,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT date, clock_in, clock_out,
               hours_worked
        FROM attendance_log
        WHERE staff_id = :sid
        ORDER BY date DESC
        LIMIT 30
    """), {"sid": staff_id})
    logs = []
    for row in result:
        logs.append({
            "date": str(row[0]),
            "clock_in": str(row[1]) if row[1] else None,
            "clock_out": str(row[2]) if row[2] else None,
            "hours_worked": float(row[3] or 0)
        })
    return {"attendance": logs}

# ════════════════════════════════════
# REPORTS
# ════════════════════════════════════

@app.get("/reports/summary")
def get_reports_summary(
    period: str = "daily",
    db: Session = Depends(get_db)
):
    if period == "daily":
        date_filter = "date(created_at) = date('now')"
    elif period == "weekly":
        date_filter = "created_at >= datetime('now') - INTERVAL '7 days'"
    else:
        date_filter = "created_at >= datetime('now') - INTERVAL '30 days'"

    result = db.execute(text(f"""
        SELECT
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COALESCE(SUM(CASE WHEN payment_type='cash'
              THEN total_amount ELSE 0 END), 0) as cash,
            COALESCE(SUM(CASE WHEN payment_type='upi'
              THEN total_amount ELSE 0 END), 0) as upi,
            COALESCE(SUM(CASE WHEN payment_type='pending'
              THEN total_amount ELSE 0 END), 0) as pending,
            COUNT(CASE WHEN status='collected' THEN 1 END)
              as completed
        FROM orders WHERE {date_filter}
    """)).fetchone()

    daily = db.execute(text("""
        SELECT date(created_at) as date,
               COALESCE(SUM(total_amount), 0) as revenue,
               COUNT(*) as orders
        FROM orders
        WHERE created_at >= datetime('now') - INTERVAL '7 days'
          AND status = 'collected'
        GROUP BY date(created_at)
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
            p.id, p.name_en, p.name_te,
            p.sku, p.selling_price,
            COALESCE(SUM(oi.qty), 0) as total_sold,
            COALESCE(SUM(oi.qty * oi.price), 0) as revenue
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
            "selling_price": float(row[4] or 0),
            "total_sold": row[5],
            "total_revenue": float(row[6] or 0)
        })
    return {"bestsellers": items}

# ════════════════════════════════════
# PUSH NOTIFICATIONS
# ════════════════════════════════════

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
        VALUES (:sid, :token, datetime('now'))
        ON CONFLICT (token) DO UPDATE
        SET staff_id = :sid, updated_at = datetime('now')
    """), {"sid": staff_id, "token": token})
    db.commit()
    return {"message": "Token saved!"}

@app.post("/customer-tokens")
def save_customer_token(
    data: dict,
    db: Session = Depends(get_db)
):
    token = data.get("token")
    phone = data.get("phone")
    if not token or not phone:
        return {"error": "Missing data"}
    db.execute(text("""
        INSERT INTO customer_tokens (phone, token, updated_at)
        VALUES (:phone, :token, datetime('now'))
        ON CONFLICT (phone) DO UPDATE
        SET token = :token, updated_at = datetime('now')
    """), {"phone": phone, "token": token})
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
        "SELECT DISTINCT token FROM push_tokens"
        " WHERE token IS NOT NULL"
    ))
    tokens = [row[0] for row in result]
    if not tokens:
        return {"message": "No tokens"}

    messages = [{
        "to": token,
        "title": f"🔔 New Order {custom_id}!",
        "body": f"👤 {customer_name} • ₹{total}"
                f" • 📅 {pickup_time}",
        "sound": "default",
        "badge": 1
    } for token in tokens]

    try:
        http_requests.post(
            "https://exp.host/--/api/v2/push/send",
            json=messages,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return {"message": f"Notified {len(tokens)} devices"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/notify/order-ready/{order_id}")
def notify_order_ready(
    order_id: int,
    db: Session = Depends(get_db)
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
        return {"message": "No customer token"}

    try:
        http_requests.post(
            "https://exp.host/--/api/v2/push/send",
            json={
                "to": token_row[0],
                "title": "🎉 Order Ready! Come Pick Up!",
                "body": f"Order {order[1] or f'RAS-{order_id}'}"
                        f" is ready! ₹{order[2]}",
                "sound": "default",
                "badge": 1
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return {"message": "Customer notified!"}
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════
# MECHANIC APPROVAL SYSTEM
# ════════════════════════════════════

@app.post("/mechanics/register")
def register_mechanic(
    data: dict,
    db: Session = Depends(get_db)
):
    name = data.get("name", "")
    phone = data.get("phone", "")
    shop_name = data.get("shop_name", "")
    area = data.get("area", "")

    if not name or not phone:
        return {"error": "Name and phone required"}

    existing = db.execute(text("""
        SELECT id, status FROM mechanic_profiles
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()

    if existing:
        existing_id = existing[0]
        existing_status = existing[1]

        # Already approved
        if existing_status == 'approved':
            return {
                "id": existing_id,
                "status": "approved",
                "message": "Already approved!"
            }

        # Still pending
        if existing_status == 'pending':
            return {
                "id": existing_id,
                "status": "pending",
                "message": "Still pending approval!"
            }

        # Was rejected — allow re-registration!
        if existing_status == 'rejected':
            db.execute(text("""
                UPDATE mechanic_profiles
                SET status = 'pending',
                    name = :name,
                    shop_name = :shop_name,
                    area = :area,
                    approved_by = NULL,
                    approved_at = NULL,
                    notes = NULL
                WHERE phone = :phone
            """), {
                "name": name,
                "shop_name": shop_name,
                "area": area,
                "phone": phone
            })
            db.commit()
            return {
                "id": existing_id,
                "status": "pending",
                "message": "Re-application submitted!"
            }

    # New registration
    result = db.execute(text("""
        INSERT INTO mechanic_profiles
        (name, phone, shop_name, area, status)
        VALUES (:name, :phone, :shop_name, :area, 'pending')
        RETURNING id
    """), {
        "name": name,
        "phone": phone,
        "shop_name": shop_name,
        "area": area
    })
    mechanic_id = result.fetchone()[0]
    db.commit()

    # Notify all staff
    try:
        tokens = db.execute(text(
            "SELECT DISTINCT token FROM push_tokens"
            " WHERE token IS NOT NULL"
        ))
        token_list = [row[0] for row in tokens]
        if token_list:
            messages = [{
                "to": token,
                "title": "🔧 New Mechanic Request!",
                "body": f"{name} from {area or 'Nandyal'}"
                        f" wants mechanic access",
                "sound": "default"
            } for token in token_list]
            http_requests.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
    except:
        pass

    return {
        "id": mechanic_id,
        "status": "pending",
        "message": "Registration submitted!"
    }

@app.get("/mechanics/check/{phone}")
def check_mechanic_status(
    phone: str,
    db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT id, name, phone, shop_name,
               area, status, created_at
        FROM mechanic_profiles WHERE phone = :phone
    """), {"phone": phone}).fetchone()

    if not result:
        return {"status": "not_found"}

    return {
        "id": result[0],
        "name": result[1],
        "phone": result[2],
        "shop_name": result[3],
        "area": result[4],
        "status": result[5],
        "created_at": str(result[6])
    }

@app.get("/mechanics")
def get_all_mechanics(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name, phone, shop_name,
               area, status, created_at
        FROM mechanic_profiles
        ORDER BY
          CASE status
            WHEN 'pending' THEN 0
            WHEN 'approved' THEN 1
            ELSE 2 END,
          created_at DESC
    """))
    mechanics = []
    for row in result:
        mechanics.append({
            "id": row[0],
            "name": row[1],
            "phone": row[2],
            "shop_name": row[3],
            "area": row[4],
            "status": row[5],
            "created_at": str(row[6])
        })
    return {
        "mechanics": mechanics,
        "pending": sum(
            1 for m in mechanics if m["status"] == "pending"
        ),
        "approved": sum(
            1 for m in mechanics if m["status"] == "approved"
        ),
        "rejected": sum(
            1 for m in mechanics if m["status"] == "rejected"
        ),
    }

@app.put("/mechanics/{mechanic_id}/approve")
def approve_mechanic(
    mechanic_id: int,
    data: dict,
    db: Session = Depends(get_db)
):
    status = data.get("status", "approved")
    approved_by = data.get("approved_by")
    notes = data.get("notes", "")

    db.execute(text("""
        UPDATE mechanic_profiles
        SET status = :status,
            approved_by = :approved_by,
            approved_at = datetime('now'),
            notes = :notes
        WHERE id = :id
    """), {
        "status": status,
        "approved_by": approved_by,
        "notes": notes,
        "id": mechanic_id
    })
    db.commit()

    # Notify mechanic
    try:
        mechanic = db.execute(text("""
            SELECT phone FROM mechanic_profiles WHERE id = :id
        """), {"id": mechanic_id}).fetchone()

        if mechanic:
            token_row = db.execute(text("""
                SELECT token FROM customer_tokens
                WHERE phone = :phone
            """), {"phone": mechanic[0]}).fetchone()

            if token_row:
                msg = (
                    "🎉 Approved! You get 5% mechanic discount!"
                    if status == "approved"
                    else "❌ Your mechanic request was not approved."
                )
                http_requests.post(
                    "https://exp.host/--/api/v2/push/send",
                    json={
                        "to": token_row[0],
                        "title": "New Rahul Auto Spares",
                        "body": msg,
                        "sound": "default"
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
    except:
        pass

    return {"message": f"Mechanic {status}!"}
@app.put("/staff/{staff_id}/pin")
def update_staff_pin(
    staff_id: int,
    data: dict,
    db: Session = Depends(get_db)
):
    new_pin = data.get("pin")
    if not new_pin or len(new_pin) != 4:
        return {"error": "PIN must be 4 digits"}

    db.execute(text("""
        UPDATE staff_profiles
        SET pin = :pin WHERE id = :id
    """), {"pin": new_pin, "id": staff_id})
    db.commit()
    return {"message": "PIN updated successfully!"}
# ════════════════════════════════════
# LOYALTY POINTS
# ════════════════════════════════════

@app.get("/loyalty/{phone}")
def get_loyalty_points(
  phone: str, db: Session = Depends(get_db)
):
    result = db.execute(text("""
        SELECT points, total_earned, total_redeemed
        FROM customer_loyalty_points
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()
    if not result:
        return {
            "points": 0,
            "total_earned": 0,
            "total_redeemed": 0
        }
    return {
        "points": result[0],
        "total_earned": result[1],
        "total_redeemed": result[2]
    }

@app.post("/loyalty/{phone}/add")
def add_loyalty_points(
  phone: str,
  data: dict,
  db: Session = Depends(get_db)
):
    points = data.get("points", 0)
    if points <= 0:
        return {"error": "Invalid points"}
    db.execute(text("""
        INSERT INTO customer_loyalty_points
        (phone, points, total_earned, updated_at)
        VALUES (:phone, :points, :points, datetime('now'))
        ON CONFLICT (phone) DO UPDATE
        SET points = customer_loyalty_points.points + :points,
            total_earned =
              customer_loyalty_points.total_earned + :points,
            updated_at = datetime('now')
    """), {"phone": phone, "points": points})
    db.commit()
    return {"message": "Points added!", "added": points}

@app.post("/loyalty/{phone}/redeem")
def redeem_loyalty_points(
  phone: str,
  data: dict,
  db: Session = Depends(get_db)
):
    points = data.get("points", 0)
    result = db.execute(text("""
        SELECT points FROM customer_loyalty_points
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()
    if not result or result[0] < points:
        return {"error": "Not enough points"}
    db.execute(text("""
        UPDATE customer_loyalty_points
        SET points = points - :points,
            total_redeemed = total_redeemed + :points,
            updated_at = datetime('now')
        WHERE phone = :phone
    """), {"phone": phone, "points": points})
    db.commit()
    return {"message": "Points redeemed!", "redeemed": points}
# ════════════════════════════════════
# CUSTOMER ANALYTICS
# ════════════════════════════════════

@app.get("/customers/analytics")
def get_customer_analytics(
    db: Session = Depends(get_db)
):
    # Top customers by spending
    top_spenders = db.execute(text("""
        SELECT customer_name, customer_phone,
               COUNT(*) as order_count,
               SUM(total_amount) as total_spent
        FROM orders
        WHERE status = 'collected'
        GROUP BY customer_name, customer_phone
        ORDER BY total_spent DESC
        LIMIT 10
    """)).fetchall()

    # Top customers by orders
    top_orderers = db.execute(text("""
        SELECT customer_name, customer_phone,
               COUNT(*) as order_count,
               SUM(total_amount) as total_spent
        FROM orders
        GROUP BY customer_name, customer_phone
        ORDER BY order_count DESC
        LIMIT 10
    """)).fetchall()

    # This month stats
    monthly = db.execute(text("""
        SELECT
            COUNT(DISTINCT customer_phone) as unique_customers,
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_revenue
        FROM orders
        WHERE strftime('%Y-%m', created_at) =
              strftime('%Y-%m', 'now')
    """)).fetchone()

    # New customers this month
    new_customers = db.execute(text("""
        SELECT COUNT(DISTINCT customer_phone)
        FROM orders
        WHERE strftime('%Y-%m', created_at) =
              strftime('%Y-%m', 'now')
        AND customer_phone NOT IN (
            SELECT DISTINCT customer_phone FROM orders
            WHERE created_at < strftime('%Y-%m', 'now')
        )
    """)).fetchone()

    return {
        "top_spenders": [
            {
                "name": r[0], "phone": r[1],
                "order_count": r[2],
                "total_spent": float(r[3] or 0)
            } for r in top_spenders
        ],
        "top_orderers": [
            {
                "name": r[0], "phone": r[1],
                "order_count": r[2],
                "total_spent": float(r[3] or 0)
            } for r in top_orderers
        ],
        "monthly": {
            "unique_customers": monthly[0] or 0,
            "total_orders": monthly[1] or 0,
            "total_revenue": float(monthly[2] or 0)
        },
        "new_customers": new_customers[0] or 0
    }

# ════════════════════════════════════
# ALL CUSTOMERS (for broadcast)
# ════════════════════════════════════

@app.get("/customers/all")
def get_all_customers(
    db: Session = Depends(get_db)
):
    customers = db.execute(text("""
        SELECT DISTINCT customer_name,
               customer_phone
        FROM orders
        WHERE customer_phone IS NOT NULL
        ORDER BY customer_name
    """)).fetchall()
    return {
        "customers": [
            {"name": r[0], "phone": r[1]}
            for r in customers
        ],
        "count": len(customers)
    }

# ════════════════════════════════════
# PRODUCT BARCODE SEARCH
# ════════════════════════════════════

@app.get("/products/barcode/{code}")
def search_by_barcode(
    code: str,
    db: Session = Depends(get_db)
):
    product = db.execute(text("""
        SELECT * FROM products
        WHERE sku = :code
        OR barcode = :code
        LIMIT 1
    """), {"code": code}).fetchone()

    if not product:
        # Try partial match
        product = db.execute(text("""
            SELECT * FROM products
            WHERE sku LIKE :code
            OR name_en LIKE :code
            LIMIT 1
        """), {"code": f"%{code}%"}).fetchone()

    if not product:
        return {"found": False, "product": None}

    cols = ["id","name_en","name_te","sku",
            "mrp","selling_price","stock_qty","barcode"]
    return {
        "found": True,
        "product": dict(zip(cols, product))
    }

# ════════════════════════════════════
# PUSH NOTIFICATIONS
# ════════════════════════════════════

@app.post("/notify/order-ready/{order_id}")
def notify_order_ready(
    order_id: int,
    db: Session = Depends(get_db)
):
    order = db.execute(text("""
        SELECT customer_phone, custom_id,
               total_amount
        FROM orders WHERE id = :id
    """), {"id": order_id}).fetchone()

    if not order:
        return {"sent": False}

    token = db.execute(text("""
        SELECT token FROM customer_tokens
        WHERE phone = :phone
        LIMIT 1
    """), {"phone": order[0]}).fetchone()

    if not token:
        return {"sent": False, "reason": "No token"}

    import httpx
    response = httpx.post(
        "https://exp.host/--/api/v2/push/send",
        json={
            "to": token[0],
            "title": "🎉 Order Ready for Pickup!",
            "body": f"Order {order[1]} · ₹{order[2]} is ready! Come collect it now.",
            "data": {"order_id": order_id},
            "sound": "default",
            "priority": "high"
        }
    )
    return {"sent": True}

@app.post("/notify/broadcast")
def broadcast_notification(
    data: dict,
    db: Session = Depends(get_db)
):
    title = data.get("title", "New Update!")
    body = data.get("body", "")

    tokens = db.execute(text("""
        SELECT token FROM customer_tokens
        WHERE token IS NOT NULL
    """)).fetchall()

    if not tokens:
        return {"sent": 0}

    import httpx
    messages = [
        {
            "to": t[0],
            "title": title,
            "body": body,
            "sound": "default"
        }
        for t in tokens
    ]

    # Send in batches of 100
    sent = 0
    for i in range(0, len(messages), 100):
        batch = messages[i:i+100]
        httpx.post(
            "https://exp.host/--/api/v2/push/send",
            json=batch
        )
        sent += len(batch)

    return {"sent": sent, "total_tokens": len(tokens)}
# ════════════════════════════════════
# ADD NEW PRODUCT
# ════════════════════════════════════

@app.post("/products")
def add_product(
    data: dict,
    db: Session = Depends(get_db)
):
    name_en = data.get("name_en", "").strip()
    name_te = data.get("name_te", "").strip()
    sku = data.get("sku", "").strip().upper()
    mrp = float(data.get("mrp", 0))
    selling_price = float(data.get("selling_price", 0))
    stock_qty = int(data.get("stock_qty", 0))

    if not name_en or not sku or mrp <= 0:
        return {"error": "Name, SKU and MRP required"}

    existing = db.execute(text("""
        SELECT id FROM products WHERE sku = :sku
    """), {"sku": sku}).fetchone()

    if existing:
        return {"error": f"SKU {sku} already exists!"}

    db.execute(text("""
        INSERT INTO products
        (name_en, name_te, sku, mrp, selling_price, stock_qty)
        VALUES (:name_en, :name_te, :sku, :mrp, :sp, :sq)
    """), {
        "name_en": name_en, "name_te": name_te,
        "sku": sku, "mrp": mrp,
        "sp": selling_price, "sq": stock_qty
    })
    db.commit()
    return {"message": "Product added!", "sku": sku}

# ════════════════════════════════════
# PRODUCTS BY BRAND
# ════════════════════════════════════

@app.get("/products/brand/{sku_prefix}")
def get_products_by_brand(
    sku_prefix: str,
    db: Session = Depends(get_db)
):
    products = db.execute(text("""
        SELECT * FROM products
        WHERE sku LIKE :prefix
        ORDER BY name_en
    """), {"prefix": f"{sku_prefix}%"}).fetchall()

    cols = ["id","name_en","name_te","sku",
            "mrp","selling_price","stock_qty"]
    return {
        "products": [dict(zip(cols, p)) for p in products]
    }

# ════════════════════════════════════
# DAILY SALES SUMMARY
# ════════════════════════════════════

@app.get("/reports/daily-summary")
def get_daily_summary(
    db: Session = Depends(get_db)
):
    today_orders = db.execute(text("""
        SELECT customer_name, customer_phone,
               total_amount, status, payment_type,
               custom_id, created_at
        FROM orders
        WHERE date(created_at) = date('now')
        ORDER BY created_at DESC
    """)).fetchall()

    total_revenue = sum(
        float(o[2] or 0) for o in today_orders
        if o[3] == 'collected'
    )
    total_orders = len(today_orders)
    pending = sum(
        1 for o in today_orders
        if o[3] not in ['collected']
    )
    cash = sum(
        float(o[2] or 0) for o in today_orders
        if o[4] == 'cash' and o[3] == 'collected'
    )
    upi = sum(
        float(o[2] or 0) for o in today_orders
        if o[4] == 'upi' and o[3] == 'collected'
    )

    bestsellers = db.execute(text("""
        SELECT p.name_en, SUM(oi.quantity) as qty
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        JOIN orders o ON o.id = oi.order_id
        WHERE date(o.created_at) = date('now')
        GROUP BY p.name_en
        ORDER BY qty DESC
        LIMIT 5
    """)).fetchall()

    return {
        "date": str(date.today()),
        "total_orders": total_orders,
        "total_revenue": float(total_revenue),
        "pending_orders": pending,
        "cash": float(cash),
        "upi": float(upi),
        "bestsellers": [
            {"name": b[0], "qty": b[1]}
            for b in bestsellers
        ],
        "orders": [
            {
                "id": o[5],
                "customer": o[0],
                "amount": float(o[2] or 0),
                "status": o[3]
            }
            for o in today_orders[:10]
        ]
    }