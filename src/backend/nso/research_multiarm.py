"""Three-arm DR learning with one common comparator; shadow only."""

from datetime import date, datetime, timezone
from typing import ClassVar, Literal
import numpy as np
from pydantic import Field, model_validator
from . import research_adaptive as binary
from .research import ResearchError, digest, now, transactional
from .research_contracts import Cohort
from .research_manufacturing import rows, approved_plan, synthetic_case

ARMS = ["SA_ONLY", "SA_BN", "SA_BN_FIBER"]
PARAMETERS = ["sa_um", "noise_height_um", "fiber_height_um", "fiber_angle_deg"]


class MultiArmCohort(Cohort):
    comparator: Literal["SA_ONLY"] = "SA_ONLY"
    intervention: Literal["SA_BN"] = "SA_BN"
    study_arms: list[Literal["SA_ONLY", "SA_BN", "SA_BN_FIBER"]] = Field(
        default_factory=lambda: ARMS.copy()
    )
    estimand: Literal["12_month_delta_al_mm"] = "12_month_delta_al_mm"

    @model_validator(mode="after")
    def common_comparator(self):
        if self.study_arms != ARMS:
            raise ValueError(
                "Use the canonical three-arm order with SA_ONLY comparator"
            )
        return self


class MultiArmPolicy(binary.AdaptivePolicy):
    assignment_probability: ClassVar[None] = None
    model_family: Literal["multiarm_dr_v1"] = "multiarm_dr_v1"
    arm_names: list[Literal["SA_ONLY", "SA_BN", "SA_BN_FIBER"]] = Field(
        default_factory=lambda: ARMS.copy()
    )
    estimand: Literal["12_month_delta_al_mm"] = "12_month_delta_al_mm"
    assignment_probabilities: dict[str, float] = Field(
        default_factory=lambda: {arm: 1 / 3 for arm in ARMS}
    )
    minimum_local_patients_per_arm: int = Field(default=5, ge=3, le=50)
    minimum_local_ess_per_arm: float = Field(default=4, ge=2, le=50)
    local_radius_sd: float = Field(default=2.5, ge=0.5, le=5)
    propensity_floor: float = Field(default=0.05, ge=0.01, le=0.2)
    design_features: list[
        Literal["sa_um", "noise_height_um", "fiber_height_um", "fiber_angle_deg"]
    ] = Field(default_factory=lambda: PARAMETERS.copy(), min_length=1, max_length=4)
    require_design_analysis: bool = False
    max_missing_design_fraction: float = Field(default=0.1, ge=0, le=0.25)
    diagnostic_ridge_alpha: float = Field(default=1, ge=0.01, le=100)
    bootstrap_reps: int = Field(default=300, ge=100, le=2000)
    permutation_reps: int = Field(default=5, ge=2, le=20)

    @model_validator(mode="after")
    def probabilities(self):
        p = self.assignment_probabilities
        if (
            self.arm_names != ARMS
            or set(p) != set(ARMS)
            or not np.isfinite(list(p.values())).all()
            or abs(sum(p.values()) - 1) > 1e-8
            or min(p.values()) < self.propensity_floor
        ):
            raise ValueError("Three positive allocation probabilities must sum to one")
        if len(set(self.design_features)) != len(self.design_features):
            raise ValueError("Design features must be unique")
        return self


def _before_index(record, index):
    value = record.get("created_at") or record.get("measured_at")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        return stamp < datetime.fromisoformat(index).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return False


