"""V3.1 offline DR learner and governed shadow-only arm ranking.

This is an independent shrunken linear DR prototype, not EconML or MPPM.
Pseudo-outcome diagnostics do not identify an individual's counterfactual effect.
"""

from datetime import date
import hashlib
from pathlib import Path
from typing import Literal
import numpy as np
from pydantic import Field, model_validator
from .research import ResearchError, digest, now
from .research_contracts import Contract, PatientScope, Observation
from .research_manufacturing import rows, approved_plan, synthetic_case

FEATURES = ["age", "baseline_al", "baseline_se", "prior_al_slope", "sex_code"]


def implementation_hash():
    sources = [
        Path(__file__),
        Path(__file__).with_name("research_multiarm.py"),
        Path(__file__).with_name("research_incremental.py"),
    ]
    return hashlib.sha256(
        b"".join(p.read_bytes() for p in sources if p.exists())
    ).hexdigest()


class AdaptivePolicy(Contract):
    name: str = Field(min_length=5, max_length=120)
    train_cohort_id: str
    test_cohort_id: str
    external_cohort_id: str
    holdout: Literal["external_site", "temporal"] = "external_site"
    evidence_kind: Literal["synthetic", "measured"]
    minimum_patients_per_arm: int = Field(default=30, ge=10, le=250)
    minimum_relative_improvement: float = Field(default=0.05, ge=0.01, le=0.9)
    max_group_calibration_error_mm: float = Field(default=0.1, gt=0, le=0.5)
    max_missing_fraction: float = Field(default=0.1, ge=0, le=0.25)
    max_extreme_propensity_fraction: float = Field(default=0.05, ge=0, le=0.1)
    shrinkage: float = Field(default=20, ge=1, le=1000)
    seed: int = Field(default=31, ge=0, le=2**31 - 1)
    assignment_probability: float = Field(default=0.5, ge=0.2, le=0.8)
    analysis_plan: str = Field(min_length=30, max_length=4000)
    identification_assumptions: str = Field(min_length=30, max_length=4000)
    prior_model_id: str | None = None


class AdaptiveTrain(Contract):
    policy_id: str


class AdaptiveReview(Contract):
    model_id: str
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=20, max_length=2000)
    scientific_review_reference: str = Field(min_length=5, max_length=200)
    ethics_reference: str | None = Field(default=None, min_length=5, max_length=200)
    assignment_review_reference: str | None = Field(
        default=None, min_length=5, max_length=200
    )


class ShadowDeployment(Contract):
    model_id: str
    review_id: str
    reason: str = Field(min_length=20, max_length=2000)
    rollback_to_deployment_id: str | None = None


class ShadowRequest(PatientScope):
    enrollment_id: str
    plan_ids: list[str] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.plan_ids)) != len(self.plan_ids):
            raise ValueError("Duplicate plan IDs")
        return self


class ShadowOutcome(Contract):
    shadow_id: str
    observed_arm: str
    observation: Observation
    adherence: float = Field(ge=0, le=1)
    source_reference: str = Field(min_length=5, max_length=200)


def cohort_patients(svc, cohort_id):
    return {r["patient_id"] for r in svc.get("cohort", cohort_id)["members"]}


def policy_patients(svc, policy):
    return set.union(
        *(
            cohort_patients(svc, policy[k])
            for k in ("train_cohort_id", "test_cohort_id", "external_cohort_id")
        )
    )


