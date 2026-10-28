"""Three-arm, parameter-value and leakage tests on invented immutable cohorts."""

from copy import deepcopy
import hashlib, json
import numpy as np
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
import api, nso
from nso.research import ResearchError, digest
from nso import research_adaptive as a
from nso import research_multiarm as m
from nso.research_incremental import evaluate_design_increment
from nso.research_multiarm_fixtures import policy_fixture, shadow_fixture
from test_v3_manufacturing_adaptive import svc as svc  # isolated SQL fixtures


def deploy(svc, model):
    review = a.review(
        svc,
        a.AdaptiveReview(
            model_id=model["record_id"],
            decision="approve",
            reason="Independent three-arm synthetic validation only.",
            scientific_review_reference="SYNTHETIC-THREE-REVIEW",
        ),
        "reviewer",
    )
    return a.deploy(
        svc,
        a.ShadowDeployment(
            model_id=model["record_id"],
            review_id=review["record_id"],
            reason="Deploy three-arm synthetic shadow version only.",
        ),
        "operator",
    )


def test_three_arm_training_ranking_increment_and_api(svc, monkeypatch):
    policy = policy_fixture(svc)
    model = a.train(svc, a.AdaptiveTrain(policy_id=policy["record_id"]), "author")
    assert model["validation_passed"], model["report"]
    assert model["comparator"] == "SA_ONLY" and model["arm_names"] == m.ARMS
    for split, report in model["report"].items():
        assert set(report["contrasts"]) == set(m.ARMS[1:])
        assert all(r["comparator"] == "SA_ONLY" for r in report["contrasts"].values())
        assert (
            min(r["effective_sample_size"] for r in report["arm_support"].values())
            >= 20
        )
    inc = model["incremental_design_report"]
    assert inc["status"] == "completed"
    assert (
        inc["same_patients_across_stages"]
        and not inc["causal_design_effects_identified"]
    )
    assert inc["preprocessing_fit_partition"] == "train"
    assert inc["held_out_predictive_increment_supported"]
    for report in inc["report"].values():
        assert (
            report["stages"]["design"]["mse_mm2"] < report["stages"]["arm"]["mse_mm2"]
        )
        assert report["ablation"]["sa_um"]["mse_reduction_mm2"] > 0
        assert report["within_arm_permutation"]["sa_um"]["mean_mse_increase_mm2"] > 0
    clone_policy = {k: policy[k] for k in m.MultiArmPolicy.model_fields}
    with pytest.raises(ResearchError, match="prior model"):
        a.lock_policy(svc, m.MultiArmPolicy(**clone_policy), "author")
    deploy(svc, model)
    protocol_id = svc.get("cohort", policy["train_cohort_id"])["protocol_id"]
    request = a.ShadowRequest(**shadow_fixture(svc, protocol_id))
    before = {
        domain: len(svc.store.list_records(domain))
        for domain in ("manufacturing_lot", "v3_exposure", "product_exposure")
    }
    log = a.shadow(svc, request, "researcher")
    assert log["status"] == "shadow_logged", log["arm_support"]
    assert log["ranking_complete"] and set(c["arm"] for c in log["candidates"]) == set(
        m.ARMS
    )
    assert (
        log["comparator"] == "SA_ONLY"
        and not log["actual_assignment_changed"]
        and not log["manufacturing_authorized"]
    )
    assert all(before[d] == len(svc.store.list_records(d)) for d in before)
    values = [c["research_difference_vs_comparator_mm"] for c in log["candidates"]]
    assert values == sorted(values)
    # Find a real local-support hole, without changing any fitted model/report.
    points = np.array(model["support_z"]) * model["scale"] + model["mean"]
    partial = next(
        (
            x
            for x in points
            if (s := m.local_support(model, x, policy))["SA_ONLY"]["supported"]
            and sum(v["supported"] for v in s.values()) == 2
        ),
        None,
    )
    assert partial is not None, (
        "Fixture should exercise arm-specific local support holes"
    )
    partial_request = a.ShadowRequest(
        **shadow_fixture(svc, protocol_id, suffix="PARTIAL", features=partial)
    )
    partial_log = a.shadow(svc, partial_request, "researcher")
    assert (
        partial_log["status"] == "partial_shadow_logged"
        and not partial_log["ranking_complete"]
    )
    missing = {
        arm for arm, s in partial_log["arm_support"].items() if not s["supported"]
    }
    assert missing and not any(c["arm"] in missing for c in partial_log["candidates"])
    unsupported_base = next(
        (
            x
            for x in points
            if not m.local_support(model, x, policy)["SA_ONLY"]["supported"]
        ),
        None,
    )
    assert unsupported_base is not None
    base_request = a.ShadowRequest(
        **shadow_fixture(
            svc, protocol_id, suffix="UNSUPPORTED-BASE", features=unsupported_base
        )
    )
    base_log = a.shadow(svc, base_request, "researcher")
    assert (
        base_log["status"] == "abstained"
        and base_log["reason"] == "UNSUPPORTED_COMPARATOR"
        and base_log["candidates"] == []
    )
    # API isolation and projection also cover the new report and cohort endpoints.
    patients = sorted(
        set(model["patient_ids"]) | {request.patient_id, partial_request.patient_id}
    )
    principals = [
        {
            "actor": "scientist",
            "token_sha256": hashlib.sha256(b"synthetic-scientist").hexdigest(),
            "roles": ["adaptive_researcher"],
            "patient_ids": patients,
        },
        {
            "actor": "outsider",
            "token_sha256": hashlib.sha256(b"synthetic-outsider").hexdigest(),
            "roles": ["admin"],
            "patient_ids": [],
        },
    ]
    monkeypatch.setattr(nso, "REGISTRY", nso.DesignRegistry(svc.store))
    monkeypatch.setenv("NSO_V3_PRINCIPALS", json.dumps(principals))
    monkeypatch.setenv("NSO_V3_ADAPTIVE_RANKING_ENABLED", "true")
    headers = {
        "Authorization": "Bearer synthetic-scientist",
        "Idempotency-Key": "synthetic-three-cohort-request",
    }
    with TestClient(api.app) as client:
        result = client.get(
            "/api/v3/adaptive/models/" + model["record_id"] + "/design-analysis",
            headers=headers,
        )
        assert result.status_code == 200 and result.json()["status"] == "completed"
        assert result.json()["evidence_kind"] == "synthetic"
        assert '"parameters":' not in result.text and "support_z" not in result.text
        inspected = client.get(
            "/api/v3/adaptive/shadows/" + log["record_id"], headers=headers
        )
        assert inspected.status_code == 200 and "features" not in inspected.json()
        denied = client.get(
            "/api/v3/adaptive/models/" + model["record_id"] + "/design-analysis",
            headers={"Authorization": "Bearer synthetic-outsider"},
        )
        assert denied.status_code == 403
        cohort = svc.get("cohort", policy["train_cohort_id"])
        body = {k: cohort[k] for k in m.MultiArmCohort.model_fields if k in cohort}
        body["members"] = [
            {k: r[k] for k in ("patient_id", "case_id", "eye")}
            for r in cohort["members"][:3]
        ]
        frozen = client.post(
            "/api/v3/adaptive/multiarm/cohorts", json=body, headers=headers
        )
        assert frozen.status_code == 201, frozen.text
        saved = svc.get("cohort", frozen.json()["cohort_id"])
        assert frozen.json()["design_linked_eyes"] == 3 and all(
            not r["exclusions"] for r in saved["members"]
        )
        assert all(r["delta_al_mm"] is not None for r in saved["members"])
        assert (
            client.post(
                "/api/v3/adaptive/multiarm/cohorts",
                json={**body, "design_parameters": {}},
                headers=headers,
            ).status_code
            == 422
        )
    # Source evidence created after the index cannot enter a future frozen cohort.
    member = svc.get("cohort", policy["test_cohort_id"])["members"][0]
    lot = member["design_evidence"]["source_ids"]["lot"]
    svc.store.put_record(
        "v3_manufacturing_qc",
        "SYN-POST-INDEX-QC",
        {
            "record_id": "SYN-POST-INDEX-QC",
            "lot_id": lot,
            "passed": True,
            "created_at": "2031-01-01T00:00:00+00:00",
        },
    )
    evidence = m.design_evidence(svc, member, "2030-01-01")
    assert evidence["eligible"] and evidence["post_index_qc_ignored"] == 1
    assert "SYN-POST-INDEX-QC" not in evidence["source_ids"]["qc"]