def design_evidence(svc, member, index):
    """Only server-owned dispensed lot/recipe/QC records can supply features."""
    links = [
        d
        for d in svc.store.list_records("v3_manufacturing_dispense")
        if all(d[k] == member[k] for k in ("patient_id", "case_id", "eye"))
        and d["start_at"] <= index
        and (not d["end_at"] or d["end_at"] >= index)
    ]
    if len(links) != 1:
        return {"eligible": False, "reason": "MISSING_OR_AMBIGUOUS_DISPENSE_LINK"}
    link = links[0]
    lot = svc.get("manufacturing_lot", link["lot_id"])
    plan = svc.get("manufacturing_plan", lot["plan_id"])
    recipe = svc.store.get_record("recipe_version", lot["recipe_version_id"])
    candidate = svc.get("optical_candidate", plan["candidate_id"])
    qcs = rows(svc, "manufacturing_qc", "lot_id", lot["record_id"])
    actual = svc.get("exposure", link["research_exposure_id"])
    physical = svc.store.get_record("product_exposure", link["product_exposure_id"])
    eye = svc.store.get_record("eye", physical["eye_id"])
    matching = (
        all(
            all(record[k] == member[k] for k in ("patient_id", "case_id", "eye"))
            for record in (lot, plan)
        )
        and physical["case_id"] == member["case_id"]
        and eye["patient_id"] == member["patient_id"]
        and eye["laterality"] == member["eye"]
        and all(actual[k] == member[k] for k in ("patient_id", "case_id", "eye"))
        and actual["design_id"] == lot["design_id"]
        and actual["arm"] == plan["arm"]
        and actual["start_at"] == link["start_at"]
        and physical["lot_id"] == lot["record_id"]
        and physical["design_id"] == lot["design_id"]
        and recipe["design_id"] == lot["design_id"]
        and recipe["parameters"]["plan_id"] == plan["record_id"]
        and recipe["parameters"]["reference_optical_parameters"]
        == candidate["parameters"]
        and plan["candidate_hash"] == digest(candidate)
    )
    if not matching:
        raise ResearchError(
            "DESIGN_PROVENANCE_MISMATCH",
            "Dispensed design, eye, lot, recipe and research exposure must agree.",
        )
    future_qc_count = sum(not _before_index(q, index) for q in qcs)
    qcs = [q for q in qcs if _before_index(q, index)]
    if not qcs or any(not q["passed"] for q in qcs):
        return {"eligible": False, "reason": "MISSING_OR_FAILED_QC"}
    records = [link, lot, plan, recipe, candidate, *qcs]
    if not all(_before_index(r, index) for r in records):
        return {"eligible": False, "reason": "POST_INDEX_DESIGN_EVIDENCE"}
    return {
        "eligible": True,
        "dispensed_arm": plan["arm"],
        "parameters": {k: candidate["parameters"][k] for k in PARAMETERS},
        "source_ids": {
            "dispense": link["record_id"],
            "lot": lot["record_id"],
            "plan": plan["record_id"],
            "recipe_version": lot["recipe_version_id"],
            "candidate": candidate["record_id"],
            "qc": [q["record_id"] for q in qcs],
        },
        "source_hash": digest(records),
        "post_index_qc_ignored": future_qc_count,
        "pre_index": True,
        "feature_source": "server_frozen_dispensed_design_only",
    }


def freeze_cohort(svc, inp, actor):
    with svc.store.transaction():
        snapshot = svc.freeze_cohort(inp, actor)
        frozen = svc.get("cohort", snapshot["cohort_id"])
        for member in frozen["members"]:
            evidence = design_evidence(svc, member, frozen["index_date"])
            member["design_evidence"] = evidence
            if evidence["eligible"]:
                member["exclusions"] = [
                    r
                    for r in member["exclusions"]
                    if r != "LEGACY_EXPOSURE_REQUIRES_RECONCILIATION"
                ]
            if not member["exclusions"] and member["baseline"] and member["followup"]:
                member["delta_al_mm"] = (
                    member["followup"]["al_mm"] - member["baseline"]["al_mm"]
                )
        frozen["dataset_hash"] = digest(frozen["members"])
        # The precursor is preserved; new immutable snapshot includes design provenance.
        frozen["precursor_cohort_id"] = snapshot["cohort_id"]
        frozen["model_family"] = "multiarm_dr_v1"
        saved = svc.save("cohort", "MCOH", frozen, actor)
        return {
            "cohort_id": saved["record_id"],
            "dataset_hash": saved["dataset_hash"],
            "arms": ARMS,
            "comparator": ARMS[0],
            "estimand": inp.estimand,
            "members": len(saved["members"]),
            "design_linked_eyes": sum(
                m["design_evidence"]["eligible"] for m in saved["members"]
            ),
            "clinical_use_allowed": False,
        }