def load_population(svc, cohort, policy):
    protocol = (
        svc.get("protocol", cohort["protocol_id"])
        if cohort.get("protocol_id")
        else None
    )
    if not protocol or protocol["analysis_population"] != "intention_to_treat":
        raise ResearchError(
            "LOCKED_ITT_PROTOCOL_REQUIRED",
            "A locked intention-to-treat protocol is required for the DR prototype.",
        )
    arm_names = policy.get("arm_names", [cohort["comparator"], cohort["intervention"]])
    grouped, missing, sites, endpoint_dates = {}, set(), set(), []
    for member in cohort["members"]:
        pid = member["patient_id"]
        case = svc.case(
            PatientScope(**{k: member[k] for k in ("patient_id", "case_id", "eye")})
        )
        if (case.get("indication_code") == "SYNTHETIC") != (
            policy["evidence_kind"] == "synthetic"
        ):
            raise ResearchError(
                "EVIDENCE_MODE_MISMATCH",
                "Cohort evidence kind does not match its case provenance.",
            )
        sites.add(case["site_id"])
        enrollment, base, follow = (
            member.get("enrollment"),
            member.get("baseline"),
            member.get("followup"),
        )
        reasons = set(member["exclusions"])
        if protocol["assignment"] == "randomized":
            reasons -= {"TREATMENT_SWITCH_OR_RESTART", "DISCONTINUED_BEFORE_ENDPOINT"}
        if (
            not enrollment
            or not enrollment["eligible"]
            or not base
            or not follow
            or reasons
        ):
            missing.add(pid)
            continue
        if (
            any(
                r["al_status"] != "measured" or r["quality_flag"] != "ACCEPTED"
                for r in (base, follow)
            )
            or base["se_status"] != "measured"
        ):
            missing.add(pid)
            continue
        if (
            enrollment["index_date"] != cohort["index_date"]
            or abs(enrollment["baseline_al"] - base["al_mm"]) > 1e-6
            or abs(enrollment["baseline_se"] - base["se_d"]) > 1e-6
        ):
            raise ResearchError(
                "BASELINE_MISMATCH", "Frozen baseline and enrollment do not match."
            )
        if not 335 <= member["elapsed_days"] <= 395:
            raise ResearchError(
                "INVALID_HORIZON",
                "CATE prototype requires measured outcomes around twelve months.",
            )
        if (
            policy["evidence_kind"] == "measured"
            and date.fromisoformat(follow["visit_at"]) > date.today()
        ):
            raise ResearchError(
                "FUTURE_OUTCOME", "Measured training endpoints cannot be in the future."
            )
        randomized = protocol["assignment"] == "randomized"
        arm = enrollment["assigned_arm"] if randomized else member["arm"]
        if arm not in arm_names:
            missing.add(pid)
            continue
        if randomized and not enrollment.get("allocation_reference"):
            raise ResearchError(
                "ALLOCATION_REFERENCE_REQUIRED",
                "RCT allocation provenance is required.",
            )
        x = [enrollment.get(k) for k in FEATURES]
        if any(v is None for v in x):
            missing.add(pid)
            continue
        if any(e["severity"] == "severe" for e in member.get("study_events", [])):
            missing.add(pid)
            continue
        a = arm_names.index(arm)
        row = grouped.setdefault(
            pid, {"a": a, "x": [], "y": [], "sex": enrollment["sex_code"]}
        )
        if row["a"] != a:
            raise ResearchError(
                "SPLIT_EYE_ASSIGNMENT",
                "Patient-level training cannot use split-eye assignment.",
            )
        row["x"].append(x)
        row["y"].append(follow["al_mm"] - base["al_mm"])
        endpoint_dates.append(follow["visit_at"])
    # One incomplete eye excludes the entire patient; never silently complete-case only one eye.
    for pid in missing:
        grouped.pop(pid, None)
    total = len({m["patient_id"] for m in cohort["members"]})
    if len(missing) / max(total, 1) > policy["max_missing_fraction"]:
        raise ResearchError(
            "MISSINGNESS_GATE_FAILED",
            "Missing/switching/ineligible patients exceed the prespecified limit.",
            409,
        )
    ids = sorted(grouped)
    x = np.array([np.mean(grouped[p]["x"], axis=0) for p in ids])
    y = np.array([np.mean(grouped[p]["y"]) for p in ids])
    a = np.array([grouped[p]["a"] for p in ids], dtype=int)
    if (
        min(np.sum(a == k) for k in range(len(arm_names)))
        < policy["minimum_patients_per_arm"]
    ):
        raise ResearchError(
            "INSUFFICIENT_SUPPORT", "Too few independent patients per arm.", 409
        )
    return {
        "ids": ids,
        "x": x,
        "y": y,
        "a": a,
        "sites": sites,
        "last_outcome": max(endpoint_dates),
        "index": cohort["index_date"],
        "missing_patients": len(missing),
        "sex": np.array([grouped[p]["sex"] for p in ids]),
        "assignment": protocol["assignment"],
    }


