from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.get("/products/barcode/{code}")
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
