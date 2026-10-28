"""Patient-level arm analysis with explicit identification/overlap limitations."""

import numpy as np
from pydantic import Field

from .research import ResearchError, digest
from .research_contracts import Contract


class CausalRequest(Contract):
    cohort_id: str
    method: str = Field(pattern="^(randomized_ancova|observational_aipw)$")
    bootstrap_reps: int = Field(default=200, ge=50, le=1000)
    seed: int = Field(default=17, ge=0, le=2**31 - 1)
    # Prespecified sensitivity bound, not an estimated confounding magnitude.
    unmeasured_bias_bound_mm: float = Field(default=0.1, ge=0, le=1)
    missing_outcome_lower_mm: float = Field(default=-0.2, ge=-2, le=2)
    missing_outcome_upper_mm: float = Field(default=1.5, ge=0, le=3)


def standardized_difference(x, arm, weights):
    result = []
    for col in x.T:
        a, b = col[arm == 1], col[arm == 0]
        denominator = np.sqrt((a.var() + b.var()) / 2)
        difference = np.average(a, weights=weights[arm == 1]) - np.average(
            b, weights=weights[arm == 0]
        )
        result.append(
            float(difference / denominator)
            if denominator > 1e-10
            else (0.0 if abs(difference) < 1e-10 else None)
        )
    return result


