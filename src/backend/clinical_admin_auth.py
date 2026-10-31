"""Server-side clinical admin login with explicit patient scope and expiring sessions."""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v3/auth", tags=["Clinical authentication"])
_sessions = OrderedDict()
_attempts = OrderedDict()
_lock = threading.Lock()


def password_hash(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return salt + ":" + value.hex()


def _error(status, message):
    raise HTTPException(status_code=status, detail={"message": message})


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/clinical-admin/login")
def login(body: Login, request: Request):
    configured = os.getenv("NSO_CLINICAL_ADMIN_PASSWORD_HASH", "")
    try:
        patients = json.loads(os.getenv("NSO_CLINICAL_ADMIN_PATIENT_IDS", "[]"))
        salt, expected = configured.split(":")
        if (
            not salt
            or len(expected) != 64
            or not isinstance(patients, list)
            or not all(isinstance(p, str) and p != "*" for p in patients)
        ):
            raise ValueError()
    except (ValueError, TypeError):
        _error(503, "Clinical admin login has not been configured.")
    # Bound attempts independently of the supplied username; forwarded headers are untrusted.
    host = request.client.host if request.client else "unknown"
    key = (host, int(time.monotonic() // 300))
    with _lock:
        _attempts[key] = _attempts.get(key, 0) + 1
        while len(_attempts) > 1000:
            _attempts.popitem(last=False)
        if _attempts[key] > 10:
            _error(429, "Too many login attempts. Try again in five minutes.")
    actual = hashlib.pbkdf2_hmac(
        "sha256", body.password.encode(), salt.encode(), 600_000
    ).hex()
    valid_password = hmac.compare_digest(actual, expected)
    valid_user = hmac.compare_digest(
        body.username.encode(), os.getenv("NSO_CLINICAL_ADMIN_USERNAME", "nso").encode()
    )
    if not (valid_password and valid_user):
        _error(401, "Incorrect username or password.")
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    token = secrets.token_urlsafe(32)
    principal = {
        "actor": "clinical-admin:" + body.username,
        "roles": ["clinical_admin"],
        "patient_ids": patients,
        "expires_at": expiry.isoformat(),
    }
    with _lock:
        _sessions[hashlib.sha256(token.encode()).hexdigest()] = (configured, principal)
        while len(_sessions) > 1000:
            _sessions.popitem(last=False)
    return {"access_token": token, "expires_at": expiry.isoformat()}


def resolve(token):
    with _lock:
        item = _sessions.get(hashlib.sha256(token.encode()).hexdigest())
    if not item:
        return None
    configured, user = item
    if configured != os.getenv(
        "NSO_CLINICAL_ADMIN_PASSWORD_HASH"
    ) or datetime.fromisoformat(user["expires_at"]) <= datetime.now(timezone.utc):
        _error(401, "Admin session expired. Please sign in again.")
    # Apply scope reductions immediately to already-issued sessions.
    try:
        current = json.loads(os.getenv("NSO_CLINICAL_ADMIN_PATIENT_IDS", "[]"))
        patients = [p for p in user["patient_ids"] if p in current]
    except (ValueError, TypeError):
        patients = []
    return {**user, "patient_ids": patients}


@router.post("/clinical-admin/logout")
def logout(request: Request):
    raw = request.headers.get("authorization", "")
    if raw.startswith("Bearer "):
        with _lock:
            _sessions.pop(hashlib.sha256(raw[7:].encode()).hexdigest(), None)
    return {"logged_out": True}