def overlap(p, a, policy, minimum=None):
    floor = policy["propensity_floor"]
    diagnostics = {}
    bounded = np.clip(p, floor, 1 - floor)
    # Clipping is only a finite numerical safeguard; unsupported arms fail first.
    minimum = minimum if minimum is not None else policy["minimum_patients_per_arm"]
    for k, arm in enumerate(ARMS):
        extreme = float(np.mean((p[:, k] < floor) | (p[:, k] > 1 - floor)))
        w = 1 / bounded[a == k, k]
        ess = float(w.sum() ** 2 / (w @ w)) if len(w) else 0
        diagnostics[arm] = {
            "patients": int(np.sum(a == k)),
            "effective_sample_size": ess,
            "extreme_propensity_fraction": extreme,
        }
        if (
            extreme > policy["max_extreme_propensity_fraction"]
            or len(w) < minimum
            or ess < minimum * 0.7
        ):
            raise ResearchError(
                "INSUFFICIENT_ARM_OVERLAP",
                f"Arm {arm} fails patient count, propensity or ESS gates.",
                409,
            )
    return bounded, diagnostics


def nuisance(train, target, policy, export=False):
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression, Ridge

    scaler = StandardScaler().fit(train["x"])
    x = scaler.transform(train["x"])
    tx = scaler.transform(target["x"])
    mu = np.column_stack(
        [
            Ridge(alpha=5)
            .fit(x[train["a"] == k], train["y"][train["a"] == k])
            .predict(tx)
            for k in range(3)
        ]
    )
    if train["assignment"] == "randomized":
        p = np.tile(
            [policy["assignment_probabilities"][arm] for arm in ARMS], (len(tx), 1)
        )
        artifact = {"kind": "randomized", "probabilities": p[0].tolist()}
    else:
        fitted = LogisticRegression(
            C=1, max_iter=1000, random_state=policy["seed"]
        ).fit(x, train["a"])
        p = fitted.predict_proba(tx)
        artifact = {
            "kind": "multinomial",
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": fitted.coef_.tolist(),
            "intercept": fitted.intercept_.tolist(),
        }
    return (p, mu, artifact) if export else (p, mu)


def dr_values(pop, p, mu):
    return mu + np.column_stack(
        [(pop["a"] == k) * (pop["y"] - mu[:, k]) / p[:, k] for k in range(3)]
    )


def unused_holdouts(svc, policy, cohorts):
    """Previously used patient outcomes cannot be called unseen validation again."""
    evaluation_ids = {r["patient_id"] for c in cohorts[1:] for r in c["members"]}
    for model in svc.store.list_records("v3_adaptive_model"):
        if evaluation_ids.intersection(model["patient_ids"]):
            raise ResearchError(
                "HOLDOUT_ALREADY_USED",
                "These validation patients were used by a prior model; freeze new independent holdouts.",
                409,
            )


