"""Deployment boundary for legacy APIs, exact CORS and bounded request handling."""

from collections import OrderedDict
import os
import threading
import time

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

_attempts = OrderedDict()
_lock = threading.Lock()


def reject(status, code, message):
    return JSONResponse(
        {"detail": {"code": code, "message": message}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def request_limit(request):
    length = request.headers.get("content-length")
    try:
        if length and int(length) > 8_000_000:
            return reject(413, "REQUEST_TOO_LARGE", "Maximum request size is 8 MB.")
    except ValueError:
        return reject(400, "INVALID_CONTENT_LENGTH", "Invalid request length.")
    if request.url.path.startswith("/api/v3/demo/"):
        host = request.client.host if request.client else "unknown"
        key = (host, int(time.monotonic() // 60))
        with _lock:
            _attempts[key] = _attempts.get(key, 0) + 1
            while len(_attempts) > 1000:
                _attempts.popitem(last=False)
            if _attempts[key] > 60:
                return reject(
                    429,
                    "RATE_LIMITED",
                    "Please wait before running another synthetic demonstration.",
                )


async def legacy_access(request):
    """Production legacy reads/writes require server-owned roles and patient scope."""
    if os.getenv("NSO_ENV", "development").lower() != "production":
        return
    if request.method == "OPTIONS":
        return
    path = request.url.path
    if (
        not path.startswith("/api/")
        or path == "/api/health"
        or path.startswith("/api/v3/")
    ):
        return
    # Segmented vendor interfaces retain their separate vendor-key verifier.
    if path in {"/api/manufacturing/package", "/api/manufacturing/verify"}:
        return
    from research_api import principal, permit, scope, service

    raw = request.headers.get("authorization", "")
    credentials = (
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw[7:])
        if raw.startswith("Bearer ")
        else None
    )
    try:
        user = principal(request, credentials)
        permission = (
            "approve"
            if path in {"/api/design/approve", "/api/manufacturing/submit"}
            else ("clinical" if request.method != "GET" else "read")
        )
        permit(user, permission)
        if path.startswith("/api/v2/"):
            # V2 generic governance endpoints use client-selected role headers;
            # keep production governance on V3's server-owned role workflows.
            if path.startswith("/api/v2/trace/"):
                case = service().store.get_record("case", path.rsplit("/", 1)[-1])
                scope(user, case["patient_id"])
                return
            return reject(
                403,
                "USE_GOVERNED_V3_API",
                "Use the governed V3 API for production record and model management.",
            )
        if request.method == "GET":
            if path.startswith("/api/governance/lineage/"):
                execution = service().store.get_record(
                    "execution", path.rsplit("/", 1)[-1]
                )
                scope(user, execution["patient_id"])
                return
            return reject(403, "FORBIDDEN", "Legacy read path is not authorized.")
        body = await request.json()
        if not isinstance(body, dict):
            return reject(400, "INVALID_REQUEST", "A JSON object is required.")
        identifiers = [
            body.get(k) for k in ("design_id", "previous_design_id") if body.get(k)
        ]
        patient = body.get("patient_id")
        if patient:
            scope(user, patient)
        for key in identifiers:
            design = service().store.get(key)
            scope(user, design["patient_id"])
            if patient and design["patient_id"] != patient:
                return reject(403, "FORBIDDEN", "Patient and design do not match.")
        if not patient and not identifiers:
            return reject(
                403,
                "PATIENT_SCOPE_REQUIRED",
                "Select an assigned patient before using clinical functions.",
            )
        if path in {"/api/design/approve", "/api/manufacturing/submit"}:
            permit(user, "approve")
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    except (KeyError, ValueError, TypeError):
        return reject(403, "FORBIDDEN", "Record unavailable to this session.")


def log_legacy_access(request, status):
    if os.getenv("NSO_ENV", "development").lower() != "production":
        return
    if (
        not request.url.path.startswith("/api/")
        or request.url.path.startswith("/api/v3/")
        or request.url.path == "/api/health"
    ):
        return
    if request.method == "OPTIONS":
        return
    from research_api import service
    from .research import now

    service().store.append_audit(
        {
            "event_type": "LEGACY_API_ACCESS",
            "action": "LEGACY_API_ACCESS",
            "object_id": request.url.path,
            "actor": getattr(request.state, "research_actor", "unauthenticated"),
            "timestamp": now(),
            "status_code": status,
            "result": "success" if status < 400 else "denied_or_failed",
        }
    )
