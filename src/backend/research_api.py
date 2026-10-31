"""V3 APIs. Credentials resolve roles and patient scope on the server, never from headers."""

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse

import nso
from nso.research import (
    MODELS,
    SCHEMA_VERSION,
    ResearchError,
    ResearchService,
    digest,
    now,
)
from nso.research_contracts import (
    Cohort,
    DesignApproval,
    Estimate,
    Exposure,
    Forecast,
    ForecastResult,
    Observation,
    ObservationBatch,
    Optimization,
    OptimizationQueued,
    OptimizationState,
    Outcome,
    Validation,
)
from nso.research_operations import Operations

router = APIRouter(prefix="/api/v3", tags=["V3 research"])


def service():
    from nso.research_advanced import AdvancedResearchService

    return AdvancedResearchService(nso.REGISTRY._store_impl)


def enabled(name):
    return os.getenv("NSO_V3_" + name.upper() + "_ENABLED", "false").lower() == "true"


def fail(code, message, status=422):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


bearer = HTTPBearer(auto_error=False)


def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)] = None,
):
    from clinical_admin_auth import resolve

    if credentials and credentials.scheme.lower() == "bearer":
        admin = resolve(credentials.credentials)
        if admin:
            request.state.research_actor = admin["actor"]
            return admin
    try:
        principals = json.loads(os.getenv("NSO_V3_PRINCIPALS", "[]"))
        if not isinstance(principals, list):
            raise ValueError()
        for p in principals:
            if (
                not isinstance(p, dict)
                or not isinstance(p.get("actor"), str)
                or not isinstance(p.get("token_sha256"), str)
                or len(p["token_sha256"]) != 64
                or not isinstance(p.get("roles"), list)
                or not isinstance(p.get("patient_ids"), list)
                or not all(isinstance(x, str) for x in p["roles"] + p["patient_ids"])
            ):
                raise ValueError()
            if any(c not in "0123456789abcdef" for c in p["token_sha256"]):
                raise ValueError()
            if os.getenv(
                "NSO_ENV", "development"
            ).lower() == "production" and not p.get("expires_at"):
                raise ValueError()
            if p.get("expires_at"):
                expires = datetime.fromisoformat(p["expires_at"].replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    raise ValueError()
        if len({p["token_sha256"] for p in principals}) != len(principals):
            raise ValueError()
        if len({p["actor"] for p in principals}) != len(principals):
            raise ValueError()
    except (ValueError, TypeError):
        fail(
            "AUTH_NOT_CONFIGURED",
            "Research authentication configuration is invalid.",
            503,
        )
    if not principals:
        fail("AUTH_NOT_CONFIGURED", "Research access has not been provisioned.", 503)
    token = (
        credentials.credentials
        if credentials and credentials.scheme.lower() == "bearer"
        else ""
    )
    hashed = hashlib.sha256(token.encode()).hexdigest()
    for item in principals:
        if token and hmac.compare_digest(hashed, item["token_sha256"]):
            if item.get("expires_at") and datetime.fromisoformat(
                item["expires_at"].replace("Z", "+00:00")
            ) <= datetime.now(timezone.utc):
                fail(
                    "SESSION_EXPIRED",
                    "Your study session expired. Ask the study administrator for renewed access.",
                    401,
                )
            request.state.research_actor = item["actor"]
            return item
    fail("FORBIDDEN", "Research session is missing or invalid.", 401)


Principal = Annotated[dict, Depends(principal)]


def audit_access(request, status):
    path = request.url.path
    if (
        not path.startswith("/api/v3/")
        or path in {"/api/v3/health", "/api/v3/research", "/api/v3/demo/npm"}
        or path.endswith("/health")
    ):
        return
    service().store.append_audit(
        {
            "event_type": "V3_API_ACCESS",
            "action": "V3_API_ACCESS",
            "object_type": "research_api",
            "object_id": path,
            "actor": getattr(request.state, "research_actor", "unauthenticated"),
            "method": request.method,
            "status_code": status,
            "timestamp": now(),
            "result": "success" if status < 400 else "denied_or_failed",
        }
    )


def permit(user, permission):
    roles = {
        "researcher": {"read", "clinical", "npm", "ipm"},
        "optical_engineer": {"read", "optimizer"},
        "manufacturing_engineer": {"read", "manufacture"},
        "adaptive_researcher": {"read", "adaptive"},
        "validator": {"read", "validate"},
        "design_approver": {"read", "approve"},
        "deployer": {"read", "deploy"},
        "admin": {"*"},
        "clinical_admin": {"read", "clinical", "approve"},
    }
    if not any(
        permission in roles.get(r, set()) or "*" in roles.get(r, set())
        for r in user["roles"]
    ):
        fail(
            "FORBIDDEN", "This session is not authorized for the requested action.", 403
        )


def scope(user, patient_id):
    # Wildcards are intentionally unsupported, including for administrators.
    if patient_id not in user["patient_ids"]:
        fail("FORBIDDEN", "Patient is outside this research session.", 403)


def record_scope(user, record):
    if "members" in record:
        for item in record["members"]:
            scope(user, item["patient_id"])
    else:
        scope(user, record["patient_id"])


def require_feature(name):
    if not enabled(name):
        fail("FEATURE_DISABLED", "This research service is disabled.", 503)


def mutate(request, user, inp, key, action, status=200, response_contract=None):
    if not key or not 8 <= len(key) <= 160:
        fail(
            "IDEMPOTENCY_KEY_REQUIRED", "Supply an Idempotency-Key of 8–160 characters."
        )
    identifier = digest({"actor": user["actor"], "path": request.url.path, "key": key})
    fingerprint = digest(inp.model_dump(mode="json"))
    operations = Operations(nso.REGISTRY._store_impl)
    executing = False
    try:
        with service().store.transaction():
            previous = operations.reserve(identifier, fingerprint)
            if previous:
                return JSONResponse(
                    previous[1],
                    status_code=previous[0],
                    headers={"Idempotent-Replay": "true", "Cache-Control": "no-store"},
                )
            executing = True
            payload = action()
            if response_contract is not None:
                payload = response_contract.model_validate(payload).model_dump(
                    mode="json"
                )
            operations.finish(identifier, fingerprint, status, payload)
        return JSONResponse(
            payload, status_code=status, headers={"Cache-Control": "no-store"}
        )
    except ResearchError as exc:
        if not executing:
            fail(exc.code, exc.message, exc.status)
        payload = {"detail": {"code": exc.code, "message": exc.message}}
        with service().store.transaction():
            previous = operations.reserve(identifier, fingerprint)
            if previous:
                return JSONResponse(previous[1], status_code=previous[0])
            operations.finish(identifier, fingerprint, exc.status, payload)
        return JSONResponse(
            payload, status_code=exc.status, headers={"Cache-Control": "no-store"}
        )


def get_record(domain, key):
    try:
        return service().get(domain, key)
    except ResearchError as exc:
        fail(exc.code, exc.message, exc.status)


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": SCHEMA_VERSION,
        "clinical_use_allowed": False,
        "features": {
            "npm_enabled": enabled("npm"),
            "ipm_research_enabled": enabled("ipm_research"),
            "optimizer_enabled": enabled("optimizer"),
            "adaptive_ranking_enabled": False,
            "adaptive_shadow_enabled": enabled("adaptive_ranking"),
            "manufacturing_enabled": enabled("manufacturing"),
        },
        "services": {
            "npm": "population_training_and_baselines",
            "ipm": "protocol_gated_arm_analysis",
            "optimizer": "reference_simulator_requires_measured_calibration",
            "adaptive_ranking": "governed_shadow_only",
        },
    }


