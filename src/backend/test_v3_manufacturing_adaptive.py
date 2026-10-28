"""End-to-end and adversarial checks using invented research populations."""

import hashlib
import json
import os
from copy import deepcopy
import numpy as np
import pytest
from fastapi.testclient import TestClient
import api
import nso
from nso.manufacturing.store import (
    InMemoryDesignStore,
    SQLiteDesignStore,
    PostgresDesignStore,
)
from nso.research import ResearchError, digest
from nso.research_advanced import AdvancedResearchService
from nso.research_data import Enrollment, enroll
from nso.research_fixtures import observation
from nso import research_manufacturing as m
from nso import research_adaptive as a


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def svc(request, tmp_path):
    if request.param == "memory":
        store = InMemoryDesignStore()
    elif request.param == "sqlite":
        store = SQLiteDesignStore(tmp_path / "extension.db")
    else:
        dsn = os.getenv("NSO_TEST_POSTGRES_URL")
        if not dsn:
            pytest.skip("NSO_TEST_POSTGRES_URL required for isolated PostgreSQL checks")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        schema = "ext_" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PostgresDesignStore(
            make_conninfo(dsn, options="-c search_path=" + schema)
        )

        def cleanup():
            with psycopg.connect(dsn) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )

        request.addfinalizer(cleanup)
    return AdvancedResearchService(store)


def test_full_synthetic_manufacturing_thread_and_no_ip_leak(svc):
    scope = scope_case(svc)
    plan = plan_fixture(svc, scope)
    lot = lot_fixture(svc, plan)
    assert (
        svc.store.get_record("recipe_version", lot["recipe_version_id"])["parameters"][
            "machine_instructions"
        ]
        is False
    )
    with pytest.raises(ResearchError, match="complete passing QC"):
        m.record_dispense(
            svc,
            m.DispenseRequest(
                lot_id=lot["record_id"],
                start_at="2026-01-02",
                adherence=0.9,
                authorization_reference="SYNTHETIC-RESEARCH-AUTHORIZATION",
            ),
            "clinician",
        )
    assert qc_fixture(svc, lot)["passed"]
    exposure = m.record_dispense(
        svc,
        m.DispenseRequest(
            lot_id=lot["record_id"],
            start_at="2026-01-02",
            adherence=0.9,
            authorization_reference="SYNTHETIC-RESEARCH-AUTHORIZATION",
        ),
        "clinician",
    )
    assert not exposure["clinical_use_allowed"]
    validation = m.record_outcome(
        svc,
        m.ManufacturingOutcome(
            lot_id=lot["record_id"],
            prediction_id=plan["prediction_id"],
            observation=observation("2027-01-01", 24.2, -2.3),
        ),
        "researcher",
    )
    assert (
        svc.store.get_record("visit", plan["index_visit_id"])["visit_date"]
        == "2026-01-01"
    )
    assert (
        svc.store.get_record("visit", validation["followup_visit_id"])["visit_date"]
        == "2027-01-01"
    )
    assert len(svc.store.list_records("visit")) == 2
    assert validation["primary_endpoint_eligible"]
    assert not validation["model_approval_granted"]
    trace = m.trace(svc, scope["case_id"])
    serialized = json.dumps(trace)
    assert (
        trace["manufacturing_threads"][0]["lots"][0]["validations"][0]["record_id"]
        == validation["record_id"]
    )
    assert (
        "parameters" not in serialized
        and "qc_requirements" not in serialized
        and "surface_error" not in serialized
    )
    assert len(svc.store.list_records("product_exposure")) == 1
    assert len(svc.store.list_records("qc_measurement")) == 1
    # A duplicate dispense cannot create another exposure.
    with pytest.raises(ResearchError):
        m.record_dispense(
            svc,
            m.DispenseRequest(
                lot_id=lot["record_id"],
                start_at="2026-01-03",
                adherence=0.9,
                authorization_reference="SYNTHETIC-AUTHORIZATION",
            ),
            "clinician",
        )
    assert len(svc.store.list_records("product_exposure")) == 1


