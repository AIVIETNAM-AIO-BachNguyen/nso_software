"""Engineering-completion verification on invented data and isolated stores."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pytest

import nso
from nso.manufacturing.store import (
    InMemoryDesignStore,
    SQLiteDesignStore,
    PostgresDesignStore,
)
from nso.research import ResearchError, digest
from nso.research_advanced import AdvancedResearchService
from nso.research_contracts import Forecast, ObservationBatch, PatientScope
from nso.research_data import Correction, correct
from nso.research_learning import fit, features, predict_delta, validate_partitions
from nso.research_causal import CausalRequest, analyze
from nso.research_optics import (
    Envelope,
    CalibrationRequest,
    CalibrationPoint,
    calibrate,
    centers,
    dominates,
    optimize,
    simulate,
)
from nso.research_release import (
    Deployment,
    ReleasePolicy,
    Review,
    Rollback,
    deploy,
    review,
    rollback,
)
from nso.research_fixtures import (
    learning_request,
    observation,
    optical_envelope,
    seed_learning_cases,
    study,
)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryDesignStore()
    if request.param == "sqlite":
        return SQLiteDesignStore(tmp_path / "test.db")
    dsn = os.getenv("NSO_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("Set NSO_TEST_POSTGRES_URL to run the isolated PostgreSQL checks")
    import psycopg
    from psycopg import sql

    schema = "test_" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    from psycopg.conninfo import make_conninfo

    instance = PostgresDesignStore(
        make_conninfo(dsn, options="-c search_path=" + schema)
    )
    request.addfinalizer(lambda: drop_schema(dsn, schema))
    return instance


def drop_schema(dsn, schema):
    import psycopg
    from psycopg import sql

    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed(svc):
    nso.ClinicalDigitalThread(svc.store).create_case(
        patient_id="P",
        case_id="C",
        site_id="S",
        indication_code="SYNTHETIC",
        clinician_id="TEST",
    )
    return {"patient_id": "P", "case_id": "C", "eye": "OD"}


def test_transaction_rolls_back_record_and_audit_together(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.put_record("test", "row", {"v": 1})
            store.append_audit({"object_id": "row", "actor": "synthetic"})
            raise RuntimeError("simulated crash")
    with pytest.raises(KeyError):
        store.get_record("test", "row")
    assert store.audits("row") == []


def test_correction_preserves_history_and_optimistic_version(store):
    svc = AdvancedResearchService(store)
    scope = seed(svc)
    result = svc.ingest(
        ObservationBatch(**scope, observations=[observation(date(2026, 1, 1), 24, -2)]),
        "author",
    )
    key = result["observation_ids"][0]
    correction = Correction(
        **scope,
        observation_id=key,
        expected_revision=0,
        reason="Correct an invented measurement transcription",
        replacement=observation(date(2026, 1, 1), 24.1, -2),
    )
    correct(svc, correction, "reviewer")
    assert svc.get("observation", key)["al_mm"] == 24
    current = svc.observations(PatientScope(**scope))[0]
    assert current["al_mm"] == 24.1 and current["revision"] == 1
    with pytest.raises(ResearchError, match="Refresh"):
        correct(svc, correction, "reviewer")


def test_concurrent_exposure_imports_cannot_overlap(store):
    from nso.research_contracts import Exposure

    svc = AdvancedResearchService(store)
    scope = seed(svc)

    def add(i):
        try:
            svc.exposure(
                Exposure(
                    **scope, arm="SA_ONLY" if i else "NONE", start_at="2026-01-01"
                ),
                "test",
            )
            return "saved"
        except ResearchError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(add, [0, 1]))
    assert outcomes.count("saved") == 1
    assert outcomes.count("OVERLAPPING_EXPOSURE") == 1


@pytest.fixture(
    scope="module",
    params=["mixed_effects", "gradient_boosting", "temporal_transformer"],
)
def model(request):
    inp = learning_request(request.param)
    return inp, fit(inp, "trainer")


def test_population_models_are_executable_json_and_hold_out_patients(model):
    inp, artifact = model
    artifact = json.loads(json.dumps(artifact, allow_nan=False))
    sample = next(s for s in inp.samples if s.split == "test")
    x, sequence, _ = features(
        sample.history, sample.index_date, sample.observed.visit_at, sample.index_age
    )
    delta = predict_delta(artifact, x, sequence)
    assert np.isfinite(delta).all()
    assert artifact["calibration_patients"] == 12
    assert len(artifact["interval_radius"]) == 2
    assert artifact["report"]["split:test"]["patients"] == 8
    assert artifact["report"]["split:external"]["patients"] == 8
    assert artifact["clinical_use_allowed"] is False
    for metric in artifact["report"].values():
        assert all(0 <= v <= 1 for v in metric["interval_coverage_al_se"])


def test_training_patient_and_site_leakage_rejected():
    inp = learning_request()
    inp.samples[-1].patient_id = inp.samples[0].patient_id
    with pytest.raises(ResearchError, match="one split"):
        validate_partitions(inp.samples)


def test_population_temporal_and_conflicting_visits_rejected():
    inp = learning_request()
    with pytest.raises(ResearchError, match="Earlier endpoints"):
        validate_partitions(inp.samples, "temporal")
    sample = inp.samples[1]
    sample.history[0] = sample.history[0].model_copy(
        update={"al_mm": sample.history[0].al_mm + 0.5}
    )
    with pytest.raises(ResearchError, match="conflicting"):
        validate_partitions(inp.samples)
    inp = learning_request()
    for s in inp.samples:
        if s.split == "external":
            s.site_id = "DEVELOPMENT"
    with pytest.raises(ResearchError, match="External"):
        validate_partitions(inp.samples)


def test_learning_seed_reproduces_numerical_artifact():
    a, b = fit(learning_request(), "trainer"), fit(learning_request(), "trainer")
    assert a["artifact_hash"] == b["artifact_hash"]
    assert a["models"] == b["models"]


@pytest.mark.parametrize(
    "assignment,method",
    [("randomized", "randomized_ancova"), ("observational", "observational_aipw")],
)
def test_adjusted_effects_recover_invented_effect_at_patient_level(assignment, method):
    svc = AdvancedResearchService(InMemoryDesignStore())
    n = 80 if assignment == "observational" else 40
    cohort = study(svc, assignment, n=n)
    result = analyze(
        svc,
        CausalRequest(cohort_id=cohort["cohort_id"], method=method, bootstrap_reps=100),
        "analyst",
    )
    assert result["patients"] == n
    assert result["effect_mm"] == pytest.approx(-0.12, abs=0.04)
    assert (
        result["interval_95_mm"][0]
        <= result["effect_mm"]
        <= result["interval_95_mm"][1]
    )
    assert result["ite"] is None and result["clinical_use_allowed"] is False
    assert result["assignment_independently_verified"] is False


def test_causal_analysis_requires_locked_protocol():
    svc = AdvancedResearchService(InMemoryDesignStore())
    cohort = svc.save("cohort", "COH", {"members": [], "protocol_id": None}, "test")
    with pytest.raises(ResearchError, match="locked protocol"):
        analyze(
            svc,
            CausalRequest(cohort_id=cohort["record_id"], method="observational_aipw"),
            "analyst",
        )


def test_scalar_diffraction_energy_mtf_and_aberration():
    env = optical_envelope()
    env["bounds"]["noise_height_um"][0] = 0
    perfect = {
        "sa_um": 0.0,
        "noise_height_um": 0.0,
        "fiber_height_um": 0.0,
        "fiber_angle_deg": 0.0,
    }
    ideal, psf, otf = simulate(perfect, env, return_psf=True)
    aberrated = simulate({**perfect, "sa_um": 0.08}, env)
    assert ideal["psf_energy"] == pytest.approx(1.0)
    assert ideal["strehl"] == pytest.approx(1.0)
    assert otf[32, 32] == pytest.approx(1.0)
    assert np.all(psf >= 0) and 0 < ideal["mtf_20"] < 1
    analytic_mtf = 2 / np.pi * (np.arccos(0.2) - 0.2 * np.sqrt(1 - 0.2**2))
    assert ideal["mtf_20"] == pytest.approx(analytic_mtf, abs=0.03)
    assert aberrated["strehl"] < ideal["strehl"]


def test_poisson_exclusion_and_grid_resolution():
    env = optical_envelope()
    points = centers(env, 1)
    for i, p in enumerate(points):
        for q in points[i + 1 :]:
            assert np.linalg.norm(p - q) >= env["spacing_um"] / 1000
    env["feature_width_um"] = 10
    with pytest.raises(ValueError):
        Envelope(**env)


def test_optical_search_reproducible_and_pareto_is_nondominated():
    a = optimize(optical_envelope(), 17, 12)
    b = optimize(optical_envelope(), 17, 12)
    assert a == b and a["pareto"]
    for p in a["pareto"]:
        assert all(not dominates(q["costs"], p["costs"]) for q in a["pareto"])


def test_synthetic_calibration_cannot_authorize_envelope():
    svc = AdvancedResearchService(InMemoryDesignStore())
    env = svc.save("optical_envelope", "ENV", optical_envelope(), "designer")
    params = {k: sum(v) / 2 for k, v in env["bounds"].items()}
    m = simulate(params, env)
    points = [
        CalibrationPoint(
            parameters=params,
            measurement_reference=f"SYN-{i}",
            split="calibration" if i < 3 else "verification",
            measured_mtf_20=m["mtf_20"],
            measured_mtf_50=m["mtf_50"],
            qc_passed=True,
        )
        for i in range(5)
    ]
    report = calibrate(
        svc,
        CalibrationRequest(
            envelope_id=env["record_id"],
            max_absolute_mtf_error=0.05,
            points=points,
            evidence_kind="synthetic_fixture",
            measured_at="2026-01-01",
        ),
        "calibrator",
    )
    assert report["passed"] and not report["eligible_for_measured_review"]
    with pytest.raises(ResearchError, match="did not pass"):
        review(
            svc,
            Review(
                target_kind="envelope",
                target_id=env["record_id"],
                evidence_id=report["record_id"],
                decision="approve",
                reason="Attempt approval using synthetic calibration",
            ),
            "reviewer",
        )


def test_review_requires_independent_author_and_locked_thresholds(model):
    inp, artifact = model
    svc = AdvancedResearchService(InMemoryDesignStore())
    saved = svc.save("trained_model", "NPM3", artifact, "trainer")
    with pytest.raises(ResearchError, match="own artifact"):
        review(
            svc,
            Review(
                target_kind="model",
                target_id=saved["record_id"],
                decision="approve",
                reason="Must not approve my own trained artifact",
            ),
            "trainer",
        )
    with pytest.raises(ResearchError, match="frozen before training"):
        review(
            svc,
            Review(
                target_kind="model",
                target_id=saved["record_id"],
                decision="approve",
                reason="Missing predeclared validation policy",
            ),
            "reviewer",
        )


def test_training_release_forecast_evaluation_and_rollback_end_to_end(store):
    from nso.research_contracts import Outcome

    svc = AdvancedResearchService(store)
    inp = learning_request()
    policy = svc.save(
        "release_policy",
        "POL",
        ReleasePolicy(
            name="Synthetic testing only", minimum_test_patients=8, minimum_coverage=0.5
        ).model_dump(),
        "reviewer",
    )
    inp.validation_policy_id = policy["record_id"]
    seed_learning_cases(svc, inp)
    job = svc.queue_training(inp, "trainer")
    completed = svc.execute_training(job["record_id"])
    assert completed["status"] == "completed"
    assert svc.execute_training(job["record_id"])["model_id"] == completed["model_id"]
    approval = review(
        svc,
        Review(
            target_kind="model",
            target_id=completed["model_id"],
            policy_id=policy["record_id"],
            decision="approve",
            reason="Independent software fixture review; no clinical evidence",
        ),
        "reviewer",
    )
    with pytest.raises(ResearchError, match="separate operator"):
        deploy(
            svc,
            Deployment(
                model_id=completed["model_id"],
                review_id=approval["record_id"],
                reason="Research release of synthetic testing model",
            ),
            "trainer",
        )
    deployment = deploy(
        svc,
        Deployment(
            model_id=completed["model_id"],
            review_id=approval["record_id"],
            reason="Research release of synthetic testing model",
        ),
        "operator",
    )
    artifact = svc.get("trained_model", completed["model_id"])
    selected = next(s for s in inp.samples if s.split == "train")
    identity = {k: getattr(selected, k) for k in ("patient_id", "case_id", "eye")}
    svc.ingest(ObservationBatch(**identity, observations=selected.history), "importer")
    forecast = svc.forecast(
        Forecast(
            **identity,
            index_date=selected.index_date,
            index_age=selected.index_age,
            model_id=completed["model_id"],
            untreated_history_confirmed=True,
        ),
        "researcher",
    )
    assert forecast["forecasts"][0]["al_mm"] is not None
    assert forecast["model_artifact_hash"] == artifact["artifact_hash"]
    assert forecast["forecasts"][0]["al_interval"] is not None
    result = svc.evaluate(
        Outcome(prediction_id=forecast["prediction_id"], observation=selected.observed),
        "researcher",
    )
    assert result["metrics"]["al"]["primary_endpoint_eligible"]
    with pytest.raises(ResearchError, match="previously deployed"):
        rollback(
            svc,
            Rollback(
                target_deployment_id=deployment["record_id"],
                reason="Test invalid rollback to current deployment",
            ),
            "operator",
        )
    second = deploy(
        svc,
        Deployment(
            model_id=completed["model_id"],
            review_id=approval["record_id"],
            reason="Repeat explicit deployment for rollback test",
        ),
        "operator",
    )
    reverted = rollback(
        svc,
        Rollback(
            target_deployment_id=deployment["record_id"],
            reason="Restore previously deployed synthetic model",
        ),
        "operator",
    )
    assert (
        reverted["action"] == "rollback"
        and reverted["previous_deployment_id"] == second["record_id"]
    )
    assert not reverted["clinical_use_allowed"]
    review(
        svc,
        Review(
            target_kind="model",
            target_id=completed["model_id"],
            policy_id=policy["record_id"],
            decision="reject",
            reason="Withdraw this synthetic research approval after review",
        ),
        "reviewer",
    )
    with pytest.raises(ResearchError, match="withdrawn"):
        svc.forecast(
            Forecast(
                **identity,
                index_date=selected.index_date,
                index_age=selected.index_age,
                model_id=completed["model_id"],
                untreated_history_confirmed=True,
            ),
            "researcher",
        )
    with pytest.raises(ResearchError, match="superseded"):
        deploy(
            svc,
            Deployment(
                model_id=completed["model_id"],
                review_id=approval["record_id"],
                reason="Must not reuse a withdrawn model approval",
            ),
            "operator",
        )


def test_trained_model_cannot_serve_before_deployment():
    svc = AdvancedResearchService(InMemoryDesignStore())
    scope = seed(svc)
    svc.ingest(
        ObservationBatch(
            **scope,
            observations=[
                observation(date(2025, 1, 1), 24, -2),
                observation(date(2026, 1, 1), 24.2, -2.3),
            ],
        ),
        "test",
    )
    with pytest.raises(ResearchError, match="explicitly approved"):
        svc.forecast(
            Forecast(
                **scope,
                index_date="2026-01-01",
                index_age=10,
                model_id="NPM3-UNAPPROVED",
                untreated_history_confirmed=True,
            ),
            "test",
        )


def test_api_mutation_rolls_back_data_and_receipt_on_unexpected_failure(monkeypatch):
    import research_api
    from nso.research_contracts import Contract
    from starlette.requests import Request

    store = InMemoryDesignStore()
    monkeypatch.setattr(nso, "REGISTRY", nso.DesignRegistry(store))

    class Input(Contract):
        value: int

    request = Request(
        {
            "type": "http",
            "path": "/api/v3/test",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
        }
    )

    def crash():
        store.put_record("test", "partial", {"value": 1})
        raise RuntimeError("unexpected fixture failure")

    with pytest.raises(RuntimeError):
        research_api.mutate(
            request, {"actor": "tester"}, Input(value=1), "atomic-test-key", crash
        )
    assert store.list_records("test") == []
    assert not getattr(store, "_v3_operations", {})


def test_worker_lease_prevents_duplicates_and_recovers_after_expiry(store, monkeypatch):
    from nso.research_jobs import job_lease
    import nso.research_jobs as jobs

    clock = [100.0]
    monkeypatch.setattr(jobs.time, "time", lambda: clock[0])
    with job_lease(store, "JOB", 10) as acquired:
        assert acquired
        with job_lease(store, "JOB", 10) as second:
            assert not second
        clock[0] = 111.0
        with job_lease(store, "JOB", 10) as recovered:
            assert recovered
    with job_lease(store, "JOB", 10) as next_run:
        assert next_run


def test_logical_backup_restore_and_corrupt_or_nonempty_rejection(store, tmp_path):
    from scripts.v3_backup import snapshot, restore

    if isinstance(store, InMemoryDesignStore):
        with pytest.raises(ValueError):
            snapshot(store)
        return
    store.put_record("test", "preserved", {"synthetic": True})
    store.append_audit({"object_id": "preserved", "action": "test"})
    document = snapshot(store)
    target = SQLiteDesignStore(tmp_path / "restored.db")
    cleanup = None
    if isinstance(store, PostgresDesignStore):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        schema = "restore_" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
        with psycopg.connect(store.dsn) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        target = PostgresDesignStore(
            make_conninfo(store.dsn, options="-c search_path=" + schema)
        )
        cleanup = lambda: drop_schema(store.dsn, schema)
    try:
        counts = restore(target, document)
        assert counts["domain_records"] == 1
        assert target.get_record("test", "preserved") == {"synthetic": True}
        assert snapshot(target)["sha256"] == document["sha256"]
        with pytest.raises(ValueError, match="empty target"):
            restore(target, document)
    finally:
        if cleanup:
            cleanup()
    document["tables"]["domain_records"][0][2] = '{"tampered":true}'
    with pytest.raises(ValueError, match="checksum"):
        restore(SQLiteDesignStore(tmp_path / "corrupt.db"), document)


def test_missing_followup_sensitivity_and_overlap_rejection():
    svc = AdvancedResearchService(InMemoryDesignStore())
    frozen = study(svc, "observational", n=80)
    cohort = svc.get("cohort", frozen["cohort_id"])
    missing_patient = cohort["members"][0]["patient_id"]
    for row in cohort["members"]:
        if row["patient_id"] == missing_patient:
            row["followup"] = None
            row["exclusions"] = ["MISSING_MEASURED_FOLLOWUP_AL"]
    scenario = svc.save(
        "cohort",
        "COH",
        {**cohort, "dataset_hash": digest(cohort["members"])},
        "fixture",
    )
    result = analyze(
        svc,
        CausalRequest(
            cohort_id=scenario["record_id"],
            method="observational_aipw",
            bootstrap_reps=50,
        ),
        "analyst",
    )
    assert result["missingness_sensitivity_required"]
    assert (
        sum(
            result["missing_patient_scenario"]["fully_missing_patients_by_arm"].values()
        )
        == 1
    )
    bounds = result["missing_patient_scenario"]["unadjusted_arm_difference_bounds_mm"]
    assert bounds[0] < bounds[1]
    for row in cohort["members"]:
        row["enrollment"]["age"] = 8 if row["arm"] == "NONE" else 18
    separated = svc.save(
        "cohort",
        "COH",
        {**cohort, "dataset_hash": digest(cohort["members"])},
        "fixture",
    )
    unsupported = analyze(
        svc,
        CausalRequest(
            cohort_id=separated["record_id"],
            method="observational_aipw",
            bootstrap_reps=50,
        ),
        "analyst",
    )
    assert unsupported["status"] == "overlap_failed"
    assert unsupported["effect_mm"] is None


def test_real_optimizer_api_projects_summaries_without_parameters(monkeypatch):
    from nso.research_contracts import Optimization

    store = InMemoryDesignStore()
    svc = AdvancedResearchService(store)
    identity = seed(svc)
    env = svc.save("optical_envelope", "ENV", optical_envelope(), "engineer")
    job = svc.submit_optimizer(
        Optimization(**identity, envelope_id=env["record_id"], candidate_budget=8),
        "engineer",
    )
    output = svc.execute_optimizer(job["record_id"], "engineer")
    assert (
        output["status"] == "completed"
        and output["calibration_status"] == "uncalibrated_reference"
    )
    assert output["pareto_candidates"]
    assert "parameters" not in json.dumps(output)
    assert "relief_max_um" not in json.dumps(output)
    assert svc.execute_optimizer(job["record_id"], "engineer") == output
    candidate = svc.get(
        "optical_candidate", output["pareto_candidates"][0]["design_id"]
    )
    assert set(candidate["parameters"]) == {
        "sa_um",
        "noise_height_um",
        "fiber_height_um",
        "fiber_angle_deg",
    }