def lock_policy(svc, inp, actor):
    with svc.store.transaction():
        data = inp.model_dump(mode="json")
        cohorts = [
            svc.get("cohort", data[k])
            for k in ("train_cohort_id", "test_cohort_id", "external_cohort_id")
        ]
        if len({c["record_id"] for c in cohorts}) != 3:
            raise ResearchError(
                "PATIENT_LEAKAGE", "Three distinct frozen cohorts required."
            )
        ids = [cohort_patients(svc, c["record_id"]) for c in cohorts]
        if any(ids[i] & ids[j] for i, j in ((0, 1), (0, 2), (1, 2))):
            raise ResearchError(
                "PATIENT_LEAKAGE", "A patient cannot appear in more than one partition."
            )
        if data.get("arm_names") and any(
            c.get("study_arms") != data["arm_names"] for c in cohorts
        ):
            raise ResearchError(
                "ESTIMAND_MISMATCH",
                "Every cohort must freeze the same three arms and comparator.",
            )
        arms = {
            (
                c["comparator"],
                c["intervention"],
                c["assignment"],
                c["eligibility_version"],
            )
            for c in cohorts
        }
        if len(arms) != 1:
            raise ResearchError(
                "ESTIMAND_MISMATCH",
                "Cohort treatment arms, eligibility and assignment must agree.",
            )
        if data.get("model_family") == "multiarm_dr_v1":
            from .research_multiarm import unused_holdouts

            unused_holdouts(svc, data, cohorts)
        pops = [load_population(svc, c, data) for c in cohorts]
        protocols = [svc.get("protocol", c["protocol_id"]) for c in cohorts]
        if any(not set(FEATURES).issubset(p["covariates"]) for p in protocols):
            raise ResearchError(
                "FEATURE_PROTOCOL_MISMATCH",
                "All learner features must be prespecified in every partition protocol.",
            )
        for field in (
            "estimand",
            "covariates",
            "missingness_plan",
            "switching_plan",
            "analysis_plan",
        ):
            if len({digest(p[field]) for p in protocols}) != 1:
                raise ResearchError(
                    "PROTOCOL_MISMATCH",
                    "Partition protocols must use the same locked analysis definitions.",
                )
        if data["holdout"] == "external_site" and pops[2]["sites"] & (
            pops[0]["sites"] | pops[1]["sites"]
        ):
            raise ResearchError(
                "SITE_LEAKAGE", "External-site holdout must use independent sites."
            )
        if (
            data["holdout"] == "temporal"
            and max(pops[0]["last_outcome"], pops[1]["last_outcome"])
            >= pops[2]["index"]
        ):
            raise ResearchError(
                "TEMPORAL_LEAKAGE",
                "All development endpoints must precede the later validation index.",
            )
        if inp.prior_model_id:
            svc.get("adaptive_model", inp.prior_model_id)
        return svc.save(
            "adaptive_policy",
            "APOL",
            {
                **data,
                "cohort_hashes": [digest(c) for c in cohorts],
                "feature_schema": FEATURES,
                "arms": {
                    "comparator": cohorts[0]["comparator"],
                    "intervention": cohorts[0]["intervention"],
                    **(
                        {"intervention_2": data["arm_names"][2]}
                        if data.get("arm_names")
                        else {}
                    ),
                },
                "clinical_use_allowed": False,
            },
            actor,
        )


def nuisance(train, target, policy):
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge, LogisticRegression

    scaler = StandardScaler().fit(train["x"])
    x, tx = scaler.transform(train["x"]), scaler.transform(target["x"])
    mu = np.column_stack(
        [
            Ridge(alpha=5)
            .fit(x[train["a"] == a], train["y"][train["a"] == a])
            .predict(tx)
            for a in (0, 1)
        ]
    )
    if train["assignment"] == "randomized":
        p = np.full(len(tx), policy["assignment_probability"])
    else:
        p = (
            LogisticRegression(C=1, max_iter=1000, random_state=policy["seed"])
            .fit(x, train["a"])
            .predict_proba(tx)[:, 1]
        )
    return p, mu


def dr_values(pop, p, mu):
    a, y = pop["a"], pop["y"]
    return np.column_stack(
        [
            mu[:, 0] + (1 - a) * (y - mu[:, 0]) / (1 - p),
            mu[:, 1] + a * (y - mu[:, 1]) / p,
        ]
    )


def support(p, a, policy):
    extreme = float(np.mean((p < 0.05) | (p > 0.95)))
    bounded = np.clip(p, 0.05, 0.95)
    w = np.where(a == 1, 1 / bounded, 1 / (1 - bounded))
    ess = [float(w[a == k].sum() ** 2 / np.sum(w[a == k] ** 2)) for k in (0, 1)]
    if (
        extreme > policy["max_extreme_propensity_fraction"]
        or min(ess) < policy["minimum_patients_per_arm"] * 0.7
    ):
        raise ResearchError(
            "INSUFFICIENT_OVERLAP",
            "Propensity support or effective sample size failed.",
            409,
        )
    return bounded, {"extreme_fraction": extreme, "ess_comparator_intervention": ess}