def test_failed_qc_quarantine_and_revocation(svc):
    scope = scope_case(svc)
    plan = plan_fixture(svc, scope)
    lot = lot_fixture(svc, plan)
    assert not qc_fixture(svc, lot, 0.3)["passed"]
    assert qc_fixture(svc, lot, 0.1)["passed"]
    with pytest.raises(ResearchError, match="quarantined"):
        m.lot_ready(svc, lot["record_id"])
    replacement = lot_fixture(svc, plan, "SYN-REWORK")
    assert qc_fixture(svc, replacement)["passed"]
    m.record_dispense(
        svc,
        m.DispenseRequest(
            lot_id=replacement["record_id"],
            start_at="2026-01-02",
            adherence=0.9,
            authorization_reference="SYN-REWORK-AUTHORIZATION",
        ),
        "clinician",
    )
    m.decide_plan(
        svc,
        m.ManufacturingDecision(
            plan_id=plan["record_id"],
            decision="reject",
            reason="Withdraw after independent engineering review.",
            process_qualification_reference="SYN-REVIEW",
        ),
        "reviewer",
    )
    with pytest.raises(ResearchError, match="current independent approval"):
        m.lot_ready(svc, replacement["record_id"])


def test_manufacturing_independence_scope_and_evidence_gate(svc):
    scope = scope_case(svc)
    plan = plan_fixture(svc, scope, approve=False)
    with pytest.raises(ResearchError, match="own plans"):
        m.decide_plan(
            svc,
            m.ManufacturingDecision(
                plan_id=plan["record_id"],
                decision="approve",
                reason="Attempt author approval of own candidate.",
                process_qualification_reference="SYN-QUALIFICATION",
            ),
            "engineer",
        )
    wrong_arm = deepcopy(svc.get("manufacturing_plan", plan["record_id"]))
    wrong_arm["arm"] = "SA_BN"
    with pytest.raises(ResearchError, match="declared research arm"):
        m.check_candidate(svc, wrong_arm)
    request = m.ManufacturingPlan(
        **scope,
        prediction_id=plan["prediction_id"],
        candidate_id=plan["candidate_id"],
        mode="measured_research",
        arm="SA_ONLY",
        process_reference="QUALIFIED-REFERENCE",
        material_code="REAL-MATERIAL",
        qc_requirements=[
            {"name": "surface_error", "unit": "um", "lower": 0, "upper": 0.2}
        ],
    )
    with pytest.raises(ResearchError, match="Synthetic cases"):
        m.create_plan(svc, request, "engineer")
    # Non-synthetic label alone cannot bypass measured calibration.
    other = scope_case(svc, "REAL-P", "REAL-C", indication="RESEARCH")
    otherplan = deepcopy(svc.get("manufacturing_plan", plan["record_id"]))
    otherplan.update(other)
    with pytest.raises(ResearchError, match="approved optical design"):
        m.check_candidate(svc, otherplan, True)


