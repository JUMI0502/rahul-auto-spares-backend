from fastapi import FastAPI, Depends, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, date
import os
from dotenv import load_dotenv
import requests as http_requests
from database import engine, SessionLocal, get_db

load_dotenv()

import sentry_sdk

sentry_sdk.init(
    dsn="https://33f5816e1480278c558077d02cc67e8a@o4511731723534336.ingest.us.sentry.io/4511816756953088",
    send_default_pii=True,
    traces_sample_rate=0.5,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════

API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
if not API_SECRET_KEY:
    raise RuntimeError("API_SECRET_KEY environment variable must be set - refusing to start without it")

import time
from collections import defaultdict

_rate_limit_buckets = defaultdict(list)
RATE_LIMIT_MAX_REQUESTS = 100
RATE_LIMIT_WINDOW_SECONDS = 60

# Per-account PIN lockout (separate from IP rate limiting above) -
# stops brute-forcing one account's PIN even if under the general IP limit
_pin_failed_attempts = defaultdict(list)
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_SECONDS = 900  # 15 minutes

def check_pin_lockout(key: str):
    now = time.time()
    attempts = _pin_failed_attempts[key]
    while attempts and attempts[0] < now - PIN_LOCKOUT_SECONDS:
        attempts.pop(0)
    if len(attempts) >= PIN_MAX_FAILURES:
        wait_seconds = int(PIN_LOCKOUT_SECONDS - (now - attempts[0]))
        return max(wait_seconds, 1)
    return None

def record_pin_failure(key: str):
    _pin_failed_attempts[key].append(time.time())

def clear_pin_failures(key: str):
    _pin_failed_attempts[key] = []

# Customer session tokens - issued after PIN verification, required for
# any endpoint that returns/modifies data tied to a specific phone number.
# Without this, anyone with the app's API key could access ANY customer's
# order history, points, or delete their account just by knowing their phone.
import secrets
_customer_sessions = {}  # token -> {"phone": str, "expires_at": float}
SESSION_DURATION_SECONDS = 60 * 60 * 24 * 7  # 7 days

def create_customer_session(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    _customer_sessions[token] = {"phone": phone, "expires_at": time.time() + SESSION_DURATION_SECONDS}
    return token

def require_customer_session(phone: str, x_session_token: str = Header(None)):
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Session token required")
    session = _customer_sessions.get(x_session_token)
    if not session or session["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="Session expired - please log in again")
    if session["phone"] != phone:
        raise HTTPException(status_code=403, detail="Session does not match requested account")
    return True

# PIN hashing - staff and customer PINs were previously stored as plain
# text, meaning a database breach would expose every PIN immediately.
# hash_pin() is used everywhere a PIN is written. check_pin() handles
# verification and also transparently upgrades any legacy plaintext PIN
# to a proper hash the moment it's next used successfully - no separate
# migration script needed, existing accounts self-heal on next login.
import bcrypt

def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

def check_pin(pin: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        try:
            return bcrypt.checkpw(pin.encode(), stored.encode())
        except Exception:
            return False
    # Legacy plaintext PIN - direct comparison for this one last check
    return pin == stored

# One-time startup fix: staff_profiles.pin was originally VARCHAR(10),
# which fits a 4-digit plaintext PIN but is far too narrow for a bcrypt
# hash (~60 chars). Without this, every hash-migration write silently
# fails with a truncation error, breaking staff login entirely.
try:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE staff_profiles ALTER COLUMN pin TYPE VARCHAR(100);"))
        _conn.commit()
except Exception as _e:
    sentry_sdk.capture_exception(_e)

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path == "/" or request.url.path == "/privacy-policy" or request.method == "HEAD":
        return await call_next(request)

    provided_key = request.headers.get("x-api-key")
    if provided_key != API_SECRET_KEY:
        return JSONResponse(status_code=401, content={"error": "Unauthorized - missing or invalid API key"})

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _rate_limit_buckets[client_ip]
    while bucket and bucket[0] < now - RATE_LIMIT_WINDOW_SECONDS:
        bucket.pop(0)
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(status_code=429, content={"error": "Too many requests - please slow down"})
    bucket.append(now)

    return await call_next(request)

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
               stock_qty, category_id, is_oem
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
            "category_id": row[8],
            "is_oem": bool(row[9]) if row[9] is not None else False
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

    old_row = db.execute(text(
        "SELECT stock_qty FROM products WHERE id = :id"
    ), {"id": product_id}).fetchone()
    old_qty = old_row[0] if old_row else 0

    db.execute(text("""
        UPDATE products
        SET stock_qty = :qty WHERE id = :id
    """), {"qty": new_qty, "id": product_id})
    db.commit()

    # Log the movement in its own transaction - if this fails,
    # it must NEVER be able to roll back the stock update above.
    try:
        db.execute(text("""
            INSERT INTO stock_movements
            (product_id, qty_change, reason)
            VALUES (:pid, :qc, 'manual_update')
        """), {
            "pid": product_id,
            "qc": new_qty - old_qty
        })
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

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
    db: Session = Depends(get_db),
    _auth: bool = Depends(require_customer_session)
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


@app.get("/staff/customers/{phone}/orders")
def staff_get_customer_orders(phone: str, db: Session = Depends(get_db)):
    """Staff-facing version of order lookup - used by the store app so
    staff can help any customer, without requiring that customer's own
    session token (which only makes sense for their self-service app)."""
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


@app.post("/staff/{staff_id}/register-push-token")
def register_push_token(staff_id: int, data: dict, db: Session = Depends(get_db)):
    token = data.get("push_token")
    if not token:
        return {"error": "push_token is required"}
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_push_tokens (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER,
                push_token TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(text("""
            INSERT INTO staff_push_tokens (staff_id, push_token)
            VALUES (:sid, :token)
            ON CONFLICT (push_token) DO UPDATE SET staff_id = :sid
        """), {"sid": staff_id, "token": token})
        db.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def send_new_order_push(custom_id: str, total_amount: float, db: Session):
    try:
        tokens = db.execute(text(
            "SELECT DISTINCT push_token FROM staff_push_tokens"
        )).fetchall()
        if not tokens:
            return
        messages = [{
            "to": row[0],
            "sound": "default",
            "priority": "high",
            "title": "New Order!",
            "body": f"Order {custom_id} - Rs.{total_amount:.0f}",
            "data": {"custom_id": custom_id, "type": "new_order"},
            "channelId": "new-orders",
        } for row in tokens]
        resp = http_requests.post(
            "https://exp.host/--/api/v2/push/send",
            json=messages,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
    except Exception as e:
        pass


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
    referred_by_phone = data.get("referred_by_phone", "").strip()

    # Check if this is the customer's first-ever order (for referral bonus)
    is_first_order = False
    if referred_by_phone and referred_by_phone != customer_phone:
        prior_count = db.execute(text(
            "SELECT COUNT(*) FROM orders WHERE customer_phone = :phone"
        ), {"phone": customer_phone}).fetchone()[0]
        is_first_order = (prior_count == 0)

    # Duplicate protection: reject if an identical order was just placed
    # by the same customer in the last 15 seconds (catches double-taps
    # and network retries without needing a client-side idempotency key)
    recent_dupe = db.execute(text("""
        SELECT id, custom_id FROM orders
        WHERE customer_phone = :phone
          AND total_amount = :total
          AND created_at > NOW() - INTERVAL '15 seconds'
        ORDER BY created_at DESC LIMIT 1
    """), {"phone": customer_phone, "total": total_amount}).fetchone()

    if recent_dupe:
        return {
            "message": "Order already placed!",
            "order_id": recent_dupe[0],
            "custom_id": recent_dupe[1],
            "duplicate_prevented": True
        }

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

    # Validate stock availability BEFORE making any changes
    insufficient = []
    for item in items:
        pid = item.get("id")
        qty = item.get("qty", 1)
        stock_row = db.execute(text(
            "SELECT stock_qty, name_en FROM products WHERE id = :pid"
        ), {"pid": pid}).fetchone()
        if not stock_row or stock_row[0] < qty:
            insufficient.append({
                "product_id": pid,
                "name": stock_row[1] if stock_row else "Unknown item",
                "available": stock_row[0] if stock_row else 0,
                "requested": qty
            })

    if insufficient:
        db.rollback()
        return {
            "error": "Insufficient stock",
            "insufficient_items": insufficient
        }

    for item in items:
        price = item.get("mechanic_price") or \
                item.get("selling_price", 0)
        pid = item.get("id")
        qty = item.get("qty", 1)

        db.execute(text("""
            INSERT INTO order_items
            (order_id, product_id, qty, price)
            VALUES (:oid, :pid, :qty, :price)
        """), {
            "oid": order_id,
            "pid": pid,
            "qty": qty,
            "price": price
        })

        result = db.execute(text("""
            UPDATE products
            SET stock_qty = stock_qty - :qty
            WHERE id = :pid AND stock_qty >= :qty
        """), {"qty": qty, "pid": pid})

        if result.rowcount == 0:
            db.rollback()
            return {"error": "Stock changed during order - please try again"}

    db.commit()
    send_new_order_push(custom_id, total_amount, db)

    referral_bonus_awarded = False
    if is_first_order and referred_by_phone:
        try:
            REFERRER_BONUS = 50
            NEW_CUSTOMER_BONUS = 20
            db.execute(text("""
                INSERT INTO customer_loyalty_points
                (phone, points, total_earned, updated_at)
                VALUES (:phone, :points, :points, NOW())
                ON CONFLICT (phone) DO UPDATE
                SET points = customer_loyalty_points.points + :points,
                    total_earned = customer_loyalty_points.total_earned + :points,
                    updated_at = NOW()
            """), {"phone": referred_by_phone, "points": REFERRER_BONUS})
            db.execute(text("""
                INSERT INTO customer_loyalty_points
                (phone, points, total_earned, updated_at)
                VALUES (:phone, :points, :points, NOW())
                ON CONFLICT (phone) DO UPDATE
                SET points = customer_loyalty_points.points + :points,
                    total_earned = customer_loyalty_points.total_earned + :points,
                    updated_at = NOW()
            """), {"phone": customer_phone, "points": NEW_CUSTOMER_BONUS})
            db.commit()
            referral_bonus_awarded = True
        except Exception as e:
            sentry_sdk.capture_exception(e)
            db.rollback()

    return {
        "message": "Order created!",
        "order_id": order_id,
        "custom_id": custom_id,
        "referral_bonus_awarded": referral_bonus_awarded
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
    # SECURITY: never select/return the pin column here - this endpoint
    # populates the staff-selection list and must not leak credentials.
    # PIN verification happens exclusively via /staff/verify-pin.
    result = db.execute(text("""
        SELECT id, name, role, phone,
               is_clocked_in, total_hours_today
        FROM staff_profiles
        WHERE is_active = true
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
def get_staff_profile(staff_id: int, db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT id, name, role, phone,
               photo_url, is_clocked_in,
               clock_in_time, total_hours_today
        FROM staff_profiles WHERE id = :id AND is_active = true
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
def update_staff_profile(staff_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE staff_profiles
        SET name = COALESCE(:name, name),
            phone = COALESCE(:phone, phone),
            role = COALESCE(:role, role),
            photo_url = COALESCE(:photo_url, photo_url)
        WHERE id = :id
    """), {
        "name": data.get("name"),
        "phone": data.get("phone"),
        "role": data.get("role"),
        "photo_url": data.get("photo_url"),
        "id": staff_id
    })
    db.commit()
    return {"message": "Profile updated!"}

@app.post("/staff/{staff_id}/reset-hours")
def reset_staff_hours(staff_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE staff_profiles SET total_hours_today = 0 WHERE id = :id
    """), {"id": staff_id})
    db.commit()
    return {"message": "Hours reset"}


@app.post("/staff")
def add_staff(data: dict, db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            INSERT INTO staff_profiles (name, phone, role, pin, is_active)
            VALUES (:name, :phone, :role, :pin, true)
            RETURNING id
        """), {
            "name": data.get("name"),
            "phone": data.get("phone", ""),
            "role": data.get("role", "staff"),
            "pin": hash_pin(data.get("pin", "0000")),
        })
        db.commit()
        row = result.fetchone()
        return {"id": row[0], "success": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/staff/{staff_id}/reset-pin")
def reset_staff_pin(staff_id: int, data: dict, db: Session = Depends(get_db)):
    new_pin = data.get("pin")
    if not new_pin or len(str(new_pin)) != 4:
        return {"error": "A valid 4-digit PIN is required"}
    try:
        db.execute(text(
            "UPDATE staff_profiles SET pin = :pin WHERE id = :id"
        ), {"pin": hash_pin(str(new_pin)), "id": staff_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            UPDATE staff_profiles SET is_active = false WHERE id = :id
        """), {"id": staff_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/staff/verify-pin")
def verify_staff_pin(data: dict, db: Session = Depends(get_db)):
    staff_id = data.get("staff_id")
    lockout_key = f"staff:{staff_id}"
    wait = check_pin_lockout(lockout_key)
    if wait:
        return {"staff": None, "locked": True, "retry_after_seconds": wait}
    try:
        entered_pin = data.get("pin", "")
        result = db.execute(text("""
            SELECT id, name, role, phone, pin
            FROM staff_profiles
            WHERE id = :staff_id AND is_active = true
        """), {"staff_id": staff_id}).fetchone()
        if result and check_pin(entered_pin, result[4]):
            clear_pin_failures(lockout_key)
            if not result[4].startswith("$2b$") and not result[4].startswith("$2a$"):
                db.execute(text("UPDATE staff_profiles SET pin = :pin WHERE id = :id"),
                           {"pin": hash_pin(entered_pin), "id": staff_id})
                db.commit()
            staff_dict = dict(result._mapping)
            staff_dict.pop("pin", None)
            return {"staff": staff_dict}
        record_pin_failure(lockout_key)
        return {"staff": None}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"staff": None}

@app.post("/staff/{staff_id}/clockin")
def clock_in(
    staff_id: int,
    db: Session = Depends(get_db)
):
    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = TRUE,
            clock_in_time = NOW()
        WHERE id = :id
    """), {"id": staff_id})
    db.execute(text("""
        INSERT INTO attendance_log
        (staff_id, clock_in, date)
        VALUES (:sid, NOW(), date('now'))
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
        # Sanity cap: a shift can't realistically exceed 24 hours.
        # A larger value means a stale clock-in from a crash/restart -
        # cap it so it doesn't overflow the database column.
        if hours > 24 or hours < 0:
            hours = 0

    db.execute(text("""
        UPDATE staff_profiles
        SET is_clocked_in = FALSE,
            clock_out_time = NOW(),
            total_hours_today = :hours
        WHERE id = :id
    """), {"hours": hours, "id": staff_id})

    db.execute(text("""
        UPDATE attendance_log
        SET clock_out = NOW(),
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
        date_filter = "created_at >= NOW() - INTERVAL '7 days'"
    else:
        date_filter = "created_at >= NOW() - INTERVAL '30 days'"

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
        WHERE created_at >= NOW() - INTERVAL '7 days'
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
        VALUES (:sid, :token, NOW())
        ON CONFLICT (token) DO UPDATE
        SET staff_id = :sid, updated_at = NOW()
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
        VALUES (:phone, :token, NOW())
        ON CONFLICT (phone) DO UPDATE
        SET token = :token, updated_at = NOW()
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
    except Exception as e:
        sentry_sdk.capture_exception(e)
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

@app.put("/mechanics/{mechanic_id}")
def update_mechanic(mechanic_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE mechanic_profiles
        SET name = COALESCE(:name, name),
            phone = COALESCE(:phone, phone),
            shop_name = COALESCE(:shop_name, shop_name),
            area = COALESCE(:area, area)
        WHERE id = :id
    """), {
        "name": data.get("name"),
        "phone": data.get("phone"),
        "shop_name": data.get("shop_name"),
        "area": data.get("area"),
        "id": mechanic_id
    })
    db.commit()
    return {"message": "Mechanic updated!"}


@app.delete("/mechanics/{mechanic_id}")
def delete_mechanic(mechanic_id: int, db: Session = Depends(get_db)):
    db.execute(text(
        "DELETE FROM mechanic_profiles WHERE id = :id"
    ), {"id": mechanic_id})
    db.commit()
    return {"message": "Mechanic deleted!"}


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
            approved_at = NOW(),
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
                    "Approved! You now have a mechanic trade account."
                    if status == "approved"
                    else "Your mechanic request was not approved."
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
    except Exception as e:
        sentry_sdk.capture_exception(e)

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
    """), {"pin": hash_pin(new_pin), "id": staff_id})
    db.commit()
    return {"message": "PIN updated successfully!"}
# ════════════════════════════════════
# LOYALTY POINTS
# ════════════════════════════════════

@app.get("/loyalty/{phone}")
def get_loyalty_points(
  phone: str, db: Session = Depends(get_db),
  _auth: bool = Depends(require_customer_session)
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
        VALUES (:phone, :points, :points, NOW())
        ON CONFLICT (phone) DO UPDATE
        SET points = customer_loyalty_points.points + :points,
            total_earned =
              customer_loyalty_points.total_earned + :points,
            updated_at = NOW()
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
            updated_at = NOW()
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
# SERVICE REMINDERS
# ════════════════════════════════════

@app.get("/customers/service-due")
def get_service_due_customers(days: int = 60, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS service_reminders_sent (
                id SERIAL PRIMARY KEY,
                customer_phone TEXT,
                sent_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    result = db.execute(text("""
        SELECT
            o.customer_phone,
            MAX(o.customer_name) as customer_name,
            MAX(o.created_at) as last_order_date,
            COUNT(o.id) as total_orders
        FROM orders o
        WHERE o.customer_phone IS NOT NULL
        GROUP BY o.customer_phone
        HAVING MAX(o.created_at) < NOW() - (:days || ' days')::interval
        ORDER BY MAX(o.created_at) ASC
    """), {"days": days}).fetchall()

    due_customers = []
    for row in result:
        phone = row[0]
        recent_reminder = db.execute(text("""
            SELECT sent_at FROM service_reminders_sent
            WHERE customer_phone = :phone
            AND sent_at > NOW() - INTERVAL '30 days'
            ORDER BY sent_at DESC LIMIT 1
        """), {"phone": phone}).fetchone()

        due_customers.append({
            "customer_phone": phone,
            "customer_name": row[1],
            "last_order_date": str(row[2]),
            "total_orders": row[3],
            "reminder_sent_recently": recent_reminder is not None
        })

    return {"due_customers": due_customers, "count": len(due_customers)}


@app.post("/customers/{phone}/service-reminder-sent")
def mark_service_reminder_sent(phone: str, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO service_reminders_sent (customer_phone)
        VALUES (:phone)
    """), {"phone": phone})
    db.commit()
    return {"message": "Recorded"}


# ════════════════════════════════════
# WARRANTY / RETURNS
# ════════════════════════════════════

@app.post("/warranty-claims")
def create_warranty_claim(data: dict, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS warranty_claims (
                id SERIAL PRIMARY KEY,
                order_id INTEGER,
                product_name TEXT,
                customer_name TEXT,
                customer_phone TEXT,
                issue_description TEXT,
                status TEXT DEFAULT 'pending',
                resolution_type TEXT,
                resolution_notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP,
                resolved_by TEXT
            )
        """))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    result = db.execute(text("""
        INSERT INTO warranty_claims
        (order_id, product_name, customer_name, customer_phone, issue_description)
        VALUES (:oid, :pname, :cname, :cphone, :issue)
        RETURNING id
    """), {
        "oid": data.get("order_id"),
        "pname": data.get("product_name", ""),
        "cname": data.get("customer_name", ""),
        "cphone": data.get("customer_phone", ""),
        "issue": data.get("issue_description", "")
    })
    claim_id = result.fetchone()[0]
    db.commit()
    return {"id": claim_id, "message": "Claim logged!"}


@app.get("/warranty-claims")
def get_warranty_claims(status: str = None, db: Session = Depends(get_db)):
    query = "SELECT id, order_id, product_name, customer_name, customer_phone, issue_description, status, resolution_type, resolution_notes, created_at, resolved_at, resolved_by FROM warranty_claims"
    params = {}
    if status:
        query += " WHERE status = :status"
        params["status"] = status
    query += " ORDER BY created_at DESC"

    result = db.execute(text(query), params).fetchall()
    claims = []
    for r in result:
        claims.append({
            "id": r[0], "order_id": r[1], "product_name": r[2],
            "customer_name": r[3], "customer_phone": r[4],
            "issue_description": r[5], "status": r[6],
            "resolution_type": r[7], "resolution_notes": r[8],
            "created_at": str(r[9]),
            "resolved_at": str(r[10]) if r[10] else None,
            "resolved_by": r[11]
        })
    return {"claims": claims}


@app.put("/warranty-claims/{claim_id}")
def update_warranty_claim(claim_id: int, data: dict, db: Session = Depends(get_db)):
    status = data.get("status", "pending")
    resolution_type = data.get("resolution_type")
    resolution_notes = data.get("resolution_notes", "")
    resolved_by = data.get("resolved_by", "")

    resolved_at_clause = "resolved_at = NOW()," if status in ("resolved", "rejected") else ""

    db.execute(text(f"""
        UPDATE warranty_claims
        SET status = :status,
            resolution_type = :rtype,
            resolution_notes = :rnotes,
            {resolved_at_clause}
            resolved_by = :rby
        WHERE id = :id
    """), {
        "status": status,
        "rtype": resolution_type,
        "rnotes": resolution_notes,
        "rby": resolved_by,
        "id": claim_id
    })
    db.commit()
    return {"message": "Updated!"}


# ════════════════════════════════════
# BUSINESS HEALTH (owner-only KPIs)
# ════════════════════════════════════

@app.get("/reports/business-health")
def get_business_health(db: Session = Depends(get_db)):
    # Staff productivity this month (private, owner-only - not a competitive leaderboard)
    staff_rows = db.execute(text("""
        SELECT collected_by, COUNT(*) as orders_completed
        FROM orders
        WHERE collected_by IS NOT NULL
          AND created_at > date_trunc('month', NOW())
        GROUP BY collected_by
        ORDER BY orders_completed DESC
    """)).fetchall()
    staff_productivity = [{"name": r[0], "orders_completed": r[1]} for r in staff_rows]

    # Warranty claim rate this month
    try:
        total_orders_month = db.execute(text("""
            SELECT COUNT(*) FROM orders WHERE created_at > date_trunc('month', NOW())
        """)).fetchone()[0]
        claims_month = db.execute(text("""
            SELECT COUNT(*) FROM warranty_claims WHERE created_at > date_trunc('month', NOW())
        """)).fetchone()[0]
    except Exception as e:
        sentry_sdk.capture_exception(e)
        total_orders_month = 0
        claims_month = 0
    claim_rate = round((claims_month / total_orders_month) * 100, 1) if total_orders_month > 0 else 0

    # Customer retention: active (ordered in last 60 days) vs lapsed
    total_customers = db.execute(text("""
        SELECT COUNT(DISTINCT customer_phone) FROM orders WHERE customer_phone IS NOT NULL
    """)).fetchone()[0]
    active_customers = db.execute(text("""
        SELECT COUNT(DISTINCT customer_phone) FROM orders
        WHERE customer_phone IS NOT NULL
          AND created_at > NOW() - INTERVAL '60 days'
    """)).fetchone()[0]
    lapsed_customers = total_customers - active_customers
    retention_rate = round((active_customers / total_customers) * 100, 1) if total_customers > 0 else 0

    return {
        "staff_productivity": staff_productivity,
        "warranty": {
            "claims_this_month": claims_month,
            "orders_this_month": total_orders_month,
            "claim_rate_percent": claim_rate
        },
        "retention": {
            "total_customers": total_customers,
            "active_customers": active_customers,
            "lapsed_customers": lapsed_customers,
            "retention_rate_percent": retention_rate
        }
    }


# ════════════════════════════════════
# ABANDONED CART RECOVERY
# ════════════════════════════════════

@app.post("/cart/save")
def save_cart(data: dict, db: Session = Depends(get_db)):
    import json as jsonlib
    phone = data.get("customer_phone", "").strip()
    name = data.get("customer_name", "")
    items = data.get("items", [])

    if not phone:
        return {"error": "Phone required"}

    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS active_carts (
                customer_phone TEXT PRIMARY KEY,
                customer_name TEXT,
                items_json TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                reminder_sent_at TIMESTAMP
            )
        """))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    if not items:
        db.execute(text("DELETE FROM active_carts WHERE customer_phone = :phone"), {"phone": phone})
        db.commit()
        return {"message": "Cart cleared"}

    db.execute(text("""
        INSERT INTO active_carts (customer_phone, customer_name, items_json, updated_at, reminder_sent_at)
        VALUES (:phone, :name, :items, NOW(), NULL)
        ON CONFLICT (customer_phone) DO UPDATE
        SET customer_name = :name, items_json = :items, updated_at = NOW(), reminder_sent_at = NULL
    """), {"phone": phone, "name": name, "items": jsonlib.dumps(items)})
    db.commit()
    return {"message": "Cart saved"}


@app.delete("/cart/{phone}")
def clear_cart(phone: str, db: Session = Depends(get_db)):
    try:
        db.execute(text("DELETE FROM active_carts WHERE customer_phone = :phone"), {"phone": phone})
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()
    return {"message": "Cleared"}


@app.get("/carts/abandoned")
def get_abandoned_carts(hours: int = 3, db: Session = Depends(get_db)):
    import json as jsonlib
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS active_carts (
                customer_phone TEXT PRIMARY KEY,
                customer_name TEXT,
                items_json TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                reminder_sent_at TIMESTAMP
            )
        """))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    result = db.execute(text("""
        SELECT customer_phone, customer_name, items_json, updated_at, reminder_sent_at
        FROM active_carts
        WHERE updated_at < NOW() - (:hours || ' hours')::interval
        ORDER BY updated_at ASC
    """), {"hours": hours}).fetchall()

    carts = []
    for r in result:
        try:
            items = jsonlib.loads(r[2]) if r[2] else []
        except Exception as e:
            sentry_sdk.capture_exception(e)
            items = []
        carts.append({
            "customer_phone": r[0],
            "customer_name": r[1],
            "items": items,
            "item_count": len(items),
            "updated_at": str(r[3]),
            "reminder_sent": r[4] is not None
        })
    return {"abandoned_carts": carts, "count": len(carts)}


@app.post("/carts/{phone}/reminder-sent")
def mark_cart_reminder_sent(phone: str, db: Session = Depends(get_db)):
    db.execute(text(
        "UPDATE active_carts SET reminder_sent_at = NOW() WHERE customer_phone = :phone"
    ), {"phone": phone})
    db.commit()
    return {"message": "Recorded"}


# ════════════════════════════════════
# INVENTORY FORECASTING
# ════════════════════════════════════

@app.get("/products/forecast")
def get_inventory_forecast(days_threshold: int = 7, db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT
            p.id, p.name_en, p.sku, p.stock_qty,
            COALESCE(SUM(oi.qty), 0) as sold_last_30_days
        FROM products p
        LEFT JOIN order_items oi ON p.id = oi.product_id
        LEFT JOIN orders o ON oi.order_id = o.id
            AND o.created_at > NOW() - INTERVAL '30 days'
        GROUP BY p.id, p.name_en, p.sku, p.stock_qty
    """)).fetchall()

    forecasts = []
    for row in result:
        product_id, name, sku, stock_qty, sold_30d = row
        avg_daily_rate = sold_30d / 30.0

        if avg_daily_rate > 0:
            days_remaining = round(stock_qty / avg_daily_rate, 1)
        else:
            days_remaining = None  # no recent sales data - can't forecast

        at_risk = days_remaining is not None and days_remaining <= days_threshold

        if at_risk or (avg_daily_rate > 0):
            forecasts.append({
                "product_id": product_id,
                "name": name,
                "sku": sku,
                "stock_qty": stock_qty,
                "sold_last_30_days": sold_30d,
                "avg_daily_rate": round(avg_daily_rate, 2),
                "days_remaining": days_remaining,
                "at_risk": at_risk
            })

    forecasts.sort(key=lambda f: (f["days_remaining"] is None, f["days_remaining"]))

    return {
        "at_risk_count": sum(1 for f in forecasts if f["at_risk"]),
        "forecasts": forecasts
    }


# ════════════════════════════════════
# CUSTOMER PIN VERIFICATION
# ════════════════════════════════════

@app.get("/customers/{phone}/has-pin")
def check_customer_has_pin(phone: str, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_profiles (
                phone TEXT PRIMARY KEY,
                name TEXT,
                pin TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        # Safety net: an early version of this table was created before
        # 'pin' existed in the CREATE TABLE statement above. Since
        # CREATE TABLE IF NOT EXISTS is a no-op on existing tables, that
        # column never got added - this ALTER TABLE self-heals it.
        db.execute(text("ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS pin TEXT;"))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    result = db.execute(text(
        "SELECT name FROM customer_profiles WHERE phone = :phone AND pin IS NOT NULL"
    ), {"phone": phone}).fetchone()

    return {"has_pin": result is not None, "name": result[0] if result else None}


@app.post("/customers/{phone}/reset-pin")
def reset_customer_pin(phone: str, db: Session = Depends(get_db)):
    """Staff-initiated PIN reset for customers who forgot their PIN and
    don't have WhatsApp (no automated recovery exists otherwise). Clears
    the PIN so the customer's next login naturally shows the 'create PIN'
    flow rather than 'enter PIN'. Called from the store app after a staff
    member has verified the customer's identity in person or by phone."""
    result = db.execute(text(
        "UPDATE customer_profiles SET pin = NULL WHERE phone = :phone RETURNING phone"
    ), {"phone": phone}).fetchone()
    db.commit()
    if not result:
        return {"error": "No account found for this phone number"}
    return {"success": True, "message": "PIN reset - customer can create a new one on next login"}


@app.post("/customers/set-pin")
def set_customer_pin(data: dict, db: Session = Depends(get_db)):
    phone = data.get("phone", "").strip()
    name = data.get("name", "").strip()
    pin = data.get("pin", "").strip()

    if not phone or not name or len(pin) != 4 or not pin.isdigit():
        return {"error": "Valid phone, name, and 4-digit PIN required"}

    # Self-healing safety net: fixes the case where this table was created
    # before 'pin' existed in its definition (previous incident, see Sentry).
    # Applied directly here since this endpoint is the one that actually
    # needs the column, rather than relying on a different endpoint's setup.
    try:
        db.execute(text("ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS pin TEXT;"))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    existing = db.execute(text(
        "SELECT phone FROM customer_profiles WHERE phone = :phone"
    ), {"phone": phone}).fetchone()

    if existing:
        return {"error": "PIN already set for this phone. Please log in instead."}

    db.execute(text("""
        INSERT INTO customer_profiles (phone, name, pin)
        VALUES (:phone, :name, :pin)
    """), {"phone": phone, "name": name, "pin": hash_pin(pin)})
    db.commit()
    return {"message": "PIN created!", "name": name}


@app.post("/customers/verify-pin")
def verify_customer_pin(data: dict, db: Session = Depends(get_db)):
    phone = data.get("phone", "").strip()
    pin = data.get("pin", "").strip()
    lockout_key = f"customer:{phone}"

    wait = check_pin_lockout(lockout_key)
    if wait:
        return {"verified": False, "locked": True, "retry_after_seconds": wait}

    result = db.execute(text("""
        SELECT phone, name, pin FROM customer_profiles
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()

    if result and check_pin(pin, result[2]):
        clear_pin_failures(lockout_key)
        if not result[2].startswith("$2b$") and not result[2].startswith("$2a$"):
            db.execute(text("UPDATE customer_profiles SET pin = :pin WHERE phone = :phone"),
                       {"pin": hash_pin(pin), "phone": phone})
            db.commit()
        token = create_customer_session(phone)
        return {"verified": True, "name": result[1], "session_token": token}
    record_pin_failure(lockout_key)
    return {"verified": False}


# ════════════════════════════════════
# PRIVACY POLICY + ACCOUNT DELETION
# ════════════════════════════════════

from fastapi.responses import HTMLResponse

PRIVACY_POLICY_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy - New Rahul Auto Spares</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #222; }
  h1 { font-size: 24px; } h2 { font-size: 18px; margin-top: 28px; }
  .updated { color: #666; font-size: 13px; margin-bottom: 30px; }
</style>
</head>
<body>
<h1>Privacy Policy - New Rahul Auto Spares</h1>
<p class="updated">Last updated: July 2026</p>

<p>New Rahul Auto Spares ("we", "our", "the app") operates the New Rahul Auto Spares
customer and store mobile applications. This page explains what information we collect,
how we use it, and how you can control it.</p>

<h2>Information We Collect</h2>
<p>When you use the app, we collect: your name and phone number (to create your
account), your order history and items purchased, your saved vehicle information
(bike brand/model, if provided), your loyalty points balance, and cart contents
(to help our staff assist you if you don't finish checking out).</p>

<h2>How We Protect Your Information</h2>
<p>Your account is protected by a 4-digit PIN that you set when you first sign up.
Anyone accessing your account must know both your phone number and your PIN.</p>

<h2>How We Use Your Information</h2>
<p>We use your information to process your orders, track loyalty rewards, notify
you about order status, and (with your permission via WhatsApp) send you service
reminders or respond to support requests. We do not sell your information to
third parties.</p>

<h2>Third-Party Services</h2>
<p>When you or our staff choose to contact each other via WhatsApp, that
conversation is subject to WhatsApp's own privacy policy. We use Google Firebase
for push notifications and Sentry for crash reporting, which may process
technical device information (not your personal profile data) to help us fix bugs.</p>

<h2>Data Retention</h2>
<p>We retain your order history and account information as long as your account
is active, to support warranty claims, order lookups, and loyalty tracking.</p>

<h2>Deleting Your Account</h2>
<p>You can delete your account and all associated data at any time from the
app: go to Profile → Delete My Account. This permanently removes your name,
phone number, PIN, and loyalty points from our systems. Your past order
records may be retained in anonymized form for our internal business records
(required for accounting purposes) but will no longer be linked to your name
or phone number.</p>
<p>You can also request deletion by contacting us directly at 08514-244944 or
via WhatsApp at +91 6300281504.</p>

<h2>Children's Privacy</h2>
<p>This app is not directed at children under 13, and we do not knowingly
collect information from children.</p>

<h2>Contact Us</h2>
<p>If you have questions about this privacy policy or your data, contact us at:</p>
<p>New Rahul Auto Spares<br>
Telugu Peta, Nandyal, Andhra Pradesh 518501<br>
Phone: 08514-244944</p>
</body>
</html>
"""

@app.get("/privacy-policy", response_class=HTMLResponse)
def privacy_policy():
    return PRIVACY_POLICY_HTML


@app.delete("/customers/{phone}/account")
def delete_customer_account(phone: str, db: Session = Depends(get_db), _auth: bool = Depends(require_customer_session)):
    try:
        db.execute(text("DELETE FROM customer_profiles WHERE phone = :phone"), {"phone": phone})
        db.execute(text("DELETE FROM customer_loyalty_points WHERE phone = :phone"), {"phone": phone})
        db.execute(text("DELETE FROM active_carts WHERE customer_phone = :phone"), {"phone": phone})
        db.execute(text("DELETE FROM customer_tokens WHERE phone = :phone"), {"phone": phone})
        # Anonymize past orders rather than deleting (needed for business/accounting records)
        db.execute(text("""
            UPDATE orders SET customer_name = 'Deleted User', customer_phone = NULL
            WHERE customer_phone = :phone
        """), {"phone": phone})
        db.commit()
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    return {"message": "Account deleted"}


# ════════════════════════════════════
# PRODUCT BARCODE SEARCH
# ════════════════════════════════════

@app.get("/products/barcode/{code}")
def search_by_barcode(
    code: str,
    db: Session = Depends(get_db)
):
    product = db.execute(text("""
        SELECT id, name_en, name_te, name_hi, sku, mrp, selling_price, stock_qty
        FROM products
        WHERE sku = :code
        OR barcode = :code
        LIMIT 1
    """), {"code": code}).fetchone()

    if not product:
        # Try partial match
        product = db.execute(text("""
            SELECT id, name_en, name_te, name_hi, sku, mrp, selling_price, stock_qty
            FROM products
            WHERE sku LIKE :code
            OR name_en LIKE :code
            LIMIT 1
        """), {"code": f"%{code}%"}).fetchone()

    if not product:
        return {"found": False, "product": None}

    return {
        "found": True,
        "product": dict(product._mapping)
    }

# ════════════════════════════════════
# PUSH NOTIFICATIONS
# ════════════════════════════════════

@app.post("/notify/broadcast")
def broadcast_notification(
    data: dict,
    db: Session = Depends(get_db)
):
    title = data.get("title", "New Update!")
    body = data.get("body", "")

    tokens = db.execute(text("""
        SELECT DISTINCT token FROM customer_tokens
        WHERE token IS NOT NULL
    """)).fetchall()

    if not tokens:
        return {"sent": 0}

    messages = [
        {
            "to": t[0],
            "title": title,
            "body": body,
            "sound": "default"
        }
        for t in tokens
    ]

    sent = 0
    for i in range(0, len(messages), 100):
        batch = messages[i:i+100]
        try:
            http_requests.post(
                "https://exp.host/--/api/v2/push/send",
                json=batch,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            sent += len(batch)
        except Exception as e:
            sentry_sdk.capture_exception(e)
            pass

    return {"sent": sent}

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
    is_oem = bool(data.get("is_oem", False))

    if not name_en or not sku or mrp <= 0:
        return {"error": "Name, SKU and MRP required"}

    existing = db.execute(text("""
        SELECT id FROM products WHERE sku = :sku
    """), {"sku": sku}).fetchone()

    if existing:
        return {"error": f"SKU {sku} already exists!"}

    db.execute(text("""
        INSERT INTO products
        (name_en, name_te, sku, mrp, selling_price, stock_qty, is_oem)
        VALUES (:name_en, :name_te, :sku, :mrp, :sp, :sq, :is_oem)
    """), {
        "name_en": name_en, "name_te": name_te,
        "sku": sku, "mrp": mrp,
        "sp": selling_price, "sq": stock_qty,
        "is_oem": is_oem
    })
    db.commit()
    return {"message": "Product added!", "sku": sku}


@app.put("/products/{product_id}/oem")
def update_oem_status(product_id: int, data: dict, db: Session = Depends(get_db)):
    is_oem = bool(data.get("is_oem", False))
    db.execute(text("""
        UPDATE products SET is_oem = :is_oem WHERE id = :id
    """), {"is_oem": is_oem, "id": product_id})
    db.commit()
    return {"message": "Updated!", "is_oem": is_oem}

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

    return {
        "products": [dict(r._mapping) for r in products]
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
# ── ADD THESE IMPORTS IF NOT ALREADY THERE ──
import base64
import time


# ── CUSTOMER PUSH TOKEN SAVE ──
@app.post("/customers/{phone}/push-token")
async def save_customer_push_token(phone: str, request: Request, db=Depends(get_db)):
    try:
        body = await request.json()
        token = body.get("token", "").strip()
        if not token:
            return {"error": "No token"}
        db.execute(text("""
            INSERT INTO customer_tokens (phone, token)
            VALUES (:phone, :token)
            ON CONFLICT (phone) DO UPDATE SET token = :token
        """), {"phone": phone, "token": token})
        db.commit()
        return {"saved": True}
    except Exception as e:
        return {"error": str(e)}

# ── PRODUCT IMAGE UPLOAD ──
@app.post("/products/{product_id}/upload-image")
async def upload_product_image(product_id: int, request: Request, db=Depends(get_db)):
    try:
        body = await request.json()
        image_b64 = body.get("image_base64", "")
        if not image_b64:
            return {"error": "No image provided"}

        image_bytes = base64.b64decode(image_b64)
        filename = f"products/prod_{product_id}_{int(time.time())}.jpg"
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_KEY", "")

        # Upload to Supabase Storage bucket named "product-images"
        upload_url = f"{supabase_url}/storage/v1/object/product-images/{filename}"
        headers = {
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "image/jpeg",
            "x-upsert": "true"
        }
        r = requests.put(upload_url, headers=headers, data=image_bytes)

        if r.status_code not in [200, 201]:
            return {"error": f"Upload failed: {r.status_code}"}

        public_url = f"{supabase_url}/storage/v1/object/public/product-images/{filename}"

        db.execute(text(
            "UPDATE products SET image_url = :url WHERE id = :id"
        ), {"url": public_url, "id": product_id})
        db.commit()

        return {"image_url": public_url, "success": True}
    except Exception as e:
        return {"error": str(e)}

# ── BROADCAST PUSH TO ALL CUSTOMERS ──
# ── OFFERS / DEALS ──
@app.get("/offers/all")
def get_all_offers(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            SELECT id, title, description, discount_percent, 
                   emoji, is_active, created_at
            FROM offers
            ORDER BY created_at DESC
        """)).fetchall()
        offers = [dict(r._mapping) for r in result]
        return {"offers": offers}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"offers": []}

@app.get("/offers")
def get_active_offers(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            SELECT id, title, description, discount_percent,
                   emoji, is_active, created_at
            FROM offers
            WHERE is_active = true
            ORDER BY created_at DESC
        """)).fetchall()
        offers = [dict(r._mapping) for r in result]
        return {"offers": offers}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"offers": []}

@app.post("/offers")
def create_offer(data: dict, db: Session = Depends(get_db)):
    try:
        title = data.get("title", "").strip()
        description = data.get("description", "").strip()
        discount_percent = data.get("discount_percent", 0)
        emoji = data.get("emoji", "🎉")
        if not title:
            return {"error": "Title is required"}
        db.execute(text("""
            INSERT INTO offers (title, description, discount_percent, emoji, is_active)
            VALUES (:title, :description, :discount_percent, :emoji, true)
        """), {
            "title": title,
            "description": description,
            "discount_percent": discount_percent,
            "emoji": emoji
        })
        db.commit()
        return {"message": "Offer created!", "success": True}
    except Exception as e:
        return {"error": str(e)}

@app.put("/offers/{offer_id}/toggle")
def toggle_offer(offer_id: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            UPDATE offers SET is_active = NOT is_active WHERE id = :id
        """), {"id": offer_id})
        db.commit()
        return {"message": "Toggled!"}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/offers/{offer_id}")
def delete_offer(offer_id: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("DELETE FROM offers WHERE id = :id"), {"id": offer_id})
        db.commit()
        return {"message": "Deleted!"}
    except Exception as e:
        return {"error": str(e)}

# ── STAFF STATS ──
@app.get("/staff/{staff_id}/stats")
def get_staff_stats(staff_id: int, db: Session = Depends(get_db)):
    try:
        packed = db.execute(text("""
            SELECT COUNT(*) FROM orders 
            WHERE packed_by LIKE :name
            AND created_at >= date_trunc('month', CURRENT_DATE)
        """), {"name": f"%{staff_id}%"}).scalar() or 0

        collected = db.execute(text("""
            SELECT COUNT(*) FROM orders 
            WHERE status = 'collected'
            AND created_at >= date_trunc('month', CURRENT_DATE)
        """)).scalar() or 0

        revenue = db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) FROM orders
            WHERE status = 'collected'
            AND created_at >= date_trunc('month', CURRENT_DATE)
        """)).scalar() or 0

        return {
            "packed": int(packed),
            "collected": int(collected),
            "revenue": float(revenue)
        }
    except Exception as e:
        return {"packed": 0, "collected": 0, "revenue": 0}



# ── REWARDS SYSTEM ──
@app.get("/rewards")
def get_rewards(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            SELECT id, name, description, points_required, is_active
            FROM rewards WHERE is_active = true ORDER BY points_required ASC
        """)).fetchall()
        return {"rewards": [dict(r._mapping) for r in result]}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"rewards": []}

@app.post("/rewards")
def add_reward(data: dict, db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            INSERT INTO rewards (name, description, points_required, is_active)
            VALUES (:name, :description, :points_required, true)
            RETURNING id
        """), {
            "name": data.get("name"),
            "description": data.get("description", ""),
            "points_required": data.get("points_required", 100)
        })
        db.commit()
        row = result.fetchone()
        return {"id": row[0], "success": True}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/rewards/{reward_id}")
def delete_reward(reward_id: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("UPDATE rewards SET is_active = false WHERE id = :id"), {"id": reward_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/loyalty/{phone}/redeem-reward")
def redeem_reward(phone: str, data: dict, db: Session = Depends(get_db)):
    try:
        reward_id = data.get("reward_id")
        points = data.get("points", 0)
        result = db.execute(text(
            "SELECT points FROM loyalty_points WHERE phone = :phone"
        ), {"phone": phone}).fetchone()
        if not result or result[0] < points:
            return {"success": False, "error": "Not enough points"}
        db.execute(text("""
            UPDATE loyalty_points SET points = points - :points WHERE phone = :phone
        """), {"points": points, "phone": phone})
        db.commit()
        return {"success": True, "message": "Reward redeemed!"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── ACTIVITY LOG ──
def log_activity(db, staff_name: str, action: str, details: str = "", order_id: int = None):
    """Log every staff action to activity_log table"""
    try:
        db.execute(text("""
            INSERT INTO activity_log (staff_name, action, details, order_id, created_at)
            VALUES (:staff_name, :action, :details, :order_id, NOW())
        """), {
            "staff_name": staff_name,
            "action": action,
            "details": details,
            "order_id": order_id
        })
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        pass

@app.get("/activity-log")
def get_activity_log(limit: int = 50, db: Session = Depends(get_db)):
    try:
        result = db.execute(text("""
            SELECT id, staff_name, action, details, order_id, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        return {"logs": [dict(r._mapping) for r in result]}
    except Exception as e:
        return {"logs": [], "error": str(e)}

@app.post("/activity-log")
def add_activity_log(data: dict, db: Session = Depends(get_db)):
    try:
        log_activity(
            db,
            staff_name=data.get("staff_name", "Unknown"),
            action=data.get("action", ""),
            details=data.get("details", ""),
            order_id=data.get("order_id")
        )
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