def train(svc, inp, actor):
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge

    policy = svc.get("adaptive_policy", inp.policy_id)
    if policy.get("model_family") == "multiarm_dr_v1":
        from .research_multiarm import train_multiarm

        return train_multiarm(svc, inp, actor)
    if rows(svc, "adaptive_model", "policy_id", inp.policy_id):
        raise ResearchError(
            "POLICY_ALREADY_TRAINED",
            "Lock a new policy/version for offline retraining; holdout reuse requires scientific review.",
            409,
        )
    cohorts = [
        svc.get("cohort", policy[k])
        for k in ("train_cohort_id", "test_cohort_id", "external_cohort_id")
    ]
    if [digest(c) for c in cohorts] != policy["cohort_hashes"]:
        raise ResearchError(
            "ARTIFACT_CHANGED", "Frozen cohort integrity check failed.", 409
        )
    pops = [load_population(svc, c, policy) for c in cohorts]
    development = pops[0]
    oof = np.zeros((len(development["ids"]), 2))
    prop = np.zeros(len(oof))
    for ti, vi in StratifiedKFold(3, shuffle=True, random_state=policy["seed"]).split(
        development["x"], development["a"]
    ):
        fold = {**development, **{k: development[k][ti] for k in ("x", "y", "a")}}
        target = {**development, **{k: development[k][vi] for k in ("x", "y", "a")}}
        p, mu = nuisance(fold, target, policy)
        bounded, _ = support(
            p,
            target["a"],
            {
                **policy,
                "minimum_patients_per_arm": max(
                    1, policy["minimum_patients_per_arm"] // 3
                ),
            },
        )
        oof[vi] = dr_values(target, bounded, mu)
        prop[vi] = p
    _, overlap = support(prop, development["a"], policy)
    pseudo = oof[:, 1] - oof[:, 0]
    scaler = StandardScaler().fit(development["x"])
    z = scaler.transform(development["x"])
    learner = Ridge(alpha=policy["shrinkage"]).fit(z, pseudo)
    baseline = float(pseudo.mean())
    baseline_arm = int(baseline < 0)
    report = {}
    gates = {}
    for split, pop in zip(("test", "external"), pops[1:]):
        p, mu = nuisance(development, pop, policy)
        p, diag = support(p, pop["a"], policy)
        values = dr_values(pop, p, mu)
        target = values[:, 1] - values[:, 0]
        tau = learner.predict(scaler.transform(pop["x"]))
        mse = float(np.mean((tau - target) ** 2))
        base_mse = float(np.mean((baseline - target) ** 2))
        improvement = 1 - mse / max(base_mse, 1e-12)
        groups = np.array_split(np.argsort(tau), 3)
        calibration = [
            {
                "patients": len(g),
                "predicted_effect_mm": float(np.mean(tau[g])),
                "dr_pseudo_effect_mm": float(np.mean(target[g])),
            }
            for g in groups
        ]
        cal_error = max(
            abs(g["predicted_effect_mm"] - g["dr_pseudo_effect_mm"])
            for g in calibration
        )
        chosen = (tau < 0).astype(int)
        diff = values[np.arange(len(chosen)), chosen] - values[:, baseline_arm]
        estimate = float(diff.mean())
        se = float(diff.std(ddof=1) / np.sqrt(len(diff)))
        report[split] = {
            "patients": len(pop["ids"]),
            "missing_patients": pop["missing_patients"],
            "analysis_population": "eligible patients with complete measured endpoints; randomized assigned arm retained",
            "subgroup_calibration": {
                name: {
                    "patients": int(mask.sum()),
                    "predicted_effect_mm": float(np.mean(tau[mask]))
                    if mask.any()
                    else None,
                    "dr_pseudo_effect_mm": float(np.mean(target[mask]))
                    if mask.any()
                    else None,
                }
                for name, mask in {
                    "age_under_12": pop["x"][:, 0] < 12,
                    "age_12_plus": pop["x"][:, 0] >= 12,
                    "sex_0": pop["sex"] == 0,
                    "sex_1": pop["sex"] == 1,
                }.items()
            },
            "dr_pseudo_outcome_mse": mse,
            "arm_baseline_mse": base_mse,
            "relative_improvement": improvement,
            "group_calibration": calibration,
            "max_group_calibration_error_mm": cal_error,
            "policy_delta_al_mm_vs_constant_arm": estimate,
            "policy_delta_approx_95_interval": [
                estimate - 1.96 * se,
                estimate + 1.96 * se,
            ],
            "overlap": diag,
            "uncertainty": "Patient-level held-out DR score normal approximation with fixed nuisance fits; no individual effect CI.",
        }
        gates[split] = bool(
            improvement >= policy["minimum_relative_improvement"]
            and cal_error <= policy["max_group_calibration_error_mm"]
            and estimate + 1.96 * se <= 0
        )
    artifact = {
        "policy_id": inp.policy_id,
        "policy_hash": digest(policy),
        "actor": actor,
        "evidence_kind": policy["evidence_kind"],
        "cohort_hashes": policy["cohort_hashes"],
        "patient_ids": sorted(policy_patients(svc, policy)),
        "arms": policy["arms"],
        "feature_schema": FEATURES,
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coef": learner.coef_.tolist(),
        "intercept": float(learner.intercept_),
        "support_z": z.tolist(),
        "support_arms": development["a"].tolist(),
        "lower": development["x"].min(axis=0).tolist(),
        "upper": development["x"].max(axis=0).tolist(),
        "arm_baseline_effect_mm": baseline,
        "train_overlap": overlap,
        "report": report,
        "validation_passed": all(gates.values()),
        "gates": gates,
        "implementation_hash": implementation_hash(),
        "design_parameter_incremental_value": "not evaluated without linked dispensed design data; ranking uses arm contrast plus optical tie-break only",
        "clinical_use_allowed": False,
        "individual_effect_interval": None,
        "ranking_mode": "shadow_only",
        "identification_assumptions": policy["identification_assumptions"],
        "trained_at": now(),
    }
    artifact["artifact_hash"] = digest(artifact)
    return svc.save("adaptive_model", "AMOD", artifact, actor)