def test_null_design_and_leakage_controls(svc):
    policy = policy_fixture(
        svc, n=60, design_signal=False, prefix="NULL", require_design=False
    )
    cohorts = [
        svc.get("cohort", policy[k])
        for k in ("train_cohort_id", "test_cohort_id", "external_cohort_id")
    ]
    pops = [a.load_population(svc, c, policy) for c in cohorts]
    report = evaluate_design_increment(pops, cohorts, policy)
    assert report["status"] == "completed"
    assert not report["held_out_predictive_increment_supported"]
    for split in report["report"].values():
        # No synthetic parameter effect: do not manufacture a positive claim.
        assert split["design_increment"]["mse_reduction_mm2"] < 0.0005
    # Parameter features that only encode treatment arms are not informative increments.
    constant = deepcopy(cohorts)
    for cohort in constant:
        for row in cohort["members"]:
            arm = row["design_evidence"]["dispensed_arm"]
            row["design_evidence"]["parameters"] = {
                "sa_um": 0.04,
                "noise_height_um": 0 if arm == "SA_ONLY" else 0.1,
                "fiber_height_um": 0.05 if arm == "SA_BN_FIBER" else 0,
                "fiber_angle_deg": 0,
            }
    unavailable = evaluate_design_increment(pops, constant, policy)
    assert (
        unavailable["status"] == "unavailable"
        and unavailable["reason"] == "NO_WITHIN_ARM_PARAMETER_VARIATION"
    )
    # Leakage through physical evidence shared by independent partitions is rejected.
    leaked = deepcopy(cohorts)
    leaked[1]["members"][0]["design_evidence"]["source_ids"]["lot"] = leaked[0][
        "members"
    ][0]["design_evidence"]["source_ids"]["lot"]
    with pytest.raises(ResearchError, match="lot/QC evidence"):
        evaluate_design_increment(pops, leaked, policy)
    missing = deepcopy(cohorts)
    for row in missing[0]["members"][:20]:
        row["design_evidence"] = {
            "eligible": False,
            "reason": "POST_INDEX_DESIGN_EVIDENCE",
        }
    unavailable = evaluate_design_increment(pops, missing, policy)
    assert unavailable["reason"] == "MISSING_OR_POST_INDEX_DESIGN_LINKS"
    changed = deepcopy(cohorts[1])
    changed["members"][0]["patient_id"] = cohorts[0]["members"][0]["patient_id"]
    changed["dataset_hash"] = digest(changed["members"])
    saved = svc.save("cohort", "MCOH", changed, "fixture")
    body = {k: policy[k] for k in m.MultiArmPolicy.model_fields}
    body["test_cohort_id"] = saved["record_id"]
    with pytest.raises(ResearchError, match="one partition"):
        a.lock_policy(svc, m.MultiArmPolicy(**body), "author")