def test_adaptive_train_shadow_followup_monitor_and_withdraw(svc):
    policy, model = adaptive_fixture(svc)
    assert model["validation_passed"], model["report"]
    assert np.isfinite(model["coef"]).all()
    assert 0.045 < model["coef"][0] / model["scale"][0] < 0.08
    for report in model["report"].values():
        assert report["relative_improvement"] > 0.05
    dep = deployment_fixture(svc, model)
    scope = scope_case(svc)
    first = plan_fixture(svc, scope, "SA_ONLY")
    second = plan_fixture(svc, scope, "SA_BN")
    pro = svc.get("cohort", policy["train_cohort_id"])["protocol_id"]
    en = enroll(
        svc,
        Enrollment(
            **scope,
            protocol_id=pro,
            index_date="2026-01-01",
            eligible=True,
            assigned_arm="SA_ONLY",
            eligibility_reasons=["Synthetic shadow eligible"],
            age=12,
            baseline_al=24,
            baseline_se=-2,
            prior_al_slope=0.25,
            sex_code=0,
            allocation_reference="SYN-NEW-ALLOCATION",
        ),
        "researcher",
    )
    req = a.ShadowRequest(
        **scope,
        enrollment_id=en["record_id"],
        plan_ids=[first["record_id"], second["record_id"]],
    )
    before = len(svc.store.list_records("manufacturing_lot"))
    log = a.shadow(svc, req, "researcher")
    assert log["status"] == "shadow_logged" and len(log["candidates"]) == 2
    assert not log["manufacturing_authorized"] and not log["actual_assignment_changed"]
    assert len(svc.store.list_records("manufacturing_lot")) == before
    outcome = a.followup(
        svc,
        a.ShadowOutcome(
            shadow_id=log["record_id"],
            observed_arm="SA_ONLY",
            observation=observation("2027-01-01", 24.3, -2.2),
            adherence=0.9,
            source_reference="SYNTHETIC-FOLLOWUP",
        ),
        "researcher",
    )
    assert outcome["individual_effect_error"] is None
    report = a.monitor(svc, model["record_id"])
    assert report["outcomes"] == 1 and not report["automatic_promotion"]
    with pytest.raises(ResearchError, match="immutable"):
        a.followup(
            svc,
            a.ShadowOutcome(
                shadow_id=log["record_id"],
                observed_arm="SA_ONLY",
                observation=observation("2027-01-01", 24.3, -2.2),
                adherence=0.9,
                source_reference="SYN-DUPLICATE",
            ),
            "researcher",
        )
    with pytest.raises(ResearchError, match="already logged"):
        a.shadow(svc, req, "researcher")
    a.deploy(
        svc,
        a.ShadowDeployment(
            model_id=model["record_id"],
            review_id=dep["review_id"],
            rollback_to_deployment_id=dep["record_id"],
            reason="Explicit rollback to a prior approved shadow deployment.",
        ),
        "operator",
    )
    assert len(a.deployments(svc)) == 2
    other = scope_case(svc, "SYN-OOD", "SYN-OOD-CASE")
    p0, p1 = plan_fixture(svc, other, "SA_ONLY"), plan_fixture(svc, other, "SA_BN")
    oen = enroll(
        svc,
        Enrollment(
            **other,
            protocol_id=pro,
            index_date="2026-01-01",
            eligible=True,
            assigned_arm="SA_ONLY",
            eligibility_reasons=["Invented OOD fixture"],
            age=50,
            baseline_al=24,
            baseline_se=-2,
            prior_al_slope=0.25,
            sex_code=1,
            allocation_reference="SYN-OOD-ALLOCATION",
        ),
        "fixture",
    )
    ood = a.shadow(
        svc,
        a.ShadowRequest(
            **other,
            enrollment_id=oen["record_id"],
            plan_ids=[p0["record_id"], p1["record_id"]],
        ),
        "researcher",
    )
    assert (
        ood["status"] == "abstained"
        and ood["candidates"] == []
        and ood["research_conditional_arm_difference_mm"] is None
    )
    assert "OOD_RATE" in a.monitor(svc, model["record_id"])["alerts"]
    a.review(
        svc,
        a.AdaptiveReview(
            model_id=model["record_id"],
            decision="reject",
            reason="Withdraw the synthetic model after review.",
            scientific_review_reference="SYN-WITHDRAWAL",
        ),
        "reviewer",
    )
    with pytest.raises(ResearchError, match="no longer approved"):
        a.shadow(svc, req, "researcher")
    assert dep["ranking_mode"] == "shadow_only"


