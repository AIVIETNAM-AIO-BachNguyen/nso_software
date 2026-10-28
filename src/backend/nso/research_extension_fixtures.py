"""Invented software rehearsal fixtures; never clinical/manufacturing evidence."""

from datetime import date
from .research import months_after
import numpy as np
from .engineering import ClinicalDigitalThread
from .research_contracts import (
    ObservationBatch,
    Forecast,
    Optimization,
    Cohort,
    Exposure,
)
from .research_data import Protocol, Enrollment, enroll
from .research_fixtures import observation, optical_envelope
from . import research_manufacturing as m
from . import research_adaptive as a


def scope_case(svc, pid="SYN-NEW", case="SYN-NEW-CASE", age=12, indication="SYNTHETIC"):
    ClinicalDigitalThread(svc.store).create_case(
        patient_id=pid,
        case_id=case,
        site_id="NEW-SITE",
        indication_code=indication,
        clinician_id="fixture",
    )
    scope = {"patient_id": pid, "case_id": case, "eye": "OD"}
    svc.ingest(
        ObservationBatch(
            **scope,
            observations=[
                observation("2025-01-01", 23.75, -1.6),
                observation("2026-01-01", 24, -2),
            ],
        ),
        "fixture",
    )
    return scope


def plan_fixture(svc, scope, arm="SA_ONLY", suffix="", approve=True):
    forecast = svc.forecast(
        Forecast(**scope, index_date="2026-01-01", untreated_history_confirmed=True),
        "fixture",
    )
    envdata = optical_envelope()
    if arm == "SA_ONLY":
        envdata["bounds"]["noise_height_um"] = [0, 0]
        envdata["bounds"]["fiber_height_um"] = [0, 0]
    elif arm == "SA_BN":
        envdata["bounds"]["fiber_height_um"] = [0, 0]
    env = svc.save("optical_envelope", "ENV", envdata, "engineer")
    job = svc.submit_optimizer(
        Optimization(
            **scope,
            envelope_id=env["record_id"],
            objective_version="optical-quality-v1",
            seed=5,
            candidate_budget=8,
        ),
        "engineer",
    )
    result = svc.execute_optimizer(job["record_id"], "engineer")
    candidate = result["pareto_candidates"][0]["design_id"]
    plan = m.create_plan(
        svc,
        m.ManufacturingPlan(
            **scope,
            prediction_id=forecast["prediction_id"],
            candidate_id=candidate,
            mode="synthetic_rehearsal",
            arm=arm,
            process_reference="SYNTHETIC-PROCESS",
            material_code="SYN-MATERIAL",
            qc_requirements=[
                {"name": "surface_error", "unit": "um", "lower": 0, "upper": 0.2}
            ],
        ),
        "engineer",
    )
    if approve:
        m.decide_plan(
            svc,
            m.ManufacturingDecision(
                plan_id=plan["record_id"],
                decision="approve",
                reason="Independent synthetic rehearsal acceptance.",
                process_qualification_reference="SYNTHETIC-QUALIFICATION",
            ),
            "reviewer",
        )
    return plan


def lot_fixture(svc, plan, code="SYN-LOT"):
    return m.create_lot(
        svc,
        m.LotRequest(
            plan_id=plan["record_id"],
            lot_code=code,
            manufacturer_id="SYN-OEM",
            facility_id="SYN-FAC",
        ),
        "operator",
    )


def qc_fixture(svc, lot, actual=0.1):
    return m.record_qc(
        svc,
        m.QCRequest(
            lot_id=lot["record_id"],
            measurements=[{"name": "surface_error", "actual": actual, "unit": "um"}],
            evidence_reference="SYNTHETIC-QC-MEASUREMENT",
        ),
        "qa",
    )


