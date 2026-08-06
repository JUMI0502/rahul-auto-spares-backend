from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.get("/customers/all")
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
