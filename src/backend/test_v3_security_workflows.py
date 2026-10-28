"""Adversarial API, authorization and protocol tests on synthetic records."""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import nso
from nso.research_advanced import AdvancedResearchService
from nso.manufacturing.store import SQLiteDesignStore
from nso.research_contracts import ObservationBatch
from nso.research_fixtures import (
    observation,
    optical_envelope,
    learning_request,
    seed_learning_cases,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = SQLiteDesignStore(tmp_path / "secure.db")
    monkeypatch.setattr(nso, "REGISTRY", nso.DesignRegistry(store))
    svc = AdvancedResearchService(store)
    nso.ClinicalDigitalThread(store).create_case(
        patient_id="P",
        case_id="C",
        site_id="SITE",
        clinician_id="TEST",
        indication_code="SYNTHETIC",
    )
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    principals = [
        {
            "actor": "researcher",
            "token_sha256": hashlib.sha256(b"session-code").hexdigest(),
            "roles": ["researcher", "optical_engineer", "validator"],
            "patient_ids": ["P"],
            "expires_at": future,
        },
        {
            "actor": "outsider",
            "token_sha256": hashlib.sha256(b"outsider-code").hexdigest(),
            "roles": ["researcher"],
            "patient_ids": [],
            "expires_at": future,
        },
    ]
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(principals))
    for name in ("NPM", "IPM_RESEARCH", "OPTIMIZER"):
        monkeypatch.setenv("NSO_V3_" + name + "_ENABLED", "true")
    with TestClient(api.app) as c:
        yield c, svc, principals


def headers(key="test-request-001", token="session-code"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def protocol():
    return {
        "name": "Synthetic protocol",
        "version": "1",
        "inclusion_criteria": ["Synthetic eligible"],
        "exclusion_criteria": ["No clinical data"],
        "estimand": "Twelve-month observed arm difference in axial elongation",
        "assignment": "randomized",
        "analysis_population": "intention_to_treat",
        "covariates": ["age", "baseline_al", "baseline_se"],
        "missingness_plan": "Report missing outcomes and sensitivity analyses.",
        "switching_plan": "Retain assigned patients for intention-to-treat analysis.",
        "safety_plan": "Review unresolved adverse events before approval.",
        "analysis_plan": "Locked patient-level analysis with no individual effects.",
    }


def test_protocol_enrollment_event_and_wrong_scope(client):
    c, svc, _ = client
    locked = c.post("/api/v3/studies/protocols", headers=headers(), json=protocol())
    assert locked.status_code == 201
    pid = locked.json()["record_id"]
    body = {
        "patient_id": "P",
        "case_id": "C",
        "eye": "OD",
        "protocol_id": pid,
        "index_date": "2026-01-01",
        "eligible": True,
        "assigned_arm": "NONE",
        "eligibility_reasons": ["Eligible invented fixture"],
        "age": 10,
        "baseline_al": 24,
        "baseline_se": -2,
        "prior_al_slope": 0.2,
        "sex_code": 0,
    }
    assert (
        c.post(
            "/api/v3/studies/enrollments", headers=headers("no-allocation"), json=body
        ).status_code
        == 422
    )
    body["allocation_reference"] = "SYN-ALLOCATION"
    assert (
        c.post(
            "/api/v3/studies/enrollments", headers=headers("enrollment001"), json=body
        ).status_code
        == 201
    )
    assert (
        c.post(
            "/api/v3/studies/enrollments", headers=headers("enrollment002"), json=body
        ).status_code
        == 409
    )
    event = {
        "patient_id": "P",
        "case_id": "C",
        "eye": "OD",
        "protocol_id": pid,
        "event_at": "2026-02-01",
        "kind": "adverse_event",
        "severity": "mild",
        "description": "Invented transient discomfort event",
    }
    assert (
        c.post(
            "/api/v3/studies/events", headers=headers("event-test-001"), json=event
        ).status_code
        == 201
    )
    assert (
        c.post(
            "/api/v3/studies/events",
            headers=headers("event-test-002", token="outsider-code"),
            json=event,
        ).status_code
        == 403
    )
    event["event_at"] = "2025-01-01"
    assert (
        c.post(
            "/api/v3/studies/events", headers=headers("event-test-003"), json=event
        ).status_code
        == 422
    )


def test_protected_envelope_upload_and_summary_api(client):
    c, svc, _ = client
    result = c.post(
        "/api/v3/optimizer/envelopes", headers=headers(), json=optical_envelope()
    )
    assert result.status_code == 201
    assert "bounds" not in result.json()
    submitted = c.post(
        "/api/v3/optimizer/run",
        headers=headers("optical-run-001"),
        json={
            "patient_id": "P",
            "case_id": "C",
            "eye": "OD",
            "envelope_id": result.json()["envelope_id"],
            "candidate_budget": 8,
        },
    )
    assert submitted.status_code == 202
    status = c.get("/api/v3/optimizer/" + submitted.json()["run_id"], headers=headers())
    assert status.status_code == 200 and status.json()["status"] == "completed"
    assert "parameters" not in status.text and "noise_height_um" not in status.text


def test_expired_or_invalid_principal_fails_closed(client, monkeypatch):
    c, svc, principals = client
    principals[0]["expires_at"] = "2020-01-01T00:00:00Z"
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(principals))
    result = c.get("/api/v3/cases", headers=headers())
    assert (
        result.status_code == 401
        and result.json()["detail"]["code"] == "SESSION_EXPIRED"
    )
    principals[0]["token_sha256"] = "X" * 64
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(principals))
    assert c.get("/api/v3/session", headers=headers()).status_code == 503


