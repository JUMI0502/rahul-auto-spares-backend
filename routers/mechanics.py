from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import sentry_sdk
import requests as http_requests

from database import get_db

router = APIRouter()


@router.post("/mechanics/register")
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

        if existing_status == 'approved':
            return {
                "id": existing_id,
                "status": "approved",
                "message": "Already approved!"
            }

        if existing_status == 'pending':
            return {
                "id": existing_id,
                "status": "pending",
                "message": "Still pending approval!"
            }

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

    try:
        tokens = db.execute(text(
            "SELECT DISTINCT token FROM push_tokens"
            " WHERE token IS NOT NULL"
        ))
        token_list = [row[0] for row in tokens]
        if token_list:
            messages = [{
                "to": token,
                "title": "New Mechanic Request!",
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

    return {
        "id": mechanic_id,
        "status": "pending",
        "message": "Registration submitted!"
    }


@router.get("/mechanics/check/{phone}")
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


@router.get("/mechanics")
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


@router.put("/mechanics/{mechanic_id}")
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


@router.delete("/mechanics/{mechanic_id}")
def delete_mechanic(mechanic_id: int, db: Session = Depends(get_db)):
    db.execute(text(
        "DELETE FROM mechanic_profiles WHERE id = :id"
    ), {"id": mechanic_id})
    db.commit()
    return {"message": "Mechanic deleted!"}


@router.put("/mechanics/{mechanic_id}/approve")
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
