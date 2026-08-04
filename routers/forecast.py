from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.get("/products/forecast")
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
            days_remaining = None

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
