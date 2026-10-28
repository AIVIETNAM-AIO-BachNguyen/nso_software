"""Invented, bulk-loaded statistical fixtures; not measured production evidence.

Bulk records exercise frozen provenance joins; separate integration tests execute
real manufacturing APIs. No fixture is eligible for measured-lens approval.
"""

from datetime import date
import numpy as np
from .engineering import ClinicalDigitalThread
from .research import digest, months_after
from .research_contracts import ObservationBatch, Forecast, Optimization
from .research_data import Protocol, Enrollment, enroll
from .research_fixtures import observation, optical_envelope
from .research_optics import simulator_hash
from .research_multiarm import ARMS, MultiArmCohort, MultiArmPolicy, design_evidence
from . import research_adaptive as adaptive
from . import research_manufacturing as manufacturing

STAMP = "2026-01-01T00:00:00+00:00"


def protocol_fixture(svc):
    inp = Protocol(
        name="Invented three arm study",
        version="three-arm-1",
        inclusion_criteria=["Synthetic eligible software records"],
        exclusion_criteria=["No clinical use"],
        estimand="Twelve month measured AL change; both interventions versus common SA_ONLY comparator",
        assignment="randomized",
        analysis_population="intention_to_treat",
        covariates=adaptive.FEATURES,
        missingness_plan="Exclude a patient if any included eye has a missing accepted endpoint.",
        switching_plan="Retain randomized assigned arm; record actual dispensed arm separately.",
        safety_plan="Review severe events independently before research use.",
        analysis_plan="Locked three-arm synthetic DR and held-out nested predictive design-value analysis.",
    )
    return svc.save("protocol", "PRO", inp.model_dump(mode="json"), "synthetic-fixture")


