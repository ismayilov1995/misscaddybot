# dashboard/auth.py
import os
from fastapi import Cookie, HTTPException, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

_SECRET = os.getenv("DASHBOARD_SECRET", "changeme-secret-key")
_USER = os.getenv("DASHBOARD_USER", "admin")
_PASS = os.getenv("DASHBOARD_PASS", "admin123")

_signer = URLSafeSerializer(_SECRET, salt="session")
SESSION_COOKIE = "dsession"


def make_session_token() -> str:
    return _signer.dumps({"u": _USER})


def verify_credentials(username: str, password: str) -> bool:
    return username == _USER and password == _PASS


def verify_session(token: str) -> bool:
    try:
        _signer.loads(token)
        return True
    except BadSignature:
        return False


def require_auth(dsession: str | None = Cookie(default=None)):
    if not dsession or not verify_session(dsession):
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