def test_multinomial_support_math_and_forbidden_features():
    policy = {
        "propensity_floor": 0.05,
        "minimum_patients_per_arm": 10,
        "max_extreme_propensity_fraction": 0.05,
    }
    arms = np.tile(np.arange(3), 20)
    p = np.tile([1 / 3] * 3, (60, 1))
    mu = np.zeros((60, 3))
    pop = {"a": arms, "y": np.ones(60)}
    bounded, report = m.overlap(p, arms, policy)
    assert all(v["effective_sample_size"] == pytest.approx(20) for v in report.values())
    assert np.allclose(m.dr_values(pop, bounded, mu).mean(axis=0), np.ones(3))
    bad = np.tile([0.495, 0.495, 0.01], (60, 1))
    with pytest.raises(ResearchError, match="SA_BN_FIBER"):
        m.overlap(bad, arms, policy)
    base = dict(
        name="Locked three arm policy",
        train_cohort_id="a",
        test_cohort_id="b",
        external_cohort_id="c",
        evidence_kind="synthetic",
        analysis_plan="Prespecified independent held-out cohort analysis.",
        identification_assumptions="Synthetic randomized assignment and consistency.",
    )
    for feature in ("observed_delta_al_mm", "adherence", "qc_error", "future_al"):
        with pytest.raises(ValidationError):
            m.MultiArmPolicy(**base, design_features=[feature])
    with pytest.raises(ValidationError):
        m.MultiArmPolicy(
            **base,
            assignment_probabilities=dict(SA_ONLY=0.4, SA_BN=0.4, SA_BN_FIBER=0.4),
        )


def test_observational_propensity_json_roundtrip():
    rng = np.random.default_rng(91)
    x = rng.normal(size=(120, 5))
    arms = np.tile(np.arange(3), 40)
    population = {
        "x": x,
        "a": arms,
        "y": 0.1 * x[:, 0] + 0.05 * arms,
        "assignment": "observational",
    }
    policy = {
        "seed": 19,
        "propensity_floor": 0.01,
        "minimum_patients_per_arm": 10,
        "max_extreme_propensity_fraction": 0.1,
        "local_radius_sd": 2.5,
        "minimum_local_patients_per_arm": 3,
        "minimum_local_ess_per_arm": 2,
    }
    probability, _, artifact = m.nuisance(population, {"x": x[:5]}, policy, export=True)
    assert probability.shape == (5, 3) and np.allclose(probability.sum(axis=1), 1)
    artifact = json.loads(json.dumps(artifact))
    model = {
        "mean": artifact["mean"],
        "scale": artifact["scale"],
        "support_z": ((x - artifact["mean"]) / artifact["scale"]).tolist(),
        "support_arms": arms.tolist(),
        "support_propensity": np.full((120, 3), 1 / 3).tolist(),
        "propensity": artifact,
        "lower": x.min(axis=0).tolist(),
        "upper": x.max(axis=0).tolist(),
    }
    for i in range(5):
        support = m.local_support(model, x[i], policy)
        assert np.allclose(
            [support[arm]["propensity"] for arm in m.ARMS], probability[i]
        )