def cohort_fixture(
    svc, partition, n=90, seed=1, design_signal=True, site=None, index="2030-01-01"
):
    rng = np.random.default_rng(seed)
    index = date.fromisoformat(index)
    protocol = protocol_fixture(svc)
    members = []
    batch = []
    for i in range(n):
        arm = i % 3
        name = ARMS[arm]
        pid = f"SYN-THREE-{partition}-{i}"
        case = f"SYN-THREE-CASE-{partition}-{i}"
        scope = {"patient_id": pid, "case_id": case, "eye": "OD"}
        ClinicalDigitalThread(svc.store).create_case(
            patient_id=pid,
            case_id=case,
            site_id=site or partition,
            indication_code="SYNTHETIC",
            clinician_id="SYNTHETIC",
        )
        age = float(rng.uniform(8, 16))
        al = float(rng.normal(24, 0.25))
        se = float(rng.normal(-2, 0.3))
        slope = float(rng.normal(0.25, 0.025))
        sex = int(rng.integers(0, 2))
        parameters = {
            "sa_um": float(rng.uniform(0, 0.08)),
            "noise_height_um": float(rng.uniform(0.03, 0.15)) if arm else 0.0,
            "fiber_height_um": float(rng.uniform(0.02, 0.1)) if arm == 2 else 0.0,
            "fiber_angle_deg": float(rng.uniform(0, 180)) if arm == 2 else 0.0,
        }
        delta = (
            0.32
            - 0.012 * (age - 12)
            + ([0, 0.07 * (age - 12) + 0.025, -0.065 * (age - 12) - 0.015][arm])
            + float(rng.normal(0, 0.004))
        )
        if design_signal:
            delta += (
                2.5 * (parameters["sa_um"] - 0.04)
                + 0.5 * (parameters["noise_height_um"] - (0.09 if arm else 0))
                + 0.4 * (parameters["fiber_height_um"] - (0.06 if arm == 2 else 0))
            )
        baseline = observation(index, al, se).model_dump(mode="json")
        follow = observation(months_after(index, 12), al + delta, se - 0.2).model_dump(
            mode="json"
        )
        en = Enrollment(
            **scope,
            protocol_id=protocol["record_id"],
            index_date=index,
            eligible=True,
            assigned_arm=name,
            eligibility_reasons=["Invented eligible software fixture"],
            age=age,
            baseline_al=al,
            baseline_se=se,
            prior_al_slope=slope,
            sex_code=sex,
            allocation_reference=f"SYN-THREE-ALLOCATION-{partition}-{i}",
        ).model_dump(mode="json")
        ids = {
            kind: f"SYN-{kind}-{partition}-{i}"
            for kind in (
                "PLAN",
                "CAN",
                "LOT",
                "RCP",
                "QC",
                "EXP",
                "PRODUCT",
                "DISP",
                "ENR",
                "BASE",
                "FOLLOW",
            )
        }
        en["record_id"] = ids["ENR"]
        candidate = {
            "record_id": ids["CAN"],
            "parameters": parameters,
            "feasible": True,
            "simulator_hash": simulator_hash(),
            "created_at": STAMP,
            "synthetic_fixture": True,
        }
        plan = {
            "record_id": ids["PLAN"],
            **scope,
            "candidate_id": ids["CAN"],
            "candidate_hash": digest(candidate),
            "arm": name,
            "mode": "synthetic_rehearsal",
            "created_at": STAMP,
        }
        lot = {
            "record_id": ids["LOT"],
            **scope,
            "design_id": ids["CAN"],
            "plan_id": ids["PLAN"],
            "recipe_version_id": ids["RCP"],
            "created_at": STAMP,
        }
        exposure = {
            "record_id": ids["EXP"],
            **scope,
            "design_id": ids["CAN"],
            "arm": name,
            "start_at": index.isoformat(),
            "end_at": None,
            "adherence": 0.95,
        }
        physical = {
            "case_id": case,
            "eye_id": f"EYE-{pid}-OD",
            "lot_id": ids["LOT"],
            "design_id": ids["CAN"],
            "exposure_start": index.isoformat(),
            "exposure_end": None,
        }
        # Use the real eye ID generated by the existing clinical domain.
        physical["eye_id"] = ClinicalDigitalThread(svc.store).ensure_eyes(pid)["OD"]
        disp = {
            "record_id": ids["DISP"],
            **scope,
            "lot_id": ids["LOT"],
            "start_at": index.isoformat(),
            "end_at": None,
            "research_exposure_id": ids["EXP"],
            "product_exposure_id": ids["PRODUCT"],
            "created_at": STAMP,
        }
        records = [
            ("v3_optical_candidate", ids["CAN"], candidate),
            ("v3_manufacturing_plan", ids["PLAN"], plan),
            ("v3_manufacturing_lot", ids["LOT"], lot),
            (
                "recipe_version",
                ids["RCP"],
                {
                    "design_id": ids["CAN"],
                    "parameters": {
                        "plan_id": ids["PLAN"],
                        "reference_optical_parameters": parameters,
                    },
                    "created_at": STAMP,
                },
            ),
            (
                "v3_manufacturing_qc",
                ids["QC"],
                {
                    "record_id": ids["QC"],
                    **scope,
                    "lot_id": ids["LOT"],
                    "passed": True,
                    "created_at": STAMP,
                },
            ),
            ("v3_exposure", ids["EXP"], exposure),
            ("product_exposure", ids["PRODUCT"], physical),
            ("v3_manufacturing_dispense", ids["DISP"], disp),
            ("v3_enrollment", ids["ENR"], en),
            (
                "v3_observation",
                ids["BASE"],
                {**scope, **baseline, "record_id": ids["BASE"]},
            ),
            (
                "v3_observation",
                ids["FOLLOW"],
                {**scope, **follow, "record_id": ids["FOLLOW"]},
            ),
        ]
        batch.extend(records)
        members.append(
            {
                **scope,
                "arm": name,
                "exclusions": [],
                "baseline": baseline,
                "followup": follow,
                "elapsed_days": (months_after(index, 12) - index).days,
                "enrollment": en,
                "study_events": [],
                "adherence": 0.95,
            }
        )
    svc.store.put_records_atomic(batch)
    for member in members:
        member["design_evidence"] = design_evidence(svc, member, index.isoformat())
    contract = MultiArmCohort(
        protocol_id=protocol["record_id"],
        cohort_name="Three-arm " + partition,
        eligibility_version="THREE-SYN-1",
        assignment="randomized",
        index_date=index,
        analysis_plan=protocol["analysis_plan"],
        members=[{k: m[k] for k in ("patient_id", "case_id", "eye")} for m in members],
    )
    frozen = {
        **contract.model_dump(mode="json"),
        "members": members,
        "dataset_hash": digest(members),
        "model_family": "multiarm_dr_v1",
        "synthetic_fixture": True,
    }
    return svc.save("cohort", "MCOH", frozen, "synthetic-fixture")["record_id"]


def policy_fixture(svc, n=90, design_signal=True, require_design=True, prefix="MAIN"):
    ids = [
        cohort_fixture(
            svc,
            prefix + "-" + part,
            n=n,
            seed=seed,
            design_signal=design_signal,
            site="EXTERNAL" if part == "external" else "DEVELOPMENT",
        )
        for part, seed in [("train", 11), ("test", 12), ("external", 13)]
    ]
    policy = MultiArmPolicy(
        name="Invented three arm locked policy",
        train_cohort_id=ids[0],
        test_cohort_id=ids[1],
        external_cohort_id=ids[2],
        evidence_kind="synthetic",
        minimum_patients_per_arm=20,
        max_group_calibration_error_mm=0.2,
        shrinkage=10,
        require_design_analysis=require_design,
        bootstrap_reps=200,
        permutation_reps=3,
        analysis_plan="Prespecified three-arm DR and nested predictive design-value study.",
        identification_assumptions="Invented random allocation with known probabilities, consistency and no interference.",
    )
    return adaptive.lock_policy(svc, policy, "author")