def test_policy_leakage_and_independent_review(svc):
    policy, model = adaptive_fixture(svc, n=60)
    bad = {k: policy[k] for k in a.AdaptivePolicy.model_fields}
    bad["external_cohort_id"] = bad["test_cohort_id"]
    with pytest.raises(ResearchError, match="distinct frozen cohorts"):
        a.lock_policy(svc, a.AdaptivePolicy(**bad), "author")
    temporal = {k: policy[k] for k in a.AdaptivePolicy.model_fields}
    temporal["holdout"] = "temporal"
    with pytest.raises(ResearchError, match="development endpoints"):
        a.lock_policy(svc, a.AdaptivePolicy(**temporal), "author")
    incomplete = deepcopy(svc.get("cohort", policy["train_cohort_id"]))
    incomplete["members"][0]["followup"] = None
    incomplete["dataset_hash"] = digest(incomplete["members"])
    changed = svc.save("cohort", "COH", incomplete, "fixture")
    missing_policy = {k: policy[k] for k in a.AdaptivePolicy.model_fields}
    missing_policy.update(train_cohort_id=changed["record_id"], max_missing_fraction=0)
    with pytest.raises(ResearchError, match="Missing/switching"):
        a.lock_policy(svc, a.AdaptivePolicy(**missing_policy), "author")
    with pytest.raises(ResearchError, match="approve themselves"):
        a.review(
            svc,
            a.AdaptiveReview(
                model_id=model["record_id"],
                decision="approve",
                reason="Attempt own model approval despite separation.",
                scientific_review_reference="SYN-REVIEW",
            ),
            "author",
        )
    with pytest.raises(ResearchError, match="new policy/version"):
        a.train(svc, a.AdaptiveTrain(policy_id=policy["record_id"]), "author")
    model2 = deepcopy(model)
    model2["validation_passed"] = False
    failed = svc.save("adaptive_model", "AMOD", model2, "author")
    with pytest.raises(ResearchError, match="held-out gates"):
        a.review(
            svc,
            a.AdaptiveReview(
                model_id=failed["record_id"],
                decision="approve",
                reason="Must reject a model failing held out gates.",
                scientific_review_reference="SYN-REVIEW",
            ),
            "reviewer",
        )