def test_production_legacy_calls_require_session_and_patient_scope(client, monkeypatch):
    c, svc, principals = client
    monkeypatch.setenv("NSO_ENV", "production")
    body = {
        "patient_id": "P",
        "age": 10,
        "od": {"sphere": -2, "axial_length": 24},
        "os": {"sphere": -2, "axial_length": 24},
    }
    assert c.post("/api/predict", json=body).status_code == 401
    assert (
        c.post(
            "/api/predict", json=body, headers=headers(token="outsider-code")
        ).status_code
        == 403
    )
    assert c.post("/api/v2/models", json={}, headers=headers()).status_code == 403
    assert any(
        e.get("event_type") == "LEGACY_API_ACCESS" and e["status_code"] == 403
        for e in svc.store.audits()
    )


def test_clinical_predict_reuses_governed_patient_and_eye_records(client, monkeypatch):
    c, svc, principals = client
    import nso.clinical

    monkeypatch.setattr(nso.clinical, "REGISTRY", nso.REGISTRY)
    original = svc.store.get_record("patient", "P")
    nso.ClinicalDigitalThread(svc.store).ensure_eyes("P")
    monkeypatch.setenv("NSO_ENV", "production")
    result = c.post(
        "/api/predict",
        headers=headers(),
        json={
            "patient_id": "P",
            "age": 10,
            "od": {"sphere": -2, "axial_length": 24},
            "os": {"sphere": -2, "axial_length": 24},
        },
    )
    assert result.status_code == 200, result.text
    assert svc.store.get_record("patient", "P") == original
    assert result.headers["cache-control"] == "no-store"


