from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import sentry_sdk

from database import get_db
from auth import get_staff_session

router = APIRouter()


@router.post("/warranty-claims")
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


@router.get("/warranty-claims")
def get_warranty_claims(status: str = None, db: Session = Depends(get_db)):
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


@router.put("/warranty-claims/{claim_id}")
def update_warranty_claim(claim_id: int, data: dict, db: Session = Depends(get_db), _session: dict = Depends(get_staff_session)):
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