def test_api_flags_roles_scope_idempotency_and_qc_atomicity(svc, monkeypatch):
    scope = scope_case(svc)
    plan = plan_fixture(svc, scope)
    monkeypatch.setattr(nso, "REGISTRY", nso.DesignRegistry(svc.store))

    def principal(actor, roles, patients):
        return {
            "actor": actor,
            "token_sha256": hashlib.sha256(actor.encode()).hexdigest(),
            "roles": roles,
            "patient_ids": patients,
        }

    monkeypatch.setenv(
        "NSO_V3_PRINCIPALS",
        json.dumps(
            [
                principal(
                    "operator", ["manufacturing_engineer"], [scope["patient_id"]]
                ),
                principal("reader", ["researcher"], [scope["patient_id"]]),
                principal("outsider", ["admin"], []),
            ]
        ),
    )
    headers = {
        "Authorization": "Bearer operator",
        "Idempotency-Key": "unique-lot-request",
    }
    body = {
        "plan_id": plan["record_id"],
        "lot_code": "API-SYN-LOT",
        "manufacturer_id": "SYN-OEM",
        "facility_id": "SYN-FAC",
    }
    with TestClient(api.app) as client:
        assert (
            client.post(
                "/api/v3/manufacturing/lots", json=body, headers=headers
            ).status_code
            == 503
        )
        monkeypatch.setenv("NSO_V3_MANUFACTURING_ENABLED", "true")
        assert client.post("/api/v3/manufacturing/lots", json=body).status_code == 401
        assert (
            client.post(
                "/api/v3/manufacturing/lots",
                json=body,
                headers={**headers, "Authorization": "Bearer reader"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v3/manufacturing/lots",
                json=body,
                headers={**headers, "Authorization": "Bearer outsider"},
            ).status_code
            == 403
        )
        first = client.post("/api/v3/manufacturing/lots", json=body, headers=headers)
        assert first.status_code == 201, first.text
        again = client.post("/api/v3/manufacturing/lots", json=body, headers=headers)
        assert (
            first.json() == again.json()
            and again.headers["Idempotent-Replay"] == "true"
        )
        assert len(svc.store.list_records("manufacturing_lot")) == 1
        conflict = client.post(
            "/api/v3/manufacturing/lots",
            json={**body, "lot_code": "CHANGED"},
            headers=headers,
        )
        assert conflict.status_code == 409
        trace = client.get(
            "/api/v3/manufacturing/cases/" + scope["case_id"] + "/trace",
            headers=headers,
        )
        assert (
            trace.status_code == 200
            and "parameters" not in trace.text
            and "qc_requirements" not in trace.text
        )
        assert (
            client.get(
                "/api/v3/manufacturing/cases/" + scope["case_id"] + "/trace",
                headers={"Authorization": "Bearer outsider"},
            ).status_code
            == 403
        )
        monkeypatch.setenv("NSO_V3_ADAPTIVE_RANKING_ENABLED", "true")
        state = client.get("/api/v3/health").json()["features"]
        assert state["adaptive_shadow_enabled"] is True
        assert state["adaptive_ranking_enabled"] is False
        assert (
            client.post(
                "/api/v3/adaptive/train", json={"policy_id": "UNKNOWN"}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v3/manufacturing/qc",
                json={
                    "lot_id": first.json()["record_id"],
                    "measurements": [
                        {"name": "surface_error", "actual": 0.1, "unit": "um"}
                    ],
                    "evidence_reference": "SYN-QC",
                    "passed": True,
                },
                headers=headers,
            ).status_code
            == 422
        )
    before = len(svc.store.list_records("v3_manufacturing_qc"))
    audits = len(svc.store.audits())

    def fail(*args, **kwargs):
        raise RuntimeError("Simulated storage failure after QC evidence write")

    monkeypatch.setattr(nso.ClinicalDigitalThread, "record_qc", fail)
    with pytest.raises(RuntimeError):
        qc_fixture(svc, first.json())
    assert len(svc.store.list_records("v3_manufacturing_qc")) == before
    assert len(svc.store.audits()) == audits


def test_adaptive_overlap_and_schema_bounds():
    with pytest.raises(ResearchError, match="Propensity support"):
        a.support(
            np.full(100, 0.99),
            np.array([0, 1] * 50),
            {"minimum_patients_per_arm": 20, "max_extreme_propensity_fraction": 0.05},
        )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        m.QCValue(name="surface_error", actual=float("nan"), unit="um")
    with pytest.raises(ValidationError):
        a.AdaptivePolicy(
            name="Invalid posthoc thresholds",
            train_cohort_id="a",
            test_cohort_id="b",
            external_cohort_id="c",
            evidence_kind="synthetic",
            minimum_relative_improvement=-1,
            analysis_plan="Locked detailed plan required for synthetic tests.",
            identification_assumptions="No unmeasured confounding is a scientific assumption.",
        )


def test_wrong_eye_qc_units_incomplete_measurements_and_foreign_outcome(svc):
    scope = scope_case(svc)
    plan = plan_fixture(svc, scope)
    lot = lot_fixture(svc, plan)
    original = svc.get("manufacturing_plan", plan["record_id"])
    wrong_arm = deepcopy(svc.get("manufacturing_plan", plan["record_id"]))
    wrong_arm["arm"] = "SA_BN"
    with pytest.raises(ResearchError, match="declared research arm"):
        m.check_candidate(svc, wrong_arm)
    request = m.ManufacturingPlan(
        **{k: original[k] for k in m.ManufacturingPlan.model_fields}
    )
    with pytest.raises(ResearchError, match="Prediction does not match"):
        m.create_plan(svc, request.model_copy(update={"eye": "OS"}), "engineer")
    with pytest.raises(ResearchError, match="exactly once"):
        m.record_qc(
            svc,
            m.QCRequest(
                lot_id=lot["record_id"],
                measurements=[{"name": "other", "actual": 0.1, "unit": "um"}],
                evidence_reference="SYN-QC",
            ),
            "qa",
        )
    with pytest.raises(ResearchError, match="units differ"):
        m.record_qc(
            svc,
            m.QCRequest(
                lot_id=lot["record_id"],
                measurements=[{"name": "surface_error", "actual": 0.1, "unit": "mm"}],
                evidence_reference="SYN-QC",
            ),
            "qa",
        )
    with pytest.raises(ResearchError, match="does not belong"):
        m.record_outcome(
            svc,
            m.ManufacturingOutcome(
                lot_id=lot["record_id"],
                prediction_id="FOREIGN",
                observation=observation("2027-01-01", 24.2, -2.3),
            ),
            "researcher",
        )
    assert not svc.store.list_records("v3_manufacturing_qc")
    assert not svc.store.list_records("v3_manufacturing_validation")


from nso.research_extension_fixtures import (
    scope_case,
    plan_fixture,
    lot_fixture,
    qc_fixture,
    adaptive_fixture,
    deployment_fixture,
)