def test_standalone_cors_only_configured_origin(monkeypatch):
    from research_app import create_app

    monkeypatch.setenv("NSO_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://approved.example")
    with TestClient(create_app()) as c:
        allowed = c.options(
            "/api/v3/npm/predict",
            headers={
                "Origin": "https://approved.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        forbidden = c.options(
            "/api/v3/npm/predict",
            headers={
                "Origin": "https://arbitrary.vercel.app",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert allowed.status_code == 200 and forbidden.status_code == 400


def test_synthetic_demos_work_without_access_to_clinical_store(client):
    c, svc, _ = client
    study = c.post("/api/v3/demo/study", json={"assignment": "randomized"})
    assert study.status_code == 200, study.text
    assert study.json()["adjusted"]["patients"] == 40
    optics = c.post("/api/v3/demo/optics", json={"seed": 17})
    assert optics.status_code == 200 and optics.json()["candidates"]
    assert optics.json()["synthetic"] and not optics.json()["clinical_use_allowed"]
    assert svc.store.list_records("v3_cohort") == []
    assert svc.store.list_records("v3_optical_candidate") == []
    assert (
        c.post(
            "/api/v3/demo/study", json={"assignment": "randomized", "patient_id": "P"}
        ).status_code
        == 422
    )


def test_api_correction_and_audit(client):
    c, svc, _ = client
    saved = svc.ingest(
        ObservationBatch(
            patient_id="P",
            case_id="C",
            eye="OD",
            observations=[observation(date(2026, 1, 1), 24, -2)],
        ),
        "test",
    )
    payload = {
        "patient_id": "P",
        "case_id": "C",
        "eye": "OD",
        "observation_id": saved["observation_ids"][0],
        "expected_revision": 0,
        "reason": "Correct the invented transcription",
        "replacement": observation(date(2026, 1, 1), 24.1, -2).model_dump(mode="json"),
    }
    corrected = c.post("/api/v3/observations/correct", headers=headers(), json=payload)
    assert corrected.status_code == 200
    read = c.get("/api/v3/cases/C/observations?eye=OD", headers=headers()).json()
    assert read["observations"][0]["revision"] == 1
    assert (
        c.post(
            "/api/v3/observations/correct",
            headers=headers("second-correction"),
            json=payload,
        ).status_code
        == 409
    )


def test_training_api_checks_patient_scope_before_running(client):
    c, svc, _ = client
    request = learning_request()
    seed_learning_cases(svc, request)
    result = c.post(
        "/api/v3/models/train", headers=headers(), json=request.model_dump(mode="json")
    )
    assert result.status_code == 403
    assert svc.store.list_records("v3_training_job") == []


def test_event_resolution_keeps_original_and_is_scoped(client):
    c, svc, _ = client
    event = svc.save(
        "study_event",
        "SEV",
        {
            "patient_id": "P",
            "case_id": "C",
            "eye": "OD",
            "event_at": "2026-02-01",
            "severity": "severe",
            "kind": "adverse_event",
            "resolved_at": None,
        },
        "clinician",
    )
    body = {
        "patient_id": "P",
        "case_id": "C",
        "eye": "OD",
        "event_id": event["record_id"],
        "resolved_at": "2026-02-05",
        "reason": "Reviewed synthetic event, symptoms resolved",
    }
    assert (
        c.post(
            "/api/v3/studies/events/resolve",
            json=body,
            headers=headers(token="outsider-code"),
        ).status_code
        == 403
    )
    saved = c.post("/api/v3/studies/events/resolve", json=body, headers=headers())
    assert saved.status_code == 200
    assert svc.get("study_event", event["record_id"])["resolved_at"] is None
    assert (
        svc.store.list_records("v3_event_resolution")[0]["resolved_at"] == "2026-02-05"
    )
    assert (
        c.post(
            "/api/v3/studies/events/resolve",
            json=body,
            headers=headers("resolution-repeat"),
        ).status_code
        == 409
    )


def test_model_review_cannot_access_another_study_population(client, monkeypatch):
    c, svc, principals = client
    artifact = svc.save(
        "trained_model",
        "NPM3",
        {"training_patient_ids": ["UNASSIGNED"], "actor": "trainer"},
        "trainer",
    )
    reply = c.post(
        "/api/v3/releases/review",
        headers=headers(),
        json={
            "target_kind": "model",
            "target_id": artifact["record_id"],
            "decision": "reject",
            "reason": "Attempt review outside assigned study population",
        },
    )
    assert reply.status_code == 403


def test_training_approval_deployment_and_serving_over_http(client, monkeypatch):
    c, svc, principals = client
    request = learning_request()
    seed_learning_cases(svc, request)
    ids = sorted({s.patient_id for s in request.samples})
    principals[0]["patient_ids"] += ids
    expiry = principals[0]["expires_at"]
    for actor, token, role in (
        ("reviewer", "reviewer-code", "validator"),
        ("operator", "operator-code", "deployer"),
    ):
        principals.append(
            {
                "actor": actor,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "roles": [role],
                "patient_ids": ids,
                "expires_at": expiry,
            }
        )
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(principals))
    policy = c.post(
        "/api/v3/models/policies",
        headers=headers(),
        json={
            "name": "Synthetic HTTP workflow policy",
            "minimum_test_patients": 8,
            "minimum_coverage": 0.5,
        },
    ).json()
    request.validation_policy_id = policy["record_id"]
    queued = c.post(
        "/api/v3/models/train",
        headers=headers("train-http-001"),
        json=request.model_dump(mode="json"),
    )
    assert queued.status_code == 202, queued.text
    finished = c.get(
        "/api/v3/models/training/" + queued.json()["run_id"], headers=headers()
    )
    assert finished.status_code == 200 and finished.json()["status"] == "completed", (
        finished.text
    )
    assert "weights" not in finished.text and "samples" not in finished.text
    model_id = finished.json()["model_id"]
    approval = c.post(
        "/api/v3/releases/review",
        headers=headers("review-http-001", "reviewer-code"),
        json={
            "target_kind": "model",
            "target_id": model_id,
            "policy_id": policy["record_id"],
            "decision": "approve",
            "reason": "Independent HTTP workflow check using invented records",
        },
    )
    assert approval.status_code == 200, approval.text
    deployed = c.post(
        "/api/v3/releases/deploy",
        headers=headers("deploy-http-001", "operator-code"),
        json={
            "model_id": model_id,
            "review_id": approval.json()["record_id"],
            "reason": "Explicit independent operator release of research artifact",
        },
    )
    assert deployed.status_code == 200, deployed.text
    sample = next(s for s in request.samples if s.split == "train")
    scope = {k: getattr(sample, k) for k in ("patient_id", "case_id", "eye")}
    imported = c.post(
        "/api/v3/observations",
        headers=headers("import-http-001"),
        json={
            **scope,
            "observations": [s.model_dump(mode="json") for s in sample.history],
        },
    )
    assert imported.status_code == 201, imported.text
    forecast = c.post(
        "/api/v3/npm/predict",
        headers=headers("predict-http-001"),
        json={
            **scope,
            "model_id": model_id,
            "index_date": sample.index_date.isoformat(),
            "index_age": sample.index_age,
            "untreated_history_confirmed": True,
        },
    )
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()["forecasts"][0]["al_interval"] is not None
    assert (
        "history_snapshot" not in forecast.text
        and not forecast.json()["clinical_use_allowed"]
    )