def analyze(svc, request, actor):
    cohort = svc.get("cohort", request.cohort_id)
    if not cohort.get("protocol_id"):
        raise ResearchError(
            "PROTOCOL_REQUIRED", "Freeze the cohort against a locked protocol first."
        )
    protocol = svc.get("protocol", cohort["protocol_id"])
    randomized = request.method == "randomized_ancova"
    if randomized != (protocol["assignment"] == "randomized"):
        raise ResearchError(
            "METHOD_PROTOCOL_MISMATCH",
            "The analysis method must match the locked assignment design.",
        )
    covariates = protocol["covariates"]
    if request.missing_outcome_lower_mm >= request.missing_outcome_upper_mm:
        raise ResearchError(
            "INVALID_SENSITIVITY_BOUNDS",
            "Missing-outcome sensitivity bounds must be ordered.",
        )
    patients, excluded, eligible_missing = {}, {}, 0
    missing_by_arm = {0: set(), 1: set()}
    event_counts = {}
    for row in cohort["members"]:
        enrollment = row.get("enrollment")
        if not enrollment or not enrollment["eligible"]:
            excluded["eligibility"] = excluded.get("eligibility", 0) + 1
            continue
        arm_name = enrollment["assigned_arm"] if randomized else row["arm"]
        if arm_name not in {cohort["intervention"], cohort["comparator"]}:
            excluded["arm"] = excluded.get("arm", 0) + 1
            continue
        if randomized and not enrollment.get("allocation_reference"):
            raise ResearchError(
                "ALLOCATION_REFERENCE_REQUIRED",
                "Randomized analysis requires allocation references for every patient.",
            )
        if not row.get("baseline") or not row.get("followup"):
            eligible_missing += 1
            missing_by_arm[int(arm_name == cohort["intervention"])].add(
                row["patient_id"]
            )
            continue
        if protocol["analysis_population"] == "per_protocol" and row["exclusions"]:
            excluded["per_protocol"] = excluded.get("per_protocol", 0) + 1
            continue
        baseline, followup = row["baseline"], row["followup"]
        if baseline["al_status"] != "measured" or followup["al_status"] != "measured":
            eligible_missing += 1
            continue
        if abs(enrollment["baseline_al"] - baseline["al_mm"]) > 0.00001:
            raise ResearchError(
                "BASELINE_COVARIATE_MISMATCH",
                "Enrollment AL differs from its frozen measured baseline.",
            )
        if "baseline_se" in covariates and (
            baseline["se_status"] != "measured"
            or abs(enrollment["baseline_se"] - baseline["se_d"]) > 0.00001
        ):
            raise ResearchError(
                "BASELINE_COVARIATE_MISMATCH",
                "Enrollment SE must match its accepted measured baseline.",
            )
        for event in row.get("study_events", []):
            event_counts.setdefault(event["kind"], set()).add(event["record_id"])
        a = int(arm_name == cohort["intervention"])
        patient = patients.setdefault(row["patient_id"], {"arm": a, "x": [], "y": []})
        if patient["arm"] != a:
            raise ResearchError(
                "SPLIT_EYE_ASSIGNMENT",
                "This patient-level estimator does not support split-eye treatment assignment.",
            )
        patient["x"].append([enrollment[name] for name in covariates])
        patient["y"].append(followup["al_mm"] - baseline["al_mm"])
    data = list(patients.values())
    arm = np.array([p["arm"] for p in data])
    if len(data) < 20 or min(sum(arm == 0), sum(arm == 1)) < 8:
        raise ResearchError(
            "INSUFFICIENT_PATIENTS",
            "This estimator requires at least 20 patients and 8 in each arm.",
        )
    x = np.array([np.mean(p["x"], axis=0) for p in data])
    y = np.array([np.mean(p["y"]) for p in data])
    base = {
        "cohort_id": request.cohort_id,
        "protocol_id": cohort["protocol_id"],
        "dataset_hash": cohort["dataset_hash"],
        "method": request.method,
        "analysis_population": protocol["analysis_population"],
        "patients": len(data),
        "patients_by_arm": {
            "comparator": int(sum(arm == 0)),
            "intervention": int(sum(arm == 1)),
        },
        "missing_endpoint_eyes": eligible_missing,
        "other_exclusions": excluded,
        "covariates": covariates,
        "estimand": "intervention minus comparator in observed 12-month axial elongation (mm)",
        "clinical_use_allowed": False,
        "ite": None,
        "cate": None,
        "assignment_independently_verified": False,
        "study_event_counts": {k: len(v) for k, v in event_counts.items()},
    }
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(x)
    z = scaler.transform(x)
    if randomized:
        import statsmodels.api as sm

        design = np.column_stack([np.ones(len(data)), arm, z])
        if np.linalg.matrix_rank(design) < design.shape[1]:
            raise ResearchError(
                "SINGULAR_COVARIATES",
                "Remove redundant covariates in a new protocol version.",
            )
        fitted = sm.OLS(y, design).fit(cov_type="HC3")
        estimate = float(fitted.params[1])
        interval = fitted.conf_int(alpha=0.05)[1].tolist()
        weights = np.ones(len(data))
        diagnostics = {
            "balance_smd_before": standardized_difference(x, arm, weights),
            "uncertainty_method": "patient-level ANCOVA HC3",
        }
    else:
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.model_selection import StratifiedKFold

        propensity, mu0, mu1 = (
            np.zeros(len(data)),
            np.zeros(len(data)),
            np.zeros(len(data)),
        )
        for train, test in StratifiedKFold(
            3, shuffle=True, random_state=request.seed
        ).split(x, arm):
            fold_scaler = StandardScaler().fit(x[train])
            tx, vx = fold_scaler.transform(x[train]), fold_scaler.transform(x[test])
            propensity[test] = (
                LogisticRegression(C=1.0, max_iter=500, random_state=request.seed)
                .fit(tx, arm[train])
                .predict_proba(vx)[:, 1]
            )
            for a, output in ((0, mu0), (1, mu1)):
                selected = arm[train] == a
                output[test] = (
                    Ridge(alpha=1.0).fit(tx[selected], y[train][selected]).predict(vx)
                )
        bounded = np.clip(propensity, 0.05, 0.95)
        weights = arm / bounded + (1 - arm) / (1 - bounded)
        diagnostics = {
            "propensity_min": float(propensity.min()),
            "propensity_max": float(propensity.max()),
            "extreme_fraction": float(
                np.mean((propensity < 0.05) | (propensity > 0.95))
            ),
            "balance_smd_before": standardized_difference(x, arm, np.ones(len(data))),
            "balance_smd_after": standardized_difference(x, arm, weights),
            "effective_sample_size": {
                str(a): float(
                    weights[arm == a].sum() ** 2 / (weights[arm == a] ** 2).sum()
                )
                for a in (0, 1)
            },
            "uncertainty_method": "patient influence-function bootstrap with cross-fitted nuisance estimates held fixed",
        }
        influence = (
            mu1
            - mu0
            + arm * (y - mu1) / bounded
            - (1 - arm) * (y - mu0) / (1 - bounded)
        )
        estimate = float(influence.mean())
        rng = np.random.default_rng(request.seed)
        boot = [
            np.mean(rng.choice(influence, len(data), replace=True))
            for _ in range(request.bootstrap_reps)
        ]
        interval = np.quantile(boot, [0.025, 0.975]).tolist()
        if (
            diagnostics["extreme_fraction"] > 0.1
            or min(diagnostics["effective_sample_size"].values()) < 8
        ):
            return svc.save(
                "causal_report",
                "CAU",
                {
                    **base,
                    "status": "overlap_failed",
                    "effect_mm": None,
                    "interval_95_mm": None,
                    "diagnostics": diagnostics,
                    "limitations": [
                        "Positivity/support gate failed; no treatment effect is reported."
                    ],
                },
                actor,
            )
    sensitivity = [
        estimate - request.unmeasured_bias_bound_mm,
        estimate + request.unmeasured_bias_bound_mm,
    ]
    outcome_ranges = {}
    for a in (0, 1):
        missing = missing_by_arm[a] - set(patients)
        observed = y[arm == a]
        denominator = len(observed) + len(missing)
        outcome_ranges[a] = [
            (float(observed.sum()) + len(missing) * bound) / denominator
            for bound in (
                request.missing_outcome_lower_mm,
                request.missing_outcome_upper_mm,
            )
        ]
    result = {
        **base,
        "status": "research_estimate",
        "effect_mm": estimate,
        "interval_95_mm": interval,
        "diagnostics": diagnostics,
        "bias_sensitivity_range_mm": sensitivity,
        "missingness_sensitivity_required": bool(eligible_missing),
        "missing_patient_scenario": {
            "fully_missing_patients_by_arm": {
                str(a): len(missing_by_arm[a] - set(patients)) for a in (0, 1)
            },
            "assumed_missing_change_bounds_mm": [
                request.missing_outcome_lower_mm,
                request.missing_outcome_upper_mm,
            ],
            "unadjusted_arm_difference_bounds_mm": [
                outcome_ranges[1][0] - outcome_ranges[0][1],
                outcome_ranges[1][1] - outcome_ranges[0][0],
            ],
            "interpretation": "Worst-case unadjusted bounds for entirely missing patients, not an adjusted confidence interval; partial-eye missingness remains unresolved.",
        },
        "limitations": [
            "Identification depends on protocol, assignment, consistency and measured-confounding assumptions.",
            "Complete endpoint analysis does not identify the effect for patients lost to follow-up.",
            "The sensitivity range is a user-specified bias scenario, not a confidence interval.",
        ],
    }
    result["analysis_hash"] = digest(request.model_dump(mode="json"))
    return svc.save("causal_report", "CAU", result, actor)
