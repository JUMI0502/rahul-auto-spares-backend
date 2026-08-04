from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import sentry_sdk

from database import get_db

router = APIRouter()


@router.get("/reports/business-health")
def get_business_health(db: Session = Depends(get_db)):
    staff_rows = db.execute(text("""
        SELECT collected_by, COUNT(*) as orders_completed
        FROM orders
        WHERE collected_by IS NOT NULL
          AND created_at > date_trunc('month', NOW())
        GROUP BY collected_by
        ORDER BY orders_completed DESC
    """)).fetchall()
    staff_productivity = [{"name": r[0], "orders_completed": r[1]} for r in staff_rows]

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
