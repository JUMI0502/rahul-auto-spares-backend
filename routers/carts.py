from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import sentry_sdk
import json as jsonlib

from database import get_db

router = APIRouter()


def _ensure_active_carts_table(db: Session):
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


@router.post("/cart/save")
def save_cart(data: dict, db: Session = Depends(get_db)):
    phone = data.get("customer_phone", "").strip()
    name = data.get("customer_name", "")
    items = data.get("items", [])

    if not phone:
        return {"error": "Phone required"}

    _ensure_active_carts_table(db)

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


@router.delete("/cart/{phone}")
def clear_cart(phone: str, db: Session = Depends(get_db)):
    try:
        db.execute(text("DELETE FROM active_carts WHERE customer_phone = :phone"), {"phone": phone})
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()
    return {"message": "Cleared"}


@router.get("/carts/abandoned")
def get_abandoned_carts(hours: int = 3, db: Session = Depends(get_db)):
    _ensure_active_carts_table(db)

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


@router.post("/carts/{phone}/reminder-sent")
def mark_cart_reminder_sent(phone: str, db: Session = Depends(get_db)):
    _ensure_active_carts_table(db)

    db.execute(text(
        "UPDATE active_carts SET reminder_sent_at = NOW() WHERE customer_phone = :phone"
    ), {"phone": phone})
    db.commit()
    return {"message": "Recorded"}