def population(
    svc,
    partition,
    n=100,
    seed=1,
    assignment="randomized",
    index="2026-01-01",
    site=None,
):
    rng = np.random.default_rng(seed)
    index = date.fromisoformat(index)
    protocol = Protocol(
        name="Synthetic adaptive trial",
        version="1",
        inclusion_criteria=["Invented eligible patients"],
        exclusion_criteria=["No real patient data"],
        estimand="Twelve month axial elongation intervention minus comparator",
        assignment=assignment,
        analysis_population="intention_to_treat",
        covariates=["age", "baseline_al", "baseline_se", "prior_al_slope", "sex_code"],
        missingness_plan="Exclude entire patient if either included eye is incomplete.",
        switching_plan="Retain randomized assigned arms after switching; report missingness separately.",
        safety_plan="Exclude severe events and review independently.",
        analysis_plan="Locked synthetic DR prototype with external holdout and no clinical use.",
    )
    pro = svc.save("protocol", "PRO", protocol.model_dump(mode="json"), "fixture")
    members = []
    for i in range(n):
        pid = f"SYN-{partition}-{i}"
        case = f"SYN-CASE-{partition}-{i}"
        age = float(rng.uniform(8, 16))
        arm = i % 2
        sex = int(rng.integers(0, 2))
        ClinicalDigitalThread(svc.store).create_case(
            patient_id=pid,
            case_id=case,
            site_id=site or partition,
            indication_code="SYNTHETIC",
            clinician_id="fixture",
        )
        # Strong known heterogeneity solely for testing the software.
        effect = 0.07 * (age - 12)
        patient_noise = float(rng.normal(0, 0.004))
        for eye in ("OD", "OS"):
            al = float(24 + rng.normal(0, 0.25))
            se = float(-2 + rng.normal(0, 0.3))
            slope = 0.25
            delta = (
                0.3
                - 0.008 * (age - 12)
                + arm * effect
                + patient_noise
                + float(rng.normal(0, 0.002))
            )
            scope = {"patient_id": pid, "case_id": case, "eye": eye}
            name = "SA_BN" if arm else "SA_ONLY"
            svc.ingest(
                ObservationBatch(
                    **scope,
                    observations=[
                        observation(index, al, se),
                        observation(months_after(index, 12), al + delta, se - 0.2),
                    ],
                ),
                "fixture",
            )
            svc.exposure(
                Exposure(**scope, arm=name, start_at=index, adherence=0.95), "fixture"
            )
            enroll(
                svc,
                Enrollment(
                    **scope,
                    protocol_id=pro["record_id"],
                    index_date=index,
                    eligible=True,
                    assigned_arm=name,
                    eligibility_reasons=["Invented eligible fixture"],
                    age=age,
                    baseline_al=al,
                    baseline_se=se,
                    prior_al_slope=slope,
                    sex_code=sex,
                    allocation_reference=f"SYN-ALLOCATION-{i}"
                    if assignment == "randomized"
                    else None,
                ),
                "fixture",
            )
            members.append(scope)
    result = svc.freeze_cohort(
        Cohort(
            protocol_id=pro["record_id"],
            cohort_name=partition,
            eligibility_version="synthetic-v1",
            assignment=assignment,
            comparator="SA_ONLY",
            intervention="SA_BN",
            index_date=index,
            analysis_plan=protocol.analysis_plan,
            members=members,
        ),
        "fixture",
    )
    return result["cohort_id"]


def adaptive_fixture(svc, n=60):
    ids = cohort_fixture(svc, n)
    policy = a.lock_policy(
        svc,
        a.AdaptivePolicy(
            name="Synthetic locked shadow policy",
            train_cohort_id=ids[0],
            test_cohort_id=ids[1],
            external_cohort_id=ids[2],
            evidence_kind="synthetic",
            minimum_patients_per_arm=20,
            analysis_plan="Locked synthetic held-out pseudo outcome validation.",
            identification_assumptions="Invented randomized assignments with consistency and no interference.",
        ),
        "author",
    )
    model = a.train(svc, a.AdaptiveTrain(policy_id=policy["record_id"]), "author")
    return policy, model


def deployment_fixture(svc, model):
    rev = a.review(
        svc,
        a.AdaptiveReview(
            model_id=model["record_id"],
            decision="approve",
            reason="Independent software-only synthetic shadow validation.",
            scientific_review_reference="SYN-SCIENTIFIC-REVIEW",
        ),
        "reviewer",
    )
    return a.deploy(
        svc,
        a.ShadowDeployment(
            model_id=model["record_id"],
            review_id=rev["record_id"],
            reason="Enable invented prospective shadow test.",
        ),
        "operator",
    )


def cohort_fixture(svc, n=60):
    ids = [
        population(
            svc,
            "ADAPT-" + part,
            n=n,
            seed=seed,
            site="EXTERNAL" if part == "external" else "DEVELOPMENT",
        )
        for part, seed in [("train", 1), ("test", 2), ("external", 3)]
    ]
    return ids
