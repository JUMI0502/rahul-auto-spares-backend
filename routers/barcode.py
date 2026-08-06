from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

import sentry_sdk

from database import get_db

router = APIRouter()


@router.get("/products/barcode/{code}")
def search_by_barcode(
    code: str,
    db: Session = Depends(get_db)
):
    # Self-healing: the products table never had a 'barcode' column,
    # so this query has likely always failed whenever it fell through
    # to the barcode match (only working when sku matched directly).
    try:
        db.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS barcode TEXT;"))
        db.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        db.rollback()

    product = db.execute(text("""
        SELECT id, name_en, name_te, name_hi, sku, mrp, selling_price, stock_qty
        FROM products
        WHERE sku = :code
        OR barcode = :code
        LIMIT 1
    """), {"code": code}).fetchone()

    if not product:
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