def shadow_fixture(svc, protocol_id, age=12, suffix="NEW", features=None):
    point = (
        dict(zip(adaptive.FEATURES, features))
        if features is not None
        else dict(
            age=age, baseline_al=24, baseline_se=-2, prior_al_slope=0.25, sex_code=0
        )
    )
    age, al, se, slope, sex = (point[k] for k in adaptive.FEATURES)
    pid = "SYN-THREE-SHADOW-" + suffix
    case = pid + "-CASE"
    scope = {"patient_id": pid, "case_id": case, "eye": "OD"}
    ClinicalDigitalThread(svc.store).create_case(
        patient_id=pid,
        case_id=case,
        site_id="PROSPECTIVE",
        indication_code="SYNTHETIC",
        clinician_id="SYNTHETIC",
    )
    svc.ingest(
        ObservationBatch(
            **scope,
            observations=[
                observation("2029-01-01", al - slope, se + 0.4),
                observation("2030-01-01", al, se),
            ],
        ),
        "synthetic-fixture",
    )
    en = enroll(
        svc,
        Enrollment(
            **scope,
            protocol_id=protocol_id,
            index_date="2030-01-01",
            eligible=True,
            assigned_arm="SA_ONLY",
            eligibility_reasons=["Invented prospective shadow patient"],
            age=age,
            baseline_al=float(al),
            baseline_se=float(se),
            prior_al_slope=float(slope),
            sex_code=int(sex),
            allocation_reference="SYN-THREE-SHADOW-ALLOCATION",
        ),
        "synthetic-fixture",
    )
    forecast = svc.forecast(
        Forecast(**scope, index_date="2030-01-01", untreated_history_confirmed=True),
        "synthetic-fixture",
    )
    plans = []
    for arm in ARMS:
        env = optical_envelope()
        if arm == "SA_ONLY":
            env["bounds"]["noise_height_um"] = [0, 0]
            env["bounds"]["fiber_height_um"] = [0, 0]
        elif arm == "SA_BN":
            env["bounds"]["fiber_height_um"] = [0, 0]
        else:
            env["bounds"]["fiber_height_um"] = [0.02, 0.1]
        envelope = svc.save("optical_envelope", "ENV", env, "engineer")
        job = svc.submit_optimizer(
            Optimization(
                **scope, envelope_id=envelope["record_id"], candidate_budget=8, seed=4
            ),
            "engineer",
        )
        result = svc.execute_optimizer(job["record_id"], "engineer")
        plan = manufacturing.create_plan(
            svc,
            manufacturing.ManufacturingPlan(
                **scope,
                prediction_id=forecast["prediction_id"],
                candidate_id=result["pareto_candidates"][0]["design_id"],
                mode="synthetic_rehearsal",
                arm=arm,
                material_code="SYNTHETIC",
                process_reference="SYNTHETIC-NOT-QUALIFIED",
                qc_requirements=[
                    {"name": "surface_error", "unit": "um", "lower": 0, "upper": 0.2}
                ],
            ),
            "engineer",
        )
        manufacturing.decide_plan(
            svc,
            manufacturing.ManufacturingDecision(
                plan_id=plan["record_id"],
                decision="approve",
                reason="Independent synthetic shadow plan review.",
                process_qualification_reference="SYNTHETIC-REVIEW",
            ),
            "reviewer",
        )
        plans.append(plan["record_id"])
    return {**scope, "enrollment_id": en["record_id"], "plan_ids": plans}


def staging_context(svc):
    """Fresh synthetic population and prospective support probes for HTTP tests."""
    ids = [
        cohort_fixture(
            svc,
            "HTTP-" + part,
            n=90,
            seed=seed,
            site="EXTERNAL" if part == "external" else "DEVELOPMENT",
        )
        for part, seed in [("train", 11), ("test", 12), ("external", 13)]
    ]
    train = svc.get("cohort", ids[0])
    protocol_id = train["protocol_id"]
    full = shadow_fixture(svc, protocol_id, suffix="HTTP-FULL")
    x = np.array(
        [[row["enrollment"][k] for k in adaptive.FEATURES] for row in train["members"]]
    )
    a = np.array([ARMS.index(row["arm"]) for row in train["members"]])
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1
    z = (x - mean) / scale
    partial = None
    baseless = None
    for point, point_z in zip(x, z):
        local = np.linalg.norm(z - point_z, axis=1) <= 2.5
        supported = [int(np.sum(local & (a == k))) >= 5 for k in range(3)]
        if supported[0] and sum(supported) == 2 and partial is None:
            partial = point
        if not supported[0] and baseless is None:
            baseless = point
    if partial is None or baseless is None:
        raise RuntimeError("Synthetic support probes unavailable")
    requests = []
    for cohort_id in ids:
        cohort = svc.get("cohort", cohort_id)
        request = {k: cohort[k] for k in MultiArmCohort.model_fields if k in cohort}
        request["members"] = [
            {k: r[k] for k in ("patient_id", "case_id", "eye")}
            for r in cohort["members"]
        ]
        requests.append(request)
    return {
        "three_arm_cohort_requests": requests,
        "three_arm_cohort_ids": ids,
        "three_arm_full_request": full,
        "three_arm_partial_request": shadow_fixture(
            svc, protocol_id, suffix="HTTP-PARTIAL", features=partial
        ),
        "three_arm_abstain_request": shadow_fixture(
            svc, protocol_id, suffix="HTTP-BASELESS", features=baseless
        ),
    }
