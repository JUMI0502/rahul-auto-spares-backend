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
