import secrets
import time
from fastapi import Header, HTTPException

# Customer session tokens - issued after PIN verification, required for
# any endpoint that returns/modifies data tied to a specific phone number.
# Without this, anyone with the app's API key could access ANY customer's
# order history, points, or delete their account just by knowing their phone.
_customer_sessions = {}  # token -> {"phone": str, "expires_at": float}
SESSION_DURATION_SECONDS = 60 * 60 * 24 * 7  # 7 days


def create_customer_session(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    _customer_sessions[token] = {"phone": phone, "expires_at": time.time() + SESSION_DURATION_SECONDS}
    return token


def require_customer_session(phone: str, x_session_token: str = Header(None)):
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Session token required")
    session = _customer_sessions.get(x_session_token)
    if not session or session["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="Session expired - please log in again")
    if session["phone"] != phone:
        raise HTTPException(status_code=403, detail="Session does not match requested account")
    return True


def check_customer_session(phone: str, token: str) -> bool:
    """Manual (non-Depends) version of require_customer_session, for
    endpoints where phone comes from the request body rather than a URL
    path parameter - FastAPI's automatic dependency binding only works
    when the name matches a path param, so those routes need to check
    this by hand instead."""
    if not token:
        return False
    session = _customer_sessions.get(token)
    if not session or session["expires_at"] < time.time():
        return False
    return session["phone"] == phone


# Staff session tokens - issued after PIN verification, same pattern as
# customer sessions above. Without this, any staff member's PIN could be
# changed or reset by anyone with the shared API key, just by knowing
# their staff_id - no proof of identity or authority required.
_staff_sessions = {}  # token -> {"staff_id": int, "role": str, "expires_at": float}


def create_staff_session(staff_id: int, role: str) -> str:
    token = secrets.token_urlsafe(32)
    _staff_sessions[token] = {"staff_id": staff_id, "role": role, "expires_at": time.time() + SESSION_DURATION_SECONDS}
    return token


def get_staff_session(x_staff_session_token: str = Header(None)):
    """Returns the caller's {staff_id, role} for endpoints that need to
    know WHO is calling, not just whether they have the shared API key."""
    if not x_staff_session_token:
        raise HTTPException(status_code=401, detail="Staff session token required")
    session = _staff_sessions.get(x_staff_session_token)
    if not session or session["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="Session expired - please log in again")
    return session