@transactional
def train_multiarm(svc, inp, actor):
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge

    policy = svc.get("adaptive_policy", inp.policy_id)
    if rows(svc, "adaptive_model", "policy_id", inp.policy_id):
        raise ResearchError(
            "POLICY_ALREADY_TRAINED",
            "Lock a new policy for offline retraining; do not tune on these held-out results.",
            409,
        )
    cohorts = [
        svc.get("cohort", policy[k])
        for k in ("train_cohort_id", "test_cohort_id", "external_cohort_id")
    ]
    if [digest(c) for c in cohorts] != policy["cohort_hashes"]:
        raise ResearchError("ARTIFACT_CHANGED", "Frozen cohort integrity failed.", 409)
    unused_holdouts(svc, policy, cohorts)
    pops = [binary.load_population(svc, c, policy) for c in cohorts]
    development = pops[0]
    oof = np.zeros((len(development["ids"]), 3))
    prop = np.zeros_like(oof)
    for ti, vi in StratifiedKFold(3, shuffle=True, random_state=policy["seed"]).split(
        development["x"], development["a"]
    ):
        train = {**development, **{k: development[k][ti] for k in ("x", "y", "a")}}
        target = {**development, **{k: development[k][vi] for k in ("x", "y", "a")}}
        p, mu = nuisance(train, target, policy)
        p, _ = overlap(
            p,
            target["a"],
            policy,
            minimum=max(2, policy["minimum_patients_per_arm"] // 3),
        )
        oof[vi] = dr_values(target, p, mu)
        prop[vi] = p
    _, train_support = overlap(prop, development["a"], policy)
    effects = oof[:, 1:] - oof[:, [0]]
    scaler = StandardScaler().fit(development["x"])
    z = scaler.transform(development["x"])
    fitted = Ridge(alpha=policy["shrinkage"]).fit(z, effects)
    baseline = effects.mean(axis=0)
    baseline_arm = int(np.argmin(np.r_[0, baseline]))
    reports = {}
    gates = {}
    for split, pop in zip(("test", "external"), pops[1:]):
        p, mu = nuisance(development, pop, policy)
        p, diagnostics = overlap(p, pop["a"], policy)
        dr = dr_values(pop, p, mu)
        target = dr[:, 1:] - dr[:, [0]]
        tau = fitted.predict(scaler.transform(pop["x"]))
        contrasts = {}
        for j, arm in enumerate(ARMS[1:]):
            mse = float(np.mean((tau[:, j] - target[:, j]) ** 2))
            base_mse = float(np.mean((baseline[j] - target[:, j]) ** 2))
            groups = np.array_split(np.argsort(tau[:, j]), 3)
            calibration = [
                {
                    "patients": len(g),
                    "predicted_mm": float(tau[g, j].mean()),
                    "dr_pseudo_effect_mm": float(target[g, j].mean()),
                }
                for g in groups
            ]
            error = max(
                abs(g["predicted_mm"] - g["dr_pseudo_effect_mm"]) for g in calibration
            )
            improvement = 1 - mse / max(base_mse, 1e-12)
            from scipy.stats import norm

            ate_scores = target[:, j]
            se = float(ate_scores.std(ddof=1) / np.sqrt(len(ate_scores)))
            q = float(norm.ppf(1 - 0.05 / 4))
            contrasts[arm] = {
                "comparator": ARMS[0],
                "dr_pseudo_outcome_mse": mse,
                "constant_arm_effect_mse": base_mse,
                "relative_improvement": improvement,
                "group_calibration": calibration,
                "max_group_calibration_error_mm": error,
                "arm_effect_mm": float(ate_scores.mean()),
                "approx_simultaneous_95_interval_mm": [
                    float(ate_scores.mean() - q * se),
                    float(ate_scores.mean() + q * se),
                ],
            }
            gates[split + ":" + arm] = bool(
                improvement >= policy["minimum_relative_improvement"]
                and error <= policy["max_group_calibration_error_mm"]
            )
        predicted = np.column_stack([np.zeros(len(tau)), tau])
        chosen = np.argmin(predicted, axis=1)
        score = dr[np.arange(len(chosen)), chosen] - dr[:, baseline_arm]
        value = float(score.mean())
        se = float(score.std(ddof=1) / np.sqrt(len(score)))
        gates[split + ":policy_value"] = bool(value + 1.96 * se <= 0)
        reports[split] = {
            "patients": len(pop["ids"]),
            "comparator": ARMS[0],
            "estimand": policy["estimand"],
            "contrasts": contrasts,
            "arm_support": diagnostics,
            "policy_delta_al_mm_vs_constant_arm": value,
            "policy_delta_approx_95_interval": [value - 1.96 * se, value + 1.96 * se],
            "uncertainty": "Patient DR scores with fixed nuisance fits; contrast intervals use Bonferroni for two shared-control contrasts. Not individual effect CIs.",
        }
    from .research_incremental import evaluate_design_increment

    incremental = evaluate_design_increment(pops, cohorts, policy)
    if policy["require_design_analysis"] and incremental["status"] != "completed":
        raise ResearchError("DESIGN_ANALYSIS_UNAVAILABLE", incremental["reason"], 409)
    _, _, propensity = nuisance(development, development, policy, export=True)
    artifact = {
        "model_family": "multiarm_dr_v1",
        "policy_id": inp.policy_id,
        "policy_hash": digest(policy),
        "actor": actor,
        "evidence_kind": policy["evidence_kind"],
        "cohort_hashes": policy["cohort_hashes"],
        "patient_ids": sorted(binary.policy_patients(svc, policy)),
        "arms": policy["arms"],
        "arm_names": ARMS,
        "comparator": ARMS[0],
        "estimand": policy["estimand"],
        "feature_schema": binary.FEATURES,
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coef": fitted.coef_.tolist(),
        "intercept": fitted.intercept_.tolist(),
        "support_z": z.tolist(),
        "support_arms": development["a"].tolist(),
        "support_propensity": prop.tolist(),
        "propensity": propensity,
        "lower": development["x"].min(axis=0).tolist(),
        "upper": development["x"].max(axis=0).tolist(),
        "train_overlap": train_support,
        "report": reports,
        "incremental_design_report": incremental,
        "validation_passed": all(gates.values()),
        "gates": gates,
        "implementation_hash": binary.implementation_hash(),
        "clinical_use_allowed": False,
        "individual_effect_interval": None,
        "ranking_mode": "shadow_only",
        "trained_at": now(),
    }
    artifact["artifact_hash"] = digest(artifact)
    return svc.save("adaptive_model", "AMOD3", artifact, actor)


def local_support(model, x, policy):
    z = (x - model["mean"]) / model["scale"]
    lower, upper = np.array(model["lower"]), np.array(model["upper"])
    spread = np.maximum(upper - lower, 0.01)
    global_ood = bool(
        np.any(x < lower - 0.05 * spread) | np.any(x > upper + 0.05 * spread)
    )
    nearest = (
        np.linalg.norm(np.array(model["support_z"]) - z, axis=1)
        <= policy["local_radius_sd"]
    )
    a = np.array(model["support_arms"])
    p = model["propensity"]
    if p["kind"] == "randomized":
        probability = np.array(p["probabilities"])
    else:
        logits = np.array(p["coef"]) @ ((x - p["mean"]) / p["scale"]) + p["intercept"]
        logits -= logits.max()
        probability = np.exp(logits) / np.exp(logits).sum()
    training_p = np.array(model["support_propensity"])
    result = {}
    for k, arm in enumerate(ARMS):
        mask = nearest & (a == k)
        w = 1 / training_p[mask, k]
        ess = float(w.sum() ** 2 / (w @ w)) if len(w) else 0
        supported = bool(
            not global_ood
            and len(w) >= policy["minimum_local_patients_per_arm"]
            and ess >= policy["minimum_local_ess_per_arm"]
            and policy["propensity_floor"]
            <= probability[k]
            <= 1 - policy["propensity_floor"]
        )
        result[arm] = {
            "supported": supported,
            "local_patients": int(mask.sum()),
            "local_effective_sample_size": ess,
            "propensity": float(probability[k]),
            "reason": None
            if supported
            else "OUT_OF_DISTRIBUTION"
            if global_ood
            else "INSUFFICIENT_ARM_SUPPORT",
        }
    return result


def shadow_multiarm(svc, inp, actor, model):
    if synthetic_case(svc, inp) != (model["evidence_kind"] == "synthetic"):
        raise ResearchError(
            "EVIDENCE_MODE_MISMATCH",
            "Synthetic models cannot rank measured cases.",
            409,
        )
    if inp.patient_id in model["patient_ids"]:
        raise ResearchError(
            "IN_SAMPLE_SHADOW_FORBIDDEN", "Shadow ranking requires a new patient.", 409
        )
    enrollment = svc.get("enrollment", inp.enrollment_id)
    if any(enrollment[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")):
        raise ResearchError(
            "FORBIDDEN", "Enrollment does not match this patient/eye.", 403
        )
    policy = svc.get("adaptive_policy", model["policy_id"])
    training_protocol = svc.get(
        "protocol", svc.get("cohort", policy["train_cohort_id"])["protocol_id"]
    )
    protocol = svc.get("protocol", enrollment["protocol_id"])
    if any(
        protocol[k] != training_protocol[k]
        for k in ("assignment", "estimand", "covariates")
    ):
        raise ResearchError(
            "PROTOCOL_MISMATCH",
            "Shadow enrollment must use the validated protocol definitions.",
        )
    index = date.fromisoformat(enrollment["index_date"])
    if model["evidence_kind"] == "measured" and index < date.today():
        raise ResearchError(
            "PROSPECTIVE_INDEX_REQUIRED", "Measured shadow ranking cannot be backdated."
        )
    if any(
        l["patient_id"] == inp.patient_id
        and l["case_id"] == inp.case_id
        and l["eye"] == inp.eye
        and l["index_date"] == index.isoformat()
        for l in rows(svc, "adaptive_shadow", "model_id", model["record_id"])
    ):
        raise ResearchError(
            "DUPLICATE_SHADOW_INDEX", "This patient/eye/index is already logged.", 409
        )
    baseline = [
        r
        for r in svc.observations(inp)
        if r["visit_at"] == index.isoformat()
        and r["quality_flag"] == "ACCEPTED"
        and r["al_status"] == "measured"
        and r["se_status"] == "measured"
    ]
    if (
        not baseline
        or abs(baseline[0]["al_mm"] - enrollment["baseline_al"]) > 1e-6
        or abs(baseline[0]["se_d"] - enrollment["baseline_se"]) > 1e-6
        or not enrollment["eligible"]
    ):
        raise ResearchError(
            "BASELINE_MISMATCH", "An eligible matching measured baseline is required."
        )
    x = np.array([enrollment[k] for k in binary.FEATURES], dtype=float)
    support = local_support(model, x, policy)
    effects = np.r_[
        0,
        np.array(model["coef"]) @ ((x - model["mean"]) / model["scale"])
        + model["intercept"],
    ]
    candidates = []
    for plan_id in inp.plan_ids:
        plan, approval = approved_plan(svc, plan_id)
        if any(plan[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")):
            raise ResearchError(
                "FORBIDDEN",
                "Every candidate must match the patient, case and eye.",
                403,
            )
        if plan["arm"] not in ARMS or plan["mode"] != (
            "synthetic_rehearsal"
            if model["evidence_kind"] == "synthetic"
            else "measured_research"
        ):
            raise ResearchError(
                "UNSUPPORTED_ARM",
                "Candidate evidence mode or arm does not match the model.",
            )
        prediction = svc.get("prediction", plan["prediction_id"])
        if prediction["index_date"] != index.isoformat():
            raise ResearchError(
                "INDEX_MISMATCH",
                "Every candidate plan must use the shadow baseline index.",
            )
        candidate = svc.get("optical_candidate", plan["candidate_id"])
        k = ARMS.index(plan["arm"])
        if support[plan["arm"]]["supported"]:
            candidates.append(
                {
                    "plan_id": plan_id,
                    "candidate_id": plan["candidate_id"],
                    "arm": plan["arm"],
                    "optical_quality": candidate["metrics"]["strehl"],
                    "approval_id": approval["record_id"],
                    "research_difference_vs_comparator_mm": float(effects[k]),
                }
            )
    provided = {svc.get("manufacturing_plan", p)["arm"] for p in inp.plan_ids}
    if provided != set(ARMS):
        raise ResearchError(
            "THREE_ARM_CANDIDATES_REQUIRED",
            "Supply feasible approved candidates for all three arms.",
        )
    if not support[ARMS[0]]["supported"]:
        candidates = []
        status = "abstained"
        reason = "UNSUPPORTED_COMPARATOR"
    elif len({c["arm"] for c in candidates}) < 2:
        candidates = []
        status = "abstained"
        reason = "INSUFFICIENT_ARM_SUPPORT"
    else:
        complete = all(s["supported"] for s in support.values())
        status = "shadow_logged" if complete else "partial_shadow_logged"
        reason = None if complete else "ARM_ABSTENTION"
        candidates.sort(
            key=lambda c: (
                c["research_difference_vs_comparator_mm"],
                -c["optical_quality"],
                c["candidate_id"],
            )
        )
    return svc.save(
        "adaptive_shadow",
        "ASH3",
        {
            **inp.model_dump(),
            "model_id": model["record_id"],
            "artifact_hash": model["artifact_hash"],
            "policy_id": model["policy_id"],
            "model_family": "multiarm_dr_v1",
            "index_date": index.isoformat(),
            "features": x.tolist(),
            "sex_code": enrollment["sex_code"],
            "baseline_al": enrollment["baseline_al"],
            "status": status,
            "reason": reason,
            "arm_support": support,
            "comparator": ARMS[0],
            "estimand": model["estimand"],
            "ranking_complete": status == "shadow_logged",
            "candidates": candidates,
            "individual_effect_interval": None,
            "actual_assignment_changed": False,
            "manufacturing_authorized": False,
            "clinical_use_allowed": False,
            "synthetic": model["evidence_kind"] == "synthetic",
            "issued_at": now(),
        },
        actor,
    )
