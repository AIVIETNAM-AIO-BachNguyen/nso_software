"""Clinical admin credentials, revocation and authorization boundary tests."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import clinical_admin_auth as auth
import nso
from nso.manufacturing.store import SQLiteDesignStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = SQLiteDesignStore(tmp_path / "admin.db")
    monkeypatch.setattr(nso, "REGISTRY", nso.DesignRegistry(store))
    nso.ClinicalDigitalThread(store).create_case(
        patient_id="P",
        case_id="C",
        site_id="S",
        clinician_id="TEST",
        indication_code="SYNTHETIC",
    )
    monkeypatch.setenv("NSO_ENV", "production")
    monkeypatch.setenv("NSO_V3_PRINCIPALS", "[]")
    monkeypatch.setenv("NSO_CLINICAL_ADMIN_USERNAME", "nso")
    monkeypatch.setenv(
        "NSO_CLINICAL_ADMIN_PASSWORD_HASH", auth.password_hash("2026nso")
    )
    monkeypatch.setenv("NSO_CLINICAL_ADMIN_PATIENT_IDS", json.dumps(["P"]))
    auth._sessions.clear()
    auth._attempts.clear()
    with TestClient(api.app) as c:
        yield c
    auth._sessions.clear()
    auth._attempts.clear()


def sign_in(client):
    r = client.post(
        "/api/v3/auth/clinical-admin/login",
        json={"username": "nso", "password": "2026nso"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_admin_sign_in_scope_and_sign_out(client, monkeypatch):
    headers = sign_in(client)
    r = client.get("/api/v3/cases", headers=headers)
    assert r.status_code == 200
    assert [c["patient_id"] for c in r.json()["cases"]] == ["P"]
    assert client.get("/api/v3/session", headers=headers).json()["roles"] == [
        "clinical_admin"
    ]
    # Admin fitting is authorized but invalid clinical inputs still fail validation.
    assert (
        client.post(
            "/api/predict", headers=headers, json={"patient_id": "P"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/predict", headers=headers, json={"patient_id": "OTHER"}
        ).status_code
        == 403
    )
    from research_api import permit
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        permit({"roles": ["clinical_admin"]}, "deploy")
    monkeypatch.setenv("NSO_CLINICAL_ADMIN_PATIENT_IDS", "[]")
    assert client.get("/api/v3/cases", headers=headers).json()["cases"] == []
    assert (
        client.post("/api/v3/auth/clinical-admin/logout", headers=headers).status_code
        == 200
    )
    assert client.get("/api/v3/cases", headers=headers).status_code != 200


def test_wrong_credentials_and_rate_limit(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v3/auth/clinical-admin/login",
                json={"username": "nso", "password": "wrong"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v3/auth/clinical-admin/login",
            json={"username": "another", "password": "2026nso"},
        ).status_code
        == 429
    )


def test_expired_and_password_rotated_sessions(client, monkeypatch):
    headers = sign_in(client)
    _, user = next(iter(auth._sessions.values()))
    user["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert client.get("/api/v3/cases", headers=headers).status_code == 401
    auth._sessions.clear()
    headers = sign_in(client)
    monkeypatch.setenv(
        "NSO_CLINICAL_ADMIN_PASSWORD_HASH", auth.password_hash("changed")
    )
    assert client.get("/api/v3/cases", headers=headers).status_code == 401


def test_unconfigured_login_and_wildcard_scope_rejected(client, monkeypatch):
    monkeypatch.delenv("NSO_CLINICAL_ADMIN_PASSWORD_HASH")
    assert (
        client.post(
            "/api/v3/auth/clinical-admin/login",
            json={"username": "nso", "password": "2026nso"},
        ).status_code
        == 503
    )
    monkeypatch.setenv(
        "NSO_CLINICAL_ADMIN_PASSWORD_HASH", auth.password_hash("2026nso")
    )
    monkeypatch.setenv("NSO_CLINICAL_ADMIN_PATIENT_IDS", '["*"]')
    assert (
        client.post(
            "/api/v3/auth/clinical-admin/login",
            json={"username": "nso", "password": "2026nso"},
        ).status_code
        == 503
    )