@router.get("/research")
def research_info():
    return {
        "version": SCHEMA_VERSION,
        "reference": {
            "title": "AI-guided personalized predictions on myopia progression and interventions",
            "authors": "Liu S et al.",
            "journal": "npj Digital Medicine",
            "year": 2026,
            "doi": "10.1038/s41746-025-02308-4",
            "url": "https://www.nature.com/articles/s41746-025-02308-4",
        },
        "models": [
            {
                "model_id": k,
                **v,
                "status": "research_only",
                "intervals_available": False,
            }
            for k, v in MODELS.items()
        ],
        "limitations": [
            "Independent NSO research implementation; the published model and its performance have not been reproduced.",
            "Individual clinical treatment effects are unvalidated; V3.1 ordering is governed shadow-only research.",
            "Optical optimization requires a calibrated simulator and approved process envelope.",
        ],
    }


@router.get("/npm/health")
def npm_health():
    return {
        "service": "npm",
        "enabled": enabled("npm"),
        "state": "population_training_available",
        "version": SCHEMA_VERSION,
    }


@router.get("/ipm/health")
def ipm_health():
    return {
        "service": "ipm",
        "enabled": enabled("ipm_research"),
        "state": "protocol_gated_analysis_available",
        "version": SCHEMA_VERSION,
    }


@router.get("/optimizer/health")
def optimizer_health():
    return {
        "service": "optimizer",
        "enabled": enabled("optimizer"),
        "state": "reference_simulator_uncalibrated",
        "version": SCHEMA_VERSION,
    }


