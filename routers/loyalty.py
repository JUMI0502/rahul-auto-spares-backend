from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import require_customer_session

router = APIRouter()


@router.get("/loyalty/{phone}")
def get_loyalty_points(
  phone: str, db: Session = Depends(get_db),
  _auth: bool = Depends(require_customer_session)
):
    result = db.execute(text("""
        SELECT points, total_earned, total_redeemed
        FROM customer_loyalty_points
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()
    if not result:
        return {
            "points": 0,
            "total_earned": 0,
            "total_redeemed": 0
        }
    return {
        "points": result[0],
        "total_earned": result[1],
        "total_redeemed": result[2]
    }


@router.post("/loyalty/{phone}/add")
def add_loyalty_points(
  phone: str,
  data: dict,
  db: Session = Depends(get_db)
):
    points = data.get("points", 0)
    if points <= 0:
        return {"error": "Invalid points"}
    db.execute(text("""
        INSERT INTO customer_loyalty_points
        (phone, points, total_earned, updated_at)
        VALUES (:phone, :points, :points, NOW())
        ON CONFLICT (phone) DO UPDATE
        SET points = customer_loyalty_points.points + :points,
            total_earned =
              customer_loyalty_points.total_earned + :points,
            updated_at = NOW()
    """), {"phone": phone, "points": points})
    db.commit()
    return {"message": "Points added!", "added": points}


@router.post("/loyalty/{phone}/redeem")
def redeem_loyalty_points(
  phone: str,
  data: dict,
  db: Session = Depends(get_db)
):
    points = data.get("points", 0)
    result = db.execute(text("""
        SELECT points FROM customer_loyalty_points
        WHERE phone = :phone
    """), {"phone": phone}).fetchone()
    if not result or result[0] < points:
        return {"error": "Not enough points"}
    db.execute(text("""
        UPDATE customer_loyalty_points
        SET points = points - :points,
            total_redeemed = total_redeemed + :points,
            updated_at = NOW()
        WHERE phone = :phone
    """), {"phone": phone, "points": points})
    db.commit()
    return {"message": "Points redeemed!", "redeemed": points}
