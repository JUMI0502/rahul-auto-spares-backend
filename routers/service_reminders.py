from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import sentry_sdk

from database import get_db

router = APIRouter()


def _ensure_service_reminders_table(db: Session):
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


@router.get("/customers/service-due")
def get_service_due_customers(days: int = 60, db: Session = Depends(get_db)):
    _ensure_service_reminders_table(db)

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


@router.post("/customers/{phone}/service-reminder-sent")
def mark_service_reminder_sent(phone: str, db: Session = Depends(get_db)):
    _ensure_service_reminders_table(db)

    db.execute(text("""
        INSERT INTO service_reminders_sent (customer_phone)
        VALUES (:phone)
    """), {"phone": phone})
    db.commit()
    return {"message": "Recorded"}