@router.get("/cases")
def cases(user: Principal):
    permit(user, "read")
    return {
        "cases": [
            {k: r[k] for k in ("case_id", "patient_id", "site_id")}
            for r in service().store.list_records("case")
            if r["patient_id"] in user["patient_ids"]
        ]
    }


@router.get("/session")
def session_details(user: Principal):
    permit(user, "read")
    return {
        "actor": user["actor"],
        "roles": user["roles"],
        "assigned_patients": len(user["patient_ids"]),
        "expires_at": user.get("expires_at"),
        "clinical_use_allowed": False,
    }


@router.get("/cases/{case_id}/observations")
def observations(case_id: str, eye: str, user: Principal):
    from nso.research_contracts import PatientScope

    permit(user, "read")
    try:
        case = service().store.get_record("case", case_id)
    except KeyError:
        fail("NOT_FOUND", "Case unavailable.", 404)
    scope(user, case["patient_id"])
    if eye not in {"OD", "OS"}:
        fail("INVALID_EYE", "Eye must be OD or OS.")
    try:
        return {
            "observations": service().observations(
                PatientScope(patient_id=case["patient_id"], case_id=case_id, eye=eye)
            )
        }
    except ResearchError as exc:
        fail(exc.code, exc.message, exc.status)


@router.post("/observations")
def ingest(
    inp: ObservationBatch,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "clinical")
    scope(user, inp.patient_id)
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().ingest(inp, user["actor"]),
        201,
    )


@router.post("/exposures")
def exposure(
    inp: Exposure,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "clinical")
    scope(user, inp.patient_id)
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().exposure(inp, user["actor"]),
        201,
    )


@router.post("/npm/predict", response_model=ForecastResult)
def predict(
    inp: Forecast,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "npm")
    scope(user, inp.patient_id)
    require_feature("npm")
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().forecast(inp, user["actor"]),
        response_contract=ForecastResult,
    )


@router.post("/outcomes/evaluate")
def evaluate(
    inp: Outcome,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "clinical")
    record_scope(user, get_record("prediction", inp.prediction_id))
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().evaluate(inp, user["actor"]),
    )


@router.post("/ipm/cohorts")
def cohort(
    inp: Cohort,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "ipm")
    require_feature("ipm_research")
    for member in inp.members:
        scope(user, member.patient_id)
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().freeze_cohort(inp, user["actor"]),
        201,
    )


@router.post("/ipm/estimate")
def estimate(
    inp: Estimate,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "ipm")
    require_feature("ipm_research")
    record_scope(user, get_record("cohort", inp.cohort_id))
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().estimate(inp.cohort_id, user["actor"]),
    )


@router.post("/optimizer/run", status_code=202, response_model=OptimizationQueued)
def optimizer(
    inp: Optimization,
    request: Request,
    background: BackgroundTasks,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "optimizer")
    scope(user, inp.patient_id)
    require_feature("optimizer")

    def submit():
        job = service().submit_optimizer(inp, user["actor"])
        background.add_task(
            service().execute_optimizer, job["record_id"], user["actor"]
        )
        return {
            "run_id": job["record_id"],
            "status": "queued",
            "clinical_use_allowed": False,
        }

    return mutate(request, user, inp, idempotency_key, submit, 202, OptimizationQueued)


@router.get("/optimizer/{run_id}", response_model=OptimizationState)
def optimizer_result(run_id: str, user: Principal):
    permit(user, "read")
    require_feature("optimizer")
    record_scope(user, get_record("optimization", run_id))
    return service().optimizer_status(run_id)


@router.post("/designs/approve")
def approve(
    inp: DesignApproval,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "approve")
    require_feature("optimizer")
    record_scope(user, get_record("optimization", inp.run_id))
    try:
        candidate = service().get("optical_candidate", inp.design_id)
    except ResearchError:
        fail(
            "UNVALIDATED_MODEL", "No eligible V3 design is available for approval.", 409
        )
    if candidate["run_id"] != inp.run_id:
        fail("FORBIDDEN", "Candidate does not belong to this optimization run.", 403)
    from nso.research_release import Review, review

    try:
        entry = Review(
            target_kind="design",
            target_id=inp.design_id,
            decision="approve",
            reason=inp.reason,
        )
    except ValueError:
        fail(
            "APPROVAL_REASON_REQUIRED",
            "Provide an approval rationale of at least 20 characters.",
        )
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: review(service(), entry, user["actor"]),
    )


@router.post("/models/validate")
def validate(
    inp: Validation,
    request: Request,
    user: Principal,
    idempotency_key: Annotated[str, Header()] = "",
):
    permit(user, "validate")
    require_feature("npm")
    for sample in inp.samples:
        scope(user, sample.patient_id)
    return mutate(
        request,
        user,
        inp,
        idempotency_key,
        lambda: service().validate(inp, user["actor"]),
    )


