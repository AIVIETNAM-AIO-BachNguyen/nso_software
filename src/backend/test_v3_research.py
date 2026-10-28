"""Research safety, real-date arithmetic, scoped access and persistence acceptance."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
import nso
from nso.manufacturing.store import InMemoryDesignStore, SQLiteDesignStore
from nso.research import ResearchError, ResearchService, baseline_forecast, months_after
from nso.research_contracts import (Cohort, Exposure, Forecast, Observation, ObservationBatch,
                                    Outcome, PatientScope, Validation)
from nso.research_operations import Operations


def observation(day="2026-01-01", al=24.2, se=-2.3, **kw):
    return Observation(visit_at=day, al_mm=al, se_d=se,
        al_status="missing" if al is None else "measured", se_status="missing" if se is None else "measured",
        measurement_method="test optical biometry", source="synthetic_fixture", **kw)


def identity(patient="P1", case="C1", eye="OD"):
    return dict(patient_id=patient, case_id=case, eye=eye)


def add_case(store, patient="P1", case="C1"):
    nso.ClinicalDigitalThread(store).create_case(patient_id=patient, case_id=case,
        site_id="SITE", indication_code="RESEARCH", clinician_id="TEST")


def seed(svc, patient="P1", case="C1", eye="OD"):
    add_case(svc.store, patient, case)
    svc.ingest(ObservationBatch(**identity(patient, case, eye), observations=[
        observation("2025-01-01", 24, -2), observation("2026-01-01", 24.2, -2.3)]), "test")


@pytest.fixture
def svc():
    service = ResearchService(InMemoryDesignStore())
    seed(service)
    return service


@pytest.fixture
def client(monkeypatch, svc):
    registry = nso.DesignRegistry(svc.store)
    monkeypatch.setattr(nso, "REGISTRY", registry)
    # api.v2 and research_api.nso are the same package, and see the same registry.
    users = [dict(actor="researcher", token_sha256=hashlib.sha256(b"test-token").hexdigest(),
                  roles=["researcher", "optical_engineer", "validator", "design_approver"], patient_ids=["P1", "P2", "P3"]),
             dict(actor="outsider", token_sha256=hashlib.sha256(b"other-token").hexdigest(), roles=["researcher"], patient_ids=["P2"])]
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(users))
    for name in ("NPM", "IPM_RESEARCH", "OPTIMIZER"):
        monkeypatch.setenv(f"NSO_V3_{name}_ENABLED", "true")
    with TestClient(api.app) as c:
        yield c


def headers(key="test-request-001", token="test-token"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def predict_body(**kw):
    return {**identity(), "index_date": "2026-01-01", "untreated_history_confirmed": True, **kw}


def test_calendar_months_use_real_dates_and_leap_day():
    assert months_after(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert months_after(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_forecast_is_measured_per_eye_and_null_intervals(svc):
    result = svc.forecast(Forecast(**predict_body()), "test")
    assert result["status"] == "research_only"
    assert result["clinical_use_allowed"] is False
    annual = result["forecasts"][1]
    assert annual["al_mm"] == pytest.approx(24.4)
    assert annual["se_d"] == pytest.approx(-2.6)
    assert annual["elapsed_days"] == 365
    assert annual["al_interval"] is None
    assert "history_snapshot" not in result
    with pytest.raises(ResearchError, match="No pre-index"):
        svc.forecast(Forecast(**predict_body(eye="OS")), "test")


def test_missing_al_does_not_get_synthetic_estimate(svc):
    seed(svc, "P2", "C2")
    scope = identity("P3", "C3")
    add_case(svc.store, "P3", "C3")
    svc.ingest(ObservationBatch(**scope, observations=[observation("2025-01-01", None), observation("2026-01-01", None)]), "test")
    result = svc.forecast(Forecast(**{**predict_body(), **scope}), "test")
    assert all(f["al_mm"] is None and "INSUFFICIENT_HISTORY_AL" in f["applicability_flags"] for f in result["forecasts"])


def test_imputed_and_rejected_observations_are_not_primary_data():
    measured = observation("2025-01-01", 24)
    imputed = observation("2026-01-01", 26).model_copy(update={"al_status": "imputed"})
    result = baseline_forecast([measured, imputed], date(2026, 1, 1), date(2027, 1, 1), "npm-history-linear-v1")
    assert result["al_mm"] is None
    assert result["se_d"] is not None
    rejected = observation("2026-01-01", 26, quality_flag="REJECTED")
    assert baseline_forecast([measured, rejected], date(2026, 1, 1), date(2027, 1, 1), "npm-history-linear-v1")["al_mm"] is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 100])
def test_invalid_values_rejected(bad):
    with pytest.raises(ValidationError): observation(al=bad)


def test_provenance_and_extra_fields_strict():
    with pytest.raises(ValidationError): observation().model_validate({**observation().model_dump(), "al_status": "missing"})
    with pytest.raises(ValidationError): Observation(**{**observation().model_dump(), "hidden_recipe": {}})


def test_duplicate_batch_has_no_partial_writes(svc):
    before = len(svc.store.list_records("v3_observation"))
    with pytest.raises(ResearchError, match="duplicate"):
        svc.ingest(ObservationBatch(**identity(), observations=[observation("2025-03-01"), observation("2025-03-01")]), "test")
    assert len(svc.store.list_records("v3_observation")) == before


def test_changing_existing_date_is_rejected(svc):
    with pytest.raises(ResearchError, match="already exists"):
        svc.ingest(ObservationBatch(**identity(), observations=[observation("2026-01-01", 25)]), "test")


def test_post_index_input_rejected_but_saved_future_excluded(svc):
    with pytest.raises(ResearchError, match="post-index"):
        baseline_forecast([observation("2027-01-01")], date(2026, 1, 1), date(2027, 1, 1), "npm-carry-forward-v1")
    first = svc.forecast(Forecast(**predict_body()), "test")
    svc.ingest(ObservationBatch(**identity(), observations=[observation("2027-01-01", 27)]), "test")
    second = svc.forecast(Forecast(**predict_body()), "test")
    assert first["dataset_hash"] == second["dataset_hash"]
    assert first["forecasts"] == second["forecasts"]


def test_npm_requires_untreated_attestation_and_checks_exposures(svc):
    with pytest.raises(ResearchError, match="untreated"):
        svc.forecast(Forecast(**predict_body(untreated_history_confirmed=False)), "test")
    svc.exposure(Exposure(**identity(), arm="SA_ONLY", start_at="2025-06-01"), "test")
    with pytest.raises(ResearchError, match="untreated"):
        svc.forecast(Forecast(**predict_body()), "test")


def test_exposures_do_not_overlap_or_cross_patients(svc):
    svc.exposure(Exposure(**identity(), arm="NONE", start_at="2025-01-01", end_at="2025-12-31"), "test")
    with pytest.raises(ResearchError, match="overlap"):
        svc.exposure(Exposure(**identity(), arm="SA_ONLY", start_at="2025-05-01"), "test")
    with pytest.raises(ResearchError, match="do not match"):
        svc.exposure(Exposure(**identity("P2"), arm="NONE", start_at="2025-01-01"), "test")


def test_outcome_actual_elapsed_days_and_measured_only(svc):
    result = svc.forecast(Forecast(**predict_body()), "test")
    outcome = svc.evaluate(Outcome(prediction_id=result["prediction_id"], observation=observation("2026-07-01", 24.3)), "test")
    assert outcome["elapsed_days"] == 181
    assert outcome["metrics"]["al"]["annualized_change"] == pytest.approx(.1 * 365.25 / 181)
    assert outcome["metrics"]["al"]["predicted_at_observed_date"] == pytest.approx(24.2 + .2 * 181 / 365, abs=1e-6)
    imputed = observation("2026-07-01", 24.3).model_copy(update={"al_status": "imputed"})
    excluded = svc.evaluate(Outcome(prediction_id=result["prediction_id"], observation=imputed), "test")
    assert excluded["metrics"]["al"]["observed"] is None
    assert excluded["metrics"]["al"]["residual_observed_minus_predicted"] is None
    with pytest.raises(ResearchError, match="after"):
        svc.evaluate(Outcome(prediction_id=result["prediction_id"], observation=observation()), "test")


def cohort_input(members=None, **kw):
    return Cohort(cohort_name="Test", eligibility_version="protocol-1", assignment="randomized",
                  comparator="NONE", intervention="SA_ONLY", index_date="2026-01-01",
                  analysis_plan="Prespecified descriptive AL endpoint", members=members or [identity(), identity("P2", "C2")], **kw)


def cohort_seed(svc):
    seed(svc, "P2", "C2")
    for scope, arm, value in [(identity(), "NONE", 24.5), (identity("P2", "C2"), "SA_ONLY", 24.3)]:
        svc.ingest(ObservationBatch(**scope, observations=[observation("2027-01-01", value)]), "test")
        svc.exposure(Exposure(**scope, arm=arm, start_at="2026-01-01", adherence=.8), "test")


def test_cohort_freezes_endpoints_and_never_emits_ite(svc):
    cohort_seed(svc)
    frozen = svc.freeze_cohort(cohort_input(), "test")
    report = svc.estimate(frozen["cohort_id"], "test")
    assert frozen["eligible_eyes"] == 2
    assert report["groups"][0]["mean_observed_delta_al_mm"] == pytest.approx(.3)
    assert report["groups"][1]["mean_observed_delta_al_mm"] == pytest.approx(.1)
    assert report["ite"] is report["cate"] is report["causal_effect"] is None
    assert report["readiness"]["assignment_verified"] is False
    # A later store addition does not modify a frozen dataset or its report.
    svc.ingest(ObservationBatch(**identity(), observations=[observation("2027-01-02", 25)]), "test")
    assert svc.estimate(frozen["cohort_id"], "test")["dataset_hash"] == frozen["dataset_hash"]


def test_patient_eyes_are_not_independent_samples(svc):
    cohort_seed(svc)
    seed(svc, "P1", "C1-OS", "OS")
    svc.ingest(ObservationBatch(**identity("P1", "C1-OS", "OS"), observations=[observation("2027-01-01", 24.7)]), "test")
    svc.exposure(Exposure(**identity("P1", "C1-OS", "OS"), arm="NONE", start_at="2026-01-01"), "test")
    frozen = svc.freeze_cohort(cohort_input(members=[identity(), identity("P1", "C1-OS", "OS"), identity("P2", "C2")]), "test")
    report = svc.estimate(frozen["cohort_id"], "test")
    group = report["groups"][0]
    assert group["eyes"] == 2 and group["patients"] == 1
    assert group["mean_observed_delta_al_mm"] == pytest.approx(.4)


def test_switching_and_missing_followup_explicit(svc):
    cohort_seed(svc)
    # P1 baseline exposure is already open, so use discontinuation on P2 instead.
    seed(svc, "P3", "C3")
    svc.exposure(Exposure(**identity("P3", "C3"), arm="SA_ONLY", start_at="2026-01-01", end_at="2026-06-01"), "test")
    frozen = svc.freeze_cohort(cohort_input(members=[identity(), identity("P3", "C3")]), "test")
    report = svc.estimate(frozen["cohort_id"], "test")
    assert report["excluded_eyes"] == 1
    assert report["exclusion_reasons"]["MISSING_MEASURED_FOLLOWUP_AL"] == 1
    assert report["exclusion_reasons"]["DISCONTINUED_BEFORE_ENDPOINT"] == 1


def test_auth_fails_closed_and_roles_cannot_be_spoofed(client, monkeypatch):
    assert client.get("/api/v3/cases").status_code == 401
    assert client.get("/api/v3/cases", headers={"X-NSO-Role": "admin"}).status_code == 401
    monkeypatch.setenv("NSO_V3_PRINCIPALS", "[]")
    assert client.get("/api/v3/cases", headers=headers()).status_code == 503


def test_feature_flags_and_adaptive_ranking_fail_closed(client, monkeypatch):
    monkeypatch.setenv("NSO_V3_NPM_ENABLED", "false")
    result = client.post("/api/v3/npm/predict", headers=headers(), json=predict_body())
    assert result.status_code == 503 and result.json()["detail"]["code"] == "FEATURE_DISABLED"
    monkeypatch.setenv("NSO_V3_ADAPTIVE_RANKING_ENABLED", "true")
    assert client.get("/api/v3/health").json()["features"]["adaptive_ranking_enabled"] is False


def test_scope_applies_to_predictions_outcomes_trace_and_cases(client):
    assert client.post("/api/v3/npm/predict", json=predict_body(), headers=headers(token="other-token")).status_code == 403
    result = client.post("/api/v3/npm/predict", json=predict_body(), headers=headers()).json()
    assert client.post("/api/v3/outcomes/evaluate", headers=headers(token="other-token"), json={
        "prediction_id": result["prediction_id"], "observation": observation("2027-01-01").model_dump(mode="json")}).status_code == 403
    assert client.get("/api/v3/cases/C1/trace", headers=headers(token="other-token")).status_code == 403
    assert client.get("/api/v3/cases", headers=headers(token="other-token")).json()["cases"] == []


def test_request_receipt_replays_without_duplicate_prediction(client, svc):
    first = client.post("/api/v3/npm/predict", json=predict_body(), headers=headers())
    second = client.post("/api/v3/npm/predict", json=predict_body(), headers=headers())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["idempotent-replay"] == "true"
    assert len(svc.store.list_records("v3_prediction")) == 1
    conflict = client.post("/api/v3/npm/predict", json=predict_body(model_id="npm-carry-forward-v1"), headers=headers())
    assert conflict.status_code == 409
    assert client.post("/api/v3/npm/predict", json=predict_body(), headers={"Authorization": "Bearer test-token"}).status_code == 422


def test_public_demo_never_persists_or_accepts_patient_payload(client, svc):
    first = client.post("/api/v3/demo/npm", json={"eye": "OD"}).json()
    second = client.post("/api/v3/demo/npm", json={"eye": "OS"}).json()
    assert first["synthetic"] is True and first["persisted"] is False
    assert second["forecasts"][0]["al_mm"] != first["forecasts"][0]["al_mm"]
    assert svc.store.list_records("v3_prediction") == []
    assert client.post("/api/v3/demo/npm", json={"patient_id": "P1"}).status_code == 422
    assert client.post("/api/v3/demo/npm", json={"model_id": "published-transformer"}).status_code == 422
    replay = client.post("/api/v3/demo/npm", json={"eye": "OD"}).json()
    assert replay["dataset_hash"] == first["dataset_hash"]


def test_optimizer_async_blocked_and_approval_cannot_be_forged(client):
    result = client.post("/api/v3/optimizer/run", headers=headers(), json={**identity(), "envelope_id": "process-1"})
    assert result.status_code == 202
    run = client.get("/api/v3/optimizer/" + result.json()["run_id"], headers=headers()).json()
    assert run["status"] == "blocked" and run["code"] == "ENVELOPE_NOT_REGISTERED"
    assert run["pareto_candidates"] == [] and run["optical_metrics"] is None
    assert client.post("/api/v3/designs/approve", headers=headers(), json={"run_id": run["run_id"],
        "design_id": "FAKE", "reason": "Attempted invalid approval"}).status_code == 409


def benchmark_samples():
    return [{**identity(f"P{i}", f"C{i}"), "split": split, "site_id": "S" + str(i),
             "index_date": f"202{3+i}-01-01", "untreated_history_confirmed": True,
             "history": [observation(f"202{2+i}-01-01", 24).model_dump(mode="json"),
                         observation(f"202{3+i}-01-01", 24.2).model_dump(mode="json")],
             "observed": observation(f"202{4+i}-01-01", 24.4).model_dump(mode="json")}
            for i, split in enumerate(["train", "validation", "test"], 1)]


def test_benchmark_patient_disjoint_and_no_self_approval(svc):
    for i in (2, 3): add_case(svc.store, f"P{i}", f"C{i}")
    inp = Validation(dataset_version="synthetic-1", model_id="npm-history-linear-v1", split_strategy="patient", samples=benchmark_samples())
    result = svc.validate(inp, "test")
    assert result["validated_for_clinical_use"] is False
    assert result["approval"] is None
    assert result["metrics"]["test"]["al"]["mae"] < .001
    bad = inp.model_copy(deep=True)
    bad.samples[2].patient_id, bad.samples[2].case_id = "P1", "C1"
    with pytest.raises(ResearchError, match="multiple splits"):
        svc.validate(bad, "test")


def test_external_site_and_temporal_leakage_detected(svc):
    for i in (2, 3): add_case(svc.store, f"P{i}", f"C{i}")
    inp = Validation(dataset_version="synthetic-1", model_id="npm-history-linear-v1", split_strategy="external_site", samples=benchmark_samples())
    with pytest.raises(ResearchError, match="External"):
        svc.validate(inp, "test")
    inp.split_strategy = "temporal"
    inp.samples[0].index_date = inp.samples[1].index_date
    inp.samples[0].observed = observation("2026-01-02", 24.4)
    with pytest.raises(ResearchError, match="Temporal"):
        svc.validate(inp, "test")


def test_reuses_v2_measurements_with_strict_provenance(svc):
    thread = nso.ClinicalDigitalThread(svc.store)
    thread.record_visit(case_id="C1", visit_code="F1", visit_type="followup", visit_date="2026-02-01",
        clinician_id="TEST", site_id="SITE", measurements=[
            {"measurement_type": "axial_length", "laterality": "OS", "value": 24.1, "source": "objective"},
            {"measurement_type": "spherical_equivalent", "laterality": "OS", "value": -2, "source": "imputed"}])
    rows = svc.observations(PatientScope(**identity(eye="OS")))
    assert len(rows) == 1 and rows[0]["al_status"] == "measured"
    assert rows[0]["se_d"] is None


def test_sqlite_reopen_preserves_v2_and_research_trace(tmp_path):
    path = tmp_path / "v2-and-v3.db"
    store = SQLiteDesignStore(path)
    service = ResearchService(store)
    seed(service)
    run = service.forecast(Forecast(**predict_body()), "test")
    reopened = ResearchService(SQLiteDesignStore(path))
    assert reopened.store.get_record("case", "C1")["patient_id"] == "P1"
    assert reopened.get("prediction", run["prediction_id"])["dataset_hash"] == run["dataset_hash"]
    assert any(e["object_id"] == run["prediction_id"] for e in reopened.store.audits())


@pytest.mark.parametrize("sql", [False, True])
def test_idempotency_reservation_atomic_and_persistent(tmp_path, sql):
    store = SQLiteDesignStore(tmp_path / "receipt.db") if sql else InMemoryDesignStore()
    def reserve(_):
        try: return Operations(store).reserve("same", "hash")
        except ResearchError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert results.count(None) == 1
    assert results.count("OPERATION_PENDING") == 3
    Operations(store).finish("same", "hash", 200, {"ok": True})
    if sql: store = SQLiteDesignStore(tmp_path / "receipt.db")
    assert Operations(store).reserve("same", "hash") == (200, {"ok": True})


def test_clinical_payload_has_no_optimizer_parameters(client):
    result = client.post("/api/v3/npm/predict", json=predict_body(), headers=headers()).json()
    nso.assert_no_design_leak(result)
    assert "history_snapshot" not in json.dumps(result)


def test_openapi_contains_v3_contracts(client):
    schema = client.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.1")
    for route in ("npm/predict", "ipm/estimate", "optimizer/run", "outcomes/evaluate", "models/validate"):
        assert "/api/v3/" + route in schema["paths"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]


def test_standalone_services_exclude_legacy_and_other_service_routes():
    from research_app import create_app
    for name, required, excluded in [("npm", "/api/v3/npm/predict", "/api/v3/ipm/estimate"),
                                      ("ipm", "/api/v3/ipm/estimate", "/api/v3/optimizer/run"),
                                      ("optimizer", "/api/v3/optimizer/run", "/api/v3/npm/predict")]:
        app = create_app(name)
        paths = app.openapi()["paths"]
        assert required in paths and excluded not in paths
        assert "/api/predict" not in paths
        with TestClient(app) as c:
            assert c.get("/api/v3/health").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("sql", [True, False])
def test_atomic_batch_rolls_back_if_later_record_conflicts(tmp_path, sql):
    store = SQLiteDesignStore(tmp_path / "batch.db") if sql else InMemoryDesignStore()
    store.put_record("v3_observation", "existing", {"v": 1})
    with pytest.raises(ValueError, match="conflicts"):
        store.put_records_atomic([("v3_observation", "new", {"v": 2}), ("v3_observation", "existing", {"v": 3})])
    with pytest.raises(KeyError): store.get_record("v3_observation", "new")
    assert store.get_record("v3_observation", "existing") == {"v": 1}


def test_explicit_treatment_switch_excluded(svc):
    seed(svc, "P2", "C2")
    for patient, case in [("P1", "C1"), ("P2", "C2")]:
        svc.ingest(ObservationBatch(**identity(patient, case), observations=[observation("2027-01-01", 24.4)]), "test")
    svc.exposure(Exposure(**identity(), arm="NONE", start_at="2026-01-01"), "test")
    svc.exposure(Exposure(**identity("P2", "C2"), arm="SA_ONLY", start_at="2026-01-01", end_at="2026-06-01"), "test")
    svc.exposure(Exposure(**identity("P2", "C2"), arm="SA_BN", start_at="2026-06-02"), "test")
    frozen = svc.freeze_cohort(cohort_input(), "test")
    report = svc.estimate(frozen["cohort_id"], "test")
    assert report["exclusion_reasons"]["TREATMENT_SWITCH_OR_RESTART"] == 1


def test_npm_checks_legacy_and_other_case_treatment(svc):
    thread = nso.ClinicalDigitalThread(svc.store)
    eyes = thread.ensure_eyes("P1")
    # Only the eye/date identity is needed to test the legacy read adapter.
    svc.store.put_record("product_exposure", "LEGACY", {"eye_id": eyes["OD"], "case_id": "OTHER-CASE",
        "exposure_start": "2025-06-01", "exposure_end": None})
    with pytest.raises(ResearchError, match="untreated"):
        svc.forecast(Forecast(**predict_body()), "test")


def test_registry_hash_and_trace_linked_without_promoting(client, svc):
    run = client.post("/api/v3/npm/predict", json=predict_body(), headers=headers()).json()
    model = svc.store.get_record("model", run["model_registry_id"])
    assert model["initial_status"] == "Development"
    assert model["artifact_hash"] == run["model_artifact_hash"]
    trace = client.get("/api/v3/cases/C1/trace", headers=headers()).json()
    assert trace["research"]["prediction"][0]["record_id"] == run["prediction_id"]
    assert trace["research"]["models"][0]["model_id"] == model["model_id"]


def test_read_and_denied_access_audited_without_credential(client, svc):
    client.get("/api/v3/cases/C1/observations?eye=OD", headers=headers())
    client.get("/api/v3/cases/C1/observations?eye=OD", headers=headers(token="other-token"))
    events = [e for e in svc.store.audits() if e.get("event_type") == "V3_API_ACCESS"]
    assert {e["status_code"] for e in events} == {200, 403}
    assert {e["actor"] for e in events} == {"researcher", "outsider"}
    assert "test-token" not in json.dumps(events)


def test_synthetic_v2_design_lot_qc_and_v3_forecast_outcome_share_case(client, svc, monkeypatch):
    import nso.clinical
    import nso.manufacturing.verification
    registry = nso.DesignRegistry(svc.store)
    monkeypatch.setattr(nso, "REGISTRY", registry)
    monkeypatch.setattr(nso.clinical, "REGISTRY", registry)
    monkeypatch.setattr(nso.manufacturing.verification, "REGISTRY", registry)
    prediction = client.post("/api/predict", json={"patient_id": "P2", "age": 11,
        "od": {"sphere": -2.5, "axial_length": 24.7}, "os": {"sphere": -2.25, "axial_length": 24.6}}).json()
    case_id, design_id = prediction["case_id"], prediction["design_id"]
    initial = nso.ClinicalDigitalThread(svc.store).trace_case(case_id)
    index = date.fromisoformat(initial["visits"][0]["visit_date"])
    prior = months_after(index, -12)
    scope = identity("P2", case_id)
    svc.ingest(ObservationBatch(**scope, observations=[observation(prior.isoformat(), 24.5, -2.2)]), "test")
    result = client.post("/api/v3/npm/predict", headers=headers(), json={**scope,
        "index_date": index.isoformat(), "untreated_history_confirmed": True}).json()
    assert "prediction_id" in result
    client.post("/api/design/approve", json={"design_id": design_id}).raise_for_status()
    lot = client.post("/api/manufacturing/submit", json={"design_id": design_id}).json()
    qc = nso.geometric_verification(design_id, {"sag_error_mm": .001,
        "element_height_error_mm": .0001, "element_position_error_mm": .001, "decentration_mm": .02},
        manufacturing_id=lot["job_id"])
    assert qc["verdict"] == "Pass"
    observed_date = months_after(index, 6)
    followup = client.post("/api/v3/outcomes/evaluate", headers=headers(), json={
        "prediction_id": result["prediction_id"], "observation": observation(observed_date.isoformat(), 24.8, -2.6).model_dump(mode="json")})
    assert followup.status_code == 200
    trace = client.get(f"/api/v3/cases/{case_id}/trace", headers=headers()).json()
    assert trace["case"]["case_id"] == case_id
    assert lot["lot_id"] in {r["lot_id"] for r in trace["manufacturing_lots"]}
    assert trace["qc_measurements"]
    assert trace["research"]["prediction"][0]["record_id"] == result["prediction_id"]
    assert trace["research"]["outcome"][0]["prediction_id"] == result["prediction_id"]


def test_migration_adds_receipts_to_previous_schema_without_changing_v2(tmp_path):
    import sqlite3
    from nso.manufacturing.store import SCHEMA
    path = tmp_path / "old-v2.db"
    with sqlite3.connect(path) as conn:
        for statement in SCHEMA:
            if "v3_operations" not in statement: conn.execute(statement)
        conn.execute("INSERT INTO domain_records VALUES (?, ?, ?, ?)",
                     ("case", "OLD-CASE", '{"case_id":"OLD-CASE","patient_id":"OLD-PATIENT"}', "2026-01-01"))
    store = SQLiteDesignStore(path)
    assert store.get_record("case", "OLD-CASE") == {"case_id": "OLD-CASE", "patient_id": "OLD-PATIENT"}
    assert Operations(store).reserve("new-operation", "fingerprint") is None
