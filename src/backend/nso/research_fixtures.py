"""Invented, deterministic software fixtures. Never clinical or calibration evidence."""

import numpy as np

from .research import months_after
from .research_contracts import Observation, ObservationBatch, Cohort, Exposure
from .research_data import Protocol, Enrollment, enroll
from .research_learning import TrainRequest
from .engineering import ClinicalDigitalThread


def observation(day, al, se):
    return Observation(
        visit_at=day,
        al_mm=al,
        se_d=se,
        al_status="measured",
        se_status="measured",
        measurement_method="invented software fixture",
        source="SYNTHETIC_NOT_CLINICAL_EVIDENCE",
    )


def learning_request(algorithm="gradient_boosting", seed=17):
    from datetime import date

    rng = np.random.default_rng(seed)
    index = date(2026, 1, 1)
    samples = []
    for split, count in (
        ("train", 16),
        ("validation", 12),
        ("test", 8),
        ("external", 8),
    ):
        for p in range(count):
            age = float(rng.uniform(8, 16))
            individual = float(rng.normal(0, 0.012))
            for eye in ("OD", "OS"):
                al = float(24 + rng.normal(0, 0.4))
                se = float(-2 + rng.normal(0, 0.6))
                al_rate = 0.3 - 0.013 * (age - 8) + individual
                se_rate = -0.4 + 0.01 * (age - 8) + individual
                prior = observation(
                    months_after(index, -12),
                    al - al_rate + rng.normal(0, 0.01),
                    se - se_rate + rng.normal(0, 0.03),
                )
                current = observation(index, al, se)
                for h in (6, 12, 24):
                    end = months_after(index, h)
                    years = (end - index).days / 365.25
                    samples.append(
                        {
                            "patient_id": f"SYN-{split}-{p}",
                            "case_id": f"SYN-CASE-{split}-{p}",
                            "eye": eye,
                            "split": split,
                            "site_id": "EXTERNAL"
                            if split == "external"
                            else "DEVELOPMENT",
                            "index_date": index,
                            "index_age": age,
                            "sex_code": p % 2,
                            "untreated_history_confirmed": True,
                            "history": [prior, current],
                            "observed": observation(
                                end,
                                al + al_rate * years + rng.normal(0, 0.015),
                                se + se_rate * years + rng.normal(0, 0.03),
                            ),
                        }
                    )
    return TrainRequest(
        dataset_version="SYNTHETIC-NOT-EVIDENCE-v1",
        algorithm=algorithm,
        samples=samples,
        evidence_kind="synthetic_fixture",
        epochs=4,
        seed=seed,
    )


def seed_learning_cases(svc, request):
    seen = set()
    for s in request.samples:
        if s.case_id in seen:
            continue
        ClinicalDigitalThread(svc.store).create_case(
            patient_id=s.patient_id,
            case_id=s.case_id,
            site_id=s.site_id,
            indication_code="SYNTHETIC",
            clinician_id="FIXTURE",
        )
        seen.add(s.case_id)


def study(svc, assignment="randomized", n=40):
    from datetime import date

    rng = np.random.default_rng(19)
    index = date(2026, 1, 1)
    protocol = Protocol(
        name="Invented demonstration",
        version="synthetic-1",
        inclusion_criteria=["Invented patients only"],
        exclusion_criteria=["No actual clinical records"],
        estimand="12-month mean AL change under assigned intervention minus comparator",
        assignment=assignment,
        analysis_population="intention_to_treat"
        if assignment == "randomized"
        else "per_protocol",
        covariates=["age", "baseline_al", "baseline_se"],
        missingness_plan="Report missing endpoints and require sensitivity analysis before interpretation.",
        switching_plan="Use intention-to-treat assignment for randomized examples and report switching.",
        safety_plan="Record invented adverse events separately from efficacy endpoints.",
        analysis_plan="Locked synthetic software check, with patient-level averaging and no clinical inference.",
    )
    locked = svc.save("protocol", "PRO", protocol.model_dump(mode="json"), "fixture")
    members = []
    for i in range(n):
        patient, case = f"SYN-STUDY-{i}", f"SYN-STUDY-CASE-{i}"
        ClinicalDigitalThread(svc.store).create_case(
            patient_id=patient,
            case_id=case,
            site_id="SYNTHETIC",
            indication_code="SYNTHETIC",
            clinician_id="FIXTURE",
        )
        age = float(rng.uniform(8, 16))
        arm = (
            i % 2
            if assignment == "randomized"
            else int(rng.random() < 1 / (1 + np.exp(-0.25 * (age - 12))))
        )
        for eye in ("OD", "OS"):
            scope = {"patient_id": patient, "case_id": case, "eye": eye}
            al, se = float(24 + rng.normal(0, 0.3)), float(-2 + rng.normal(0, 0.5))
            delta = 0.32 - 0.012 * (age - 8) - 0.12 * arm + float(rng.normal(0, 0.015))
            svc.ingest(
                ObservationBatch(
                    **scope,
                    observations=[
                        observation(index, al, se),
                        observation(months_after(index, 12), al + delta, se - 0.3),
                    ],
                ),
                "fixture",
            )
            name = "SA_ONLY" if arm else "NONE"
            svc.exposure(
                Exposure(**scope, arm=name, start_at=index, adherence=0.9), "fixture"
            )
            enroll(
                svc,
                Enrollment(
                    **scope,
                    protocol_id=locked["record_id"],
                    index_date=index,
                    eligible=True,
                    assigned_arm=name,
                    eligibility_reasons=["Invented eligible fixture"],
                    age=age,
                    baseline_al=al,
                    baseline_se=se,
                    prior_al_slope=0.25,
                    sex_code=i % 2,
                    allocation_reference=f"SYN-ALLOCATION-{i}"
                    if assignment == "randomized"
                    else None,
                ),
                "fixture",
            )
            members.append(scope)
    return svc.freeze_cohort(
        Cohort(
            protocol_id=locked["record_id"],
            cohort_name="Synthetic study",
            eligibility_version="fixture-1",
            assignment=assignment,
            comparator="NONE",
            intervention="SA_ONLY",
            index_date=index,
            analysis_plan=protocol.analysis_plan,
            members=members,
        ),
        "fixture",
    )


def optical_envelope():
    return {
        "name": "Invented phase-screen envelope",
        "wavelength_nm": 550,
        "pupil_mm": 4,
        "refractive_index": 1.5,
        "grid": 64,
        "feature_width_um": 500,
        "spacing_um": 800,
        "feature_count": 6,
        "relief_limit_um": 2,
        "minimum_feature_um": 300,
        "decentration_mm": 0.1,
        "rotation_deg": 5,
        "pupil_variation_mm": 0.2,
        "height_tolerance_fraction": 0.05,
        "bounds": {
            "sa_um": [0, 0.08],
            "noise_height_um": [0.01, 0.15],
            "fiber_height_um": [0, 0.1],
            "fiber_angle_deg": [0, 180],
        },
        "process_reference": "SYNTHETIC_NOT_MEASURED_PROCESS",
    }