def reviews(svc, model_id):
    history = rows(svc, "adaptive_review", "model_id", model_id)
    return max(history, key=lambda r: r["sequence"]) if history else None


def review(svc, inp, actor):
    with svc.store.transaction():
        model = svc.get("adaptive_model", inp.model_id)
        if inp.decision == "approve":
            if actor == model["actor"]:
                raise ResearchError(
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "Model authors cannot approve themselves.",
                    403,
                )
            if (
                not model["validation_passed"]
                or model["implementation_hash"] != implementation_hash()
            ):
                raise ResearchError(
                    "VALIDATION_GATE_FAILED",
                    "Prespecified held-out gates or implementation integrity failed.",
                    409,
                )
            if model["evidence_kind"] == "measured" and (
                not inp.ethics_reference or not inp.assignment_review_reference
            ):
                raise ResearchError(
                    "SCIENTIFIC_SIGNOFF_REQUIRED",
                    "Measured shadow deployment requires ethics and assignment review references.",
                    409,
                )
        previous = reviews(svc, inp.model_id)
        return svc.save(
            "adaptive_review",
            "AREV",
            {
                **inp.model_dump(),
                "model_hash": digest(model),
                "actor": actor,
                "sequence": previous["sequence"] + 1 if previous else 1,
                "clinical_use_allowed": False,
                "ranking_mode": "shadow_only",
                "references_independently_verified": False,
            },
            actor,
        )


def deployments(svc):
    return sorted(
        svc.store.list_records("v3_adaptive_deployment"), key=lambda r: r["sequence"]
    )


def deploy(svc, inp, actor):
    with svc.store.transaction():
        model = svc.get("adaptive_model", inp.model_id)
        approval = reviews(svc, inp.model_id)
        if (
            not approval
            or approval["record_id"] != inp.review_id
            or approval["decision"] != "approve"
            or approval["model_hash"] != digest(model)
        ):
            raise ResearchError(
                "APPROVAL_WITHDRAWN", "Current matching model approval required.", 409
            )
        if actor in (approval["actor"], model["actor"]):
            raise ResearchError(
                "SEPARATION_OF_DUTIES", "Separate deployment operator required.", 403
            )
        if model["implementation_hash"] != implementation_hash():
            raise ResearchError(
                "STALE_IMPLEMENTATION",
                "Retrain/revalidate after implementation changes.",
                409,
            )
        history = deployments(svc)
        if inp.rollback_to_deployment_id:
            old = svc.get("adaptive_deployment", inp.rollback_to_deployment_id)
            if old["model_id"] != inp.model_id:
                raise ResearchError(
                    "ROLLBACK_MISMATCH", "Rollback target model does not match."
                )
        return svc.save(
            "adaptive_deployment",
            "ADEP",
            {
                **inp.model_dump(),
                "actor": actor,
                "sequence": len(history) + 1,
                "previous_deployment_id": history[-1]["record_id"] if history else None,
                "ranking_mode": "shadow_only",
                "clinical_use_allowed": False,
            },
            actor,
        )


