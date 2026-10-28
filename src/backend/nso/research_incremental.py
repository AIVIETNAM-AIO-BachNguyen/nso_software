"""Locked predictive design-value diagnostics; never causal parameter effects."""

import numpy as np
from .research import ResearchError


def _features(parameters, names):
    values = []
    groups = {}
    for name in names:
        start = len(values)
        if name == "fiber_angle_deg":
            # Inactive fibers have no orientation; the feature group is circular.
            angle = np.deg2rad(2 * parameters[name])
            active = float(parameters["fiber_height_um"] > 0)
            values.extend([active * np.sin(angle), active * np.cos(angle)])
        else:
            values.append(parameters[name])
        groups[name] = list(range(start, len(values)))
    return values, groups


def linked_population(pop, cohort, policy):
    grouped = {}
    reasons = {}
    for row in cohort["members"]:
        grouped.setdefault(row["patient_id"], []).append(row)
    keep = []
    parameters = []
    arms = []
    references = []
    groups = None
    from .research_multiarm import ARMS, PARAMETERS

    for i, pid in enumerate(pop["ids"]):
        members = grouped[pid]
        evidence = [m.get("design_evidence", {}) for m in members]
        if any(not e.get("eligible") or not e.get("pre_index") for e in evidence):
            reason = next(
                (
                    e.get("reason", "MISSING_FROZEN_DESIGN_EVIDENCE")
                    for e in evidence
                    if not e.get("eligible") or not e.get("pre_index")
                ),
                "MISSING_FROZEN_DESIGN_EVIDENCE",
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        actual = {e["dispensed_arm"] for e in evidence}
        if len(actual) != 1 or next(iter(actual)) not in ARMS:
            reasons["SPLIT_EYE_DESIGN_ASSIGNMENT"] = (
                reasons.get("SPLIT_EYE_DESIGN_ASSIGNMENT", 0) + 1
            )
            continue
        vectors = []
        for e in evidence:
            if (
                set(e["parameters"]) != set(PARAMETERS)
                or not np.isfinite(list(e["parameters"].values())).all()
            ):
                raise ResearchError(
                    "INVALID_DESIGN_FEATURES",
                    "Frozen parameter features are incomplete or non-finite.",
                )
            values, groups = _features(e["parameters"], policy["design_features"])
            vectors.append(values)
        keep.append(i)
        parameters.append(np.mean(vectors, axis=0))
        arms.append(ARMS.index(next(iter(actual))))
        references.append([e["source_ids"] for e in evidence])
    fraction = 1 - len(keep) / max(len(pop["ids"]), 1)
    if fraction > policy["max_missing_design_fraction"]:
        return None, {
            "reason": "MISSING_OR_POST_INDEX_DESIGN_LINKS",
            "excluded_fraction": fraction,
            "exclusions": reasons,
        }
    arms = np.array(arms, dtype=int)
    if min(np.sum(arms == k) for k in range(3)) < policy["minimum_patients_per_arm"]:
        return None, {
            "reason": "INSUFFICIENT_LINKED_PATIENTS_PER_ARM",
            "excluded_fraction": fraction,
            "exclusions": reasons,
        }
    keep = np.array(keep, dtype=int)
    return {
        "ids": [pop["ids"][i] for i in keep],
        "x": pop["x"][keep],
        "y": pop["y"][keep],
        "a": arms,
        "d": np.array(parameters),
        "groups": groups,
        "references": references,
        "excluded_fraction": fraction,
        "exclusions": reasons,
    }, None


def metric(y, prediction):
    error = prediction - y
    return {
        "patients": len(y),
        "mae_mm": float(np.mean(abs(error))),
        "rmse_mm": float(np.sqrt(np.mean(error**2))),
        "bias_mm": float(np.mean(error)),
        "mse_mm2": float(np.mean(error**2)),
    }


def paired_delta(y, base, full, policy, seed, alpha=0.05):
    # All eyes have already been collapsed inside each independent patient.
    differences = (base - y) ** 2 - (full - y) ** 2
    rng = np.random.default_rng(seed)
    bootstrap = np.mean(
        differences[rng.integers(0, len(y), size=(policy["bootstrap_reps"], len(y)))],
        axis=1,
    )
    return {
        "mse_reduction_mm2": float(differences.mean()),
        "paired_patient_interval": [
            float(np.quantile(bootstrap, alpha / 2)),
            float(np.quantile(bootstrap, 1 - alpha / 2)),
        ],
        "interval_level": 1 - alpha,
        "uncertainty": "Paired held-out-patient percentile bootstrap, fixed fitted models; no causal interpretation.",
    }


def evaluate_design_increment(pops, cohorts, policy):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge

    linked = []
    for split, pop, cohort in zip(("train", "test", "external"), pops, cohorts):
        selected, error = linked_population(pop, cohort, policy)
        if error:
            return {
                "status": "unavailable",
                "reason": error["reason"],
                "partition": split,
                "details": error,
                "causal_design_effects_identified": False,
            }
        linked.append(selected)
    train = linked[0]
    groups = train["groups"]
    d = train["d"]
    # A design column constant within every arm only re-encodes arm labels.
    varying = {
        name: any(
            float(np.max(np.std(d[train["a"] == k][:, cols], axis=0))) > 1e-8
            for k in range(3)
        )
        for name, cols in groups.items()
    }
    if not any(varying.values()):
        return {
            "status": "unavailable",
            "reason": "NO_WITHIN_ARM_PARAMETER_VARIATION",
            "within_arm_variation": varying,
            "causal_design_effects_identified": False,
        }
    # Prevent a physical lot/QC record being reused as independent patient evidence.
    owners = {}
    for split, pop in zip(("train", "test", "external"), linked):
        for pid, refs in zip(pop["ids"], pop["references"]):
            for ref in refs:
                for identity in [ref["lot"], *ref["qc"]]:
                    previous = owners.setdefault(identity, (split, pid))
                    if previous != (split, pid):
                        raise ResearchError(
                            "DESIGN_ENTITY_LEAKAGE",
                            "Physical lot/QC evidence cannot cross independent patients or partitions.",
                        )

    def matrix(pop, stage, columns=None):
        blocks = [pop["x"]]
        if stage != "history":
            encoded = np.eye(3)[pop["a"]][:, 1:]
            blocks.append(encoded)
            # Let arm effects vary with patient history in both nested models.
            blocks.extend([encoded[:, [k]] * pop["x"] for k in range(2)])
        if stage == "design":
            blocks.append(pop["d"] if columns is None else pop["d"][:, columns])
        return np.column_stack(blocks)

    def fit_predict(stage, columns=None, train_override=None):
        source = train if train_override is None else train_override
        model = make_pipeline(
            StandardScaler(), Ridge(alpha=policy["diagnostic_ridge_alpha"])
        )
        model.fit(matrix(source, stage, columns), source["y"])
        return [model.predict(matrix(pop, stage, columns)) for pop in linked[1:]]

    predictions = {stage: fit_predict(stage) for stage in ("history", "arm", "design")}
    reports = {}
    for j, (split, pop) in enumerate(zip(("test", "external"), linked[1:])):
        reports[split] = {
            "patients": len(pop["ids"]),
            "excluded_fraction": pop["excluded_fraction"],
            "stages": {
                stage: metric(pop["y"], pred[j]) for stage, pred in predictions.items()
            },
            "arm_increment": paired_delta(
                pop["y"],
                predictions["history"][j],
                predictions["arm"][j],
                policy,
                policy["seed"] + j,
            ),
            "design_increment": paired_delta(
                pop["y"],
                predictions["arm"][j],
                predictions["design"][j],
                policy,
                policy["seed"] + 10 + j,
            ),
            "ablation": {},
            "within_arm_permutation": {},
        }
    alpha = 0.05 / max(len(groups), 1)
    for name, removed in groups.items():
        remaining = [i for i in range(d.shape[1]) if i not in removed]
        ablated = fit_predict("design", remaining) if remaining else predictions["arm"]
        for j, (split, pop) in enumerate(zip(("test", "external"), linked[1:])):
            reports[split]["ablation"][name] = {
                "within_arm_variation": varying[name],
                **paired_delta(
                    pop["y"],
                    ablated[j],
                    predictions["design"][j],
                    policy,
                    policy["seed"] + 100 + j,
                    alpha=alpha,
                ),
            }
        # Permute only within the observed arm, preserving treatment structure.
        deltas = {split: [] for split in reports}
        rng = np.random.default_rng(policy["seed"] + sum(map(ord, name)))
        for _ in range(policy["permutation_reps"]):
            permuted = {**train, "d": train["d"].copy()}
            for arm in range(3):
                selected = np.flatnonzero(train["a"] == arm)
                order = rng.permutation(selected)
                permuted["d"][np.ix_(selected, removed)] = train["d"][
                    np.ix_(order, removed)
                ]
            pred = fit_predict("design", train_override=permuted)
            for j, (split, pop) in enumerate(zip(("test", "external"), linked[1:])):
                deltas[split].append(
                    float(
                        np.mean((pred[j] - pop["y"]) ** 2)
                        - np.mean((predictions["design"][j] - pop["y"]) ** 2)
                    )
                )
        for split in reports:
            reports[split]["within_arm_permutation"][name] = {
                "mean_mse_increase_mm2": float(np.mean(deltas[split])),
                "repetitions": policy["permutation_reps"],
                "fit_on": "train only; held-out outcomes never used to refit/tune",
            }
    return {
        "status": "completed",
        "kind": "predictive_association_only",
        "causal_design_effects_identified": False,
        "parameter_effects_used_for_shadow_ranking": False,
        "feature_groups": list(groups),
        "within_arm_variation": varying,
        "train_patients": len(train["ids"]),
        "preprocessing_fit_partition": "train",
        "same_patients_across_stages": True,
        "held_out_predictive_increment_supported": all(
            r["design_increment"]["paired_patient_interval"][0] > 0
            for r in reports.values()
        ),
        "feature_increment_supported_on_both_holdouts": {
            name: bool(
                varying[name]
                and all(
                    r["ablation"][name]["paired_patient_interval"][0] > 0
                    for r in reports.values()
                )
            )
            for name in groups
        },
        "outcome": "observed twelve-month AL change in mm",
        "arm_encoding": "actual dispensed arm at index; not an individual causal effect",
        "report": reports,
        "limitations": [
            "Correlated parameters can share predictive information; ablation/permutation are not causal attribution.",
            "QC/outcome/adherence are excluded from predictive features; QC is an eligibility gate only.",
            "Hold-out reuse for tuning requires a new prespecified validation study.",
        ],
    }