@router.get("/cases/{case_id}/trace")
def trace(case_id: str, user: Principal):
    permit(user, "read")
    try:
        case = service().store.get_record("case", case_id)
    except KeyError:
        fail("NOT_FOUND", "Case unavailable.", 404)
    scope(user, case["patient_id"])
    data = nso.ClinicalDigitalThread(service().store).trace_case(case_id)
    # Responses are explicit projections: frozen raw histories stay server-side.
    domains = (
        "observation",
        "observation_correction",
        "exposure",
        "prediction",
        "outcome",
        "optimization",
        "enrollment",
        "study_event",
        "event_resolution",
    )
    data["research"] = {
        domain: [
            {k: v for k, v in r.items() if k != "history_snapshot"}
            for r in service().store.list_records("v3_" + domain)
            if r.get("case_id") == case_id
        ]
        for domain in domains
    }
    model_ids = {r["model_registry_id"] for r in data["research"]["prediction"]}
    data["research"]["models"] = [
        {
            k: r[k]
            for k in (
                "model_id",
                "artifact_hash",
                "initial_status",
                "deployment_context",
            )
        }
        for r in service().store.list_records("model")
        if r["model_id"] in model_ids
    ]
    data["research"]["validations"] = []
    for report in service().store.list_records("v3_validation"):
        if report["model_registry_id"] not in model_ids:
            continue
        dataset = service().get("benchmark_dataset", report["dataset_id"])
        if all(s["patient_id"] in user["patient_ids"] for s in dataset["samples"]):
            data["research"]["validations"].append(report)
    objects = {r["record_id"] for domain in domains for r in data["research"][domain]}
    data["research"]["audit_events"] = [
        e for e in service().store.audits() if e.get("object_id") in objects
    ]
    from nso.research_manufacturing import trace as manufacturing_trace

    data["research"]["manufacturing"] = manufacturing_trace(service(), case_id)
    data["research"]["adaptive_shadows"] = [
        {
            k: r[k]
            for k in (
                "record_id",
                "model_id",
                "index_date",
                "status",
                "clinical_use_allowed",
            )
        }
        for r in service().store.list_records("v3_adaptive_shadow")
        if r["case_id"] == case_id
    ]
    return data


@router.post("/demo/npm")
def demo(inp: dict):
    """A fixed synthetic fixture; accepts only eye/model/horizon, never patient data."""
    from nso.manufacturing.store import InMemoryDesignStore
    from nso.research_contracts import PatientScope

    if set(inp) - {"eye", "model_id", "horizons_months"}:
        fail("INVALID_DEMO_INPUT", "Demo accepts controls only.")
    try:
        forecast = Forecast(
            patient_id="SYNTHETIC-DEMO",
            case_id="SYNTHETIC-CASE",
            index_date="2026-01-01",
            untreated_history_confirmed=True,
            eye=inp.get("eye", "OD"),
            model_id=inp.get("model_id", "npm-history-linear-v1"),
            horizons_months=inp.get("horizons_months", [6, 12, 24]),
        )
    except ValueError:
        fail("INVALID_DEMO_INPUT", "Invalid demo controls.")
    if forecast.model_id not in MODELS:
        fail("INVALID_DEMO_INPUT", "Unknown demo baseline.")
    store = InMemoryDesignStore()
    nso.ClinicalDigitalThread(store).create_case(
        patient_id=forecast.patient_id,
        case_id=forecast.case_id,
        indication_code="SYNTHETIC",
        site_id="DEMO",
        clinician_id="DEMO",
    )
    svc = ResearchService(store)
    fixture = [
        Observation(
            visit_at=d,
            se_d=s,
            al_mm=a,
            se_status="measured",
            al_status="measured",
            measurement_method="synthetic fixture",
            source="synthetic_not_patient_data",
        )
        for d, s, a in [
            ("2025-01-01", -2, 24),
            ("2025-07-01", -2.15, 24.08),
            ("2026-01-01", -2.3, 24.16),
        ]
    ]
    if forecast.eye == "OS":
        fixture = [
            r.model_copy(update={"se_d": r.se_d + 0.25, "al_mm": r.al_mm - 0.1})
            for r in fixture
        ]
    svc.ingest(
        ObservationBatch(
            **{k: getattr(forecast, k) for k in PatientScope.model_fields},
            observations=fixture,
        ),
        "demo",
    )
    result = svc.forecast(forecast, "demo")
    # Demo IDs are intentionally not persisted and cannot be used by protected endpoints.
    return {
        **result,
        "synthetic": True,
        "persisted": False,
        "observations": [r.model_dump(mode="json") for r in fixture],
    }
