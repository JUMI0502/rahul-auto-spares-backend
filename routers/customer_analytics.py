from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.get("/customers/analytics")
def get_customer_analytics(
    db: Session = Depends(get_db)
):
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

    top_orderers = db.execute(text("""
        SELECT customer_name, customer_phone,
               COUNT(*) as order_count,
               SUM(total_amount) as total_spent
        FROM orders
        GROUP BY customer_name, customer_phone
        ORDER BY order_count DESC
        LIMIT 10
    """)).fetchall()

    # Fixed: was using SQLite's strftime(), which doesn't exist in
    # PostgreSQL - this endpoint likely errored every time it was called
    # before this fix, since the backend has always run on Postgres/Supabase.
    monthly = db.execute(text("""
        SELECT
            COUNT(DISTINCT customer_phone) as unique_customers,
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_revenue
        FROM orders
        WHERE date_trunc('month', created_at) = date_trunc('month', NOW())
    """)).fetchone()

    new_customers = db.execute(text("""
        SELECT COUNT(DISTINCT customer_phone)
        FROM orders
        WHERE date_trunc('month', created_at) = date_trunc('month', NOW())
        AND customer_phone NOT IN (
            SELECT DISTINCT customer_phone FROM orders
            WHERE created_at < date_trunc('month', NOW())
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