def active_model(svc):
    history = deployments(svc)
    if not history:
        raise ResearchError("NO_SHADOW_DEPLOYMENT", "No shadow model is deployed.", 409)
    deployment = history[-1]
    model = svc.get("adaptive_model", deployment["model_id"])
    approval = reviews(svc, model["record_id"])
    if (
        not approval
        or approval["decision"] != "approve"
        or approval["record_id"] != deployment["review_id"]
        or approval["model_hash"] != digest(model)
        or model["implementation_hash"] != implementation_hash()
    ):
        raise ResearchError(
            "APPROVAL_WITHDRAWN",
            "The deployed shadow model is no longer approved/current.",
            409,
        )
    return model


def shadow(svc, inp, actor):
    with svc.store.transaction():
        model = active_model(svc)
        if model.get("model_family") == "multiarm_dr_v1":
            from .research_multiarm import shadow_multiarm

            return shadow_multiarm(svc, inp, actor, model)
        is_synthetic = synthetic_case(svc, inp)
        if is_synthetic != (model["evidence_kind"] == "synthetic"):
            raise ResearchError(
                "EVIDENCE_MODE_MISMATCH",
                "Synthetic models only serve synthetic rehearsals.",
                409,
            )
        if inp.patient_id in model["patient_ids"]:
            raise ResearchError(
                "IN_SAMPLE_SHADOW_FORBIDDEN",
                "Shadow evaluation requires a new, held-out patient.",
                409,
            )
        enrollment = svc.get("enrollment", inp.enrollment_id)
        if any(
            enrollment[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")
        ):
            raise ResearchError(
                "FORBIDDEN", "Enrollment does not match this patient/eye.", 403
            )
        policy = svc.get("adaptive_policy", model["policy_id"])
        training_protocol = svc.get(
            "protocol", svc.get("cohort", policy["train_cohort_id"])["protocol_id"]
        )
        new_protocol = svc.get("protocol", enrollment["protocol_id"])
        if any(
            new_protocol[k] != training_protocol[k]
            for k in ("assignment", "estimand", "covariates")
        ):
            raise ResearchError(
                "PROTOCOL_MISMATCH",
                "Shadow enrollment must follow the validated assignment, estimand and feature protocol.",
            )
        index = date.fromisoformat(enrollment["index_date"])
        if any(
            l["patient_id"] == inp.patient_id
            and l["case_id"] == inp.case_id
            and l["eye"] == inp.eye
            and l["index_date"] == index.isoformat()
            for l in rows(svc, "adaptive_shadow", "model_id", model["record_id"])
        ):
            raise ResearchError(
                "DUPLICATE_SHADOW_INDEX",
                "This patient/eye/index is already logged for this model.",
                409,
            )
        if not is_synthetic and index < date.today():
            raise ResearchError(
                "PROSPECTIVE_INDEX_REQUIRED",
                "Measured shadow logging cannot be backdated.",
            )
        from .research_contracts import PatientScope as Scope

        observations = svc.observations(
            Scope(patient_id=inp.patient_id, case_id=inp.case_id, eye=inp.eye)
        )
        base = [
            r
            for r in observations
            if r["visit_at"] == index.isoformat()
            and r["quality_flag"] == "ACCEPTED"
            and r["al_status"] == "measured"
            and r["se_status"] == "measured"
        ]
        if (
            not base
            or abs(base[0]["al_mm"] - enrollment["baseline_al"]) > 1e-6
            or abs(base[0]["se_d"] - enrollment["baseline_se"]) > 1e-6
        ):
            raise ResearchError(
                "BASELINE_MISMATCH",
                "Accepted measured baseline must match the enrollment.",
            )
        x = np.array([enrollment[k] for k in FEATURES], dtype=float)
        if not enrollment["eligible"] or not np.isfinite(x).all():
            raise ResearchError(
                "INSUFFICIENT_HISTORY", "Eligible complete pre-index features required."
            )
        lower, upper = np.array(model["lower"]), np.array(model["upper"])
        spread = np.maximum(upper - lower, 0.01)
        ood = bool(
            np.any(x < lower - 0.05 * spread) or np.any(x > upper + 0.05 * spread)
        )
        z = (x - model["mean"]) / model["scale"]
        nearby = np.linalg.norm(np.array(model["support_z"]) - z, axis=1) <= 2.5
        a = np.array(model["support_arms"])
        ood |= min(np.sum(nearby & (a == k)) for k in (0, 1)) < 5
        # Conservative local arm support using retained training covariate summaries.
        tau = (
            float(
                np.dot((x - model["mean"]) / model["scale"], model["coef"])
                + model["intercept"]
            )
            if not ood
            else None
        )
        candidates = []
        for plan_id in inp.plan_ids:
            plan, approval = approved_plan(svc, plan_id)
            if any(
                plan[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")
            ):
                raise ResearchError(
                    "FORBIDDEN",
                    "Candidate plans must match this patient/case/eye.",
                    403,
                )
            if (
                plan["mode"]
                != ("synthetic_rehearsal" if is_synthetic else "measured_research")
                or plan["arm"] not in model["arms"].values()
            ):
                raise ResearchError(
                    "UNSUPPORTED_ARM",
                    "Plans must use the validated arms and matching evidence mode.",
                )
            candidate = svc.get("optical_candidate", plan["candidate_id"])
            candidates.append(
                {
                    "plan_id": plan_id,
                    "candidate_id": plan["candidate_id"],
                    "arm": plan["arm"],
                    "optical_quality": candidate["metrics"]["strehl"],
                    "approval_id": approval["record_id"],
                }
            )
        if set(c["arm"] for c in candidates) != set(model["arms"].values()):
            raise ResearchError(
                "COMPARATOR_REQUIRED",
                "Both validated arms require feasible approved candidates.",
            )
        if not ood:
            preferred = model["arms"]["intervention" if tau < 0 else "comparator"]
            candidates.sort(
                key=lambda c: (
                    c["arm"] != preferred,
                    -c["optical_quality"],
                    c["candidate_id"],
                )
            )
        else:
            candidates = []
        return svc.save(
            "adaptive_shadow",
            "ASH",
            {
                **inp.model_dump(),
                "model_id": model["record_id"],
                "artifact_hash": model["artifact_hash"],
                "policy_id": model["policy_id"],
                "index_date": index.isoformat(),
                "features": x.tolist(),
                "sex_code": enrollment["sex_code"],
                "baseline_al": enrollment["baseline_al"],
                "status": "abstained" if ood else "shadow_logged",
                "reason": "OUT_OF_DISTRIBUTION" if ood else None,
                "candidates": candidates,
                "research_conditional_arm_difference_mm": tau,
                "individual_effect_interval": None,
                "actual_assignment_changed": False,
                "manufacturing_authorized": False,
                "clinical_use_allowed": False,
                "synthetic": is_synthetic,
                "issued_at": now(),
            },
            actor,
        )


def followup(svc, inp, actor):
    with svc.store.transaction():
        log = svc.get("adaptive_shadow", inp.shadow_id)
        model = svc.get("adaptive_model", log["model_id"])
        if rows(svc, "adaptive_outcome", "shadow_id", inp.shadow_id):
            raise ResearchError(
                "DUPLICATE_OUTCOME",
                "A shadow outcome is immutable; submit a reviewed new version offline.",
                409,
            )
        if (
            log["status"] == "abstained"
            or inp.observed_arm not in model["arms"].values()
        ):
            raise ResearchError(
                "UNSUPPORTED_ARM",
                "Only a supported observed arm for a logged shadow run can be evaluated.",
            )
        if log.get("arm_support") and not log["arm_support"].get(
            inp.observed_arm, {}
        ).get("supported"):
            raise ResearchError(
                "UNSUPPORTED_ARM",
                "This arm had no support in the logged shadow comparison.",
            )
        obs = inp.observation
        elapsed = (obs.visit_at - date.fromisoformat(log["index_date"])).days
        if (
            not 335 <= elapsed <= 395
            or obs.al_status != "measured"
            or obs.quality_flag != "ACCEPTED"
        ):
            raise ResearchError(
                "INVALID_ENDPOINT", "Accepted measured AL at twelve months required."
            )
        if not log["synthetic"] and obs.visit_at > date.today():
            raise ResearchError(
                "FUTURE_OUTCOME", "A measured future outcome cannot be recorded."
            )
        delta = obs.al_mm - log["baseline_al"]
        return svc.save(
            "adaptive_outcome",
            "AOUT",
            {
                **inp.model_dump(mode="json"),
                "patient_id": log["patient_id"],
                "case_id": log["case_id"],
                "eye": log["eye"],
                "model_id": log["model_id"],
                "observed_delta_al_mm": delta,
                "elapsed_days": elapsed,
                "individual_effect_error": None,
                "clinical_use_allowed": False,
                "interpretation": "One observed arm outcome cannot verify an individual treatment effect.",
            },
            actor,
        )


def patient_summary(outcomes):
    patients = {}
    for outcome in outcomes:
        patients.setdefault(outcome["patient_id"], []).append(outcome)
    return {
        "patients": len(patients),
        "observations": len(outcomes),
        "mean_observed_delta_al_mm": float(
            np.mean(
                [
                    np.mean([o["observed_delta_al_mm"] for o in values])
                    for values in patients.values()
                ]
            )
        )
        if patients
        else None,
        "mean_adherence": float(
            np.mean(
                [
                    np.mean([o["adherence"] for o in values])
                    for values in patients.values()
                ]
            )
        )
        if patients
        else None,
        "causal_comparison": False,
    }


def monitor(svc, model_id):
    model = svc.get("adaptive_model", model_id)
    logs = rows(svc, "adaptive_shadow", "model_id", model_id)
    outcomes = rows(svc, "adaptive_outcome", "model_id", model_id)
    arm_summary = {}
    for arm in model["arms"].values():
        selected = [o for o in outcomes if o["observed_arm"] == arm]
        arm_summary[arm] = patient_summary(selected)
    resolved = {r["event_id"] for r in svc.store.list_records("v3_event_resolution")}
    events = [
        e
        for e in svc.store.list_records("v3_study_event")
        if e["patient_id"] in {l["patient_id"] for l in logs}
        and e["record_id"] not in resolved
    ]
    ood = sum(l["status"] == "abstained" for l in logs)
    shifts = (
        np.mean(
            [
                np.abs((np.array(l["features"]) - model["mean"]) / model["scale"])
                for l in logs
            ],
            axis=0,
        ).tolist()
        if logs
        else None
    )
    log_by_id = {l["record_id"]: l for l in logs}
    subgroups = {}
    for name, predicate in {
        "age_under_12": lambda l: l["features"][0] < 12,
        "age_12_plus": lambda l: l["features"][0] >= 12,
        "sex_0": lambda l: l.get("sex_code") == 0,
        "sex_1": lambda l: l.get("sex_code") == 1,
    }.items():
        selected = [o for o in outcomes if predicate(log_by_id[o["shadow_id"]])]
        subgroups[name] = patient_summary(selected)
    patient_ids = {l["patient_id"] for l in logs}
    qc_failures = [
        q
        for q in svc.store.list_records("v3_manufacturing_qc")
        if q["patient_id"] in patient_ids and not q["passed"]
    ]
    from .research import months_after

    overdue = sum(
        not rows(svc, "adaptive_outcome", "shadow_id", l["record_id"])
        and months_after(date.fromisoformat(l["index_date"]), 12).toordinal() + 30
        < date.today().toordinal()
        for l in logs
        if l["status"] != "abstained"
    )
    return {
        "subgroups": subgroups,
        "qc_failed_reports": len(qc_failures),
        "overdue_followup_logs": overdue,
        "model_id": model_id,
        "shadow_logs": len(logs),
        "outcomes": len(outcomes),
        "missing_followup_logs": sum(
            not rows(svc, "adaptive_outcome", "shadow_id", l["record_id"])
            for l in logs
            if l["status"] != "abstained"
        ),
        "ood_fraction": ood / len(logs) if logs else None,
        "mean_absolute_standardized_feature_shift": shifts,
        "observed_arms": arm_summary,
        "unresolved_severe_events": sum(e["severity"] == "severe" for e in events),
        "automatic_promotion": False,
        "individual_causal_validation": False,
        "clinical_use_allowed": False,
        "alerts": (["OOD_RATE"] if logs and ood / len(logs) > 0.1 else [])
        + (["SAFETY_REVIEW"] if any(e["severity"] == "severe" for e in events) else [])
        + (["QC_REVIEW"] if qc_failures else [])
        + (["FEATURE_SHIFT_REVIEW"] if shifts and max(shifts) > 2 else []),
    }
