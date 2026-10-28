"""Executable population-model research pipeline. Artifacts are JSON, never pickle.

Calibration uses patient-disjoint validation residual maxima (across eyes and
horizons); test/external patients are never fitted or used to choose intervals.
All model outputs remain research-only, including synthetic demonstrations.
"""

from datetime import date
import math
import warnings
import threading
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Literal
import hashlib

import numpy as np
from pydantic import Field

from .research import ResearchError, baseline_forecast, checked_history, digest, now
from .research_contracts import BenchmarkSample, Contract

_TORCH_LOCK = threading.RLock()

FEATURES = ["age", "al", "se", "al_slope", "se_slope", "horizon_years"]


class LearningSample(BenchmarkSample):
    index_age: float = Field(ge=3, le=100)
    sex_code: int = Field(default=0, ge=0, le=1)


class TrainRequest(Contract):
    dataset_version: str = Field(min_length=1, max_length=120)
    validation_policy_id: str | None = None
    split_strategy: Literal["patient", "temporal"] = "patient"
    evidence_kind: str = Field(
        default="clinical_dataset", pattern="^(clinical_dataset|synthetic_fixture)$"
    )
    algorithm: str = Field(
        pattern="^(mixed_effects|gradient_boosting|temporal_transformer)$"
    )
    samples: list[LearningSample] = Field(min_length=30, max_length=4000)
    seed: int = Field(default=17, ge=0, le=2**31 - 1)
    alpha: float = Field(default=0.1, ge=0.05, le=0.3)
    epochs: int = Field(default=8, ge=1, le=50)


def features(history, index, target, age):
    rows = checked_history(history, index)
    values, slopes, sequences = {}, {}, []
    for name, field in (("al", "al_mm"), ("se", "se_d")):
        measured = [
            r
            for r in rows
            if r[name + "_status"] == "measured" and r["quality_flag"] == "ACCEPTED"
        ]
        if len(measured) < 2 or measured[-1]["visit_at"] != index.isoformat():
            raise ResearchError(
                "INSUFFICIENT_HISTORY",
                "Population models require two measured visits and measured AL/SE at index.",
            )
        days = (
            date.fromisoformat(measured[-1]["visit_at"])
            - date.fromisoformat(measured[0]["visit_at"])
        ).days
        values[name] = measured[-1][field]
        slopes[name] = (measured[-1][field] - measured[0][field]) * 365.25 / days
    for r in rows[-64:]:
        al_ok = r["al_status"] == "measured" and r["quality_flag"] == "ACCEPTED"
        se_ok = r["se_status"] == "measured" and r["quality_flag"] == "ACCEPTED"
        sequences.append(
            [
                (date.fromisoformat(r["visit_at"]) - index).days / 365.25,
                (r["al_mm"] - 24) if al_ok else 0.0,
                r["se_d"] if se_ok else 0.0,
                float(al_ok),
                float(se_ok),
            ]
        )
    x = [
        age,
        values["al"],
        values["se"],
        slopes["al"],
        slopes["se"],
        (target - index).days / 365.25,
    ]
    return x, sequences, [values["al"], values["se"]]


def validate_partitions(samples, strategy="patient"):
    groups, sites = {}, {}
    seen = set()
    visits = {}
    for s in samples:
        groups.setdefault(s.patient_id, set()).add(s.split)
        if len(groups[s.patient_id]) > 1:
            raise ResearchError(
                "PATIENT_LEAKAGE",
                "Both eyes and every visit of a patient must remain in one split.",
            )
        if not s.untreated_history_confirmed or s.observed.visit_at <= s.index_date:
            raise ResearchError(
                "INVALID_TRAINING_SAMPLE",
                "Training requires untreated history and post-index measured endpoints.",
            )
        checked_history(s.history, s.index_date)
        for observation in [*s.history, s.observed]:
            key = (s.patient_id, s.eye, observation.visit_at)
            values = {
                k: getattr(observation, k)
                for k in ("al_mm", "se_d", "al_status", "se_status", "quality_flag")
            }
            if key in visits and visits[key] != values:
                raise ResearchError(
                    "INCONSISTENT_VISIT",
                    "The same patient/eye/date has conflicting training measurements.",
                )
            visits[key] = values
        if (
            any(getattr(s.observed, n + "_status") != "measured" for n in ("al", "se"))
            or s.observed.quality_flag != "ACCEPTED"
        ):
            raise ResearchError(
                "IMPUTED_ENDPOINT",
                "Training endpoints must be accepted measured AL and SE.",
            )
        key = (s.patient_id, s.eye, s.index_date, s.observed.visit_at)
        if key in seen:
            raise ResearchError("DUPLICATE_SAMPLE", "Duplicate endpoint.")
        seen.add(key)
        sites.setdefault(s.split, set()).add(s.site_id)
    if any(len(v) > 1 for v in groups.values()):
        raise ResearchError(
            "PATIENT_LEAKAGE",
            "Both eyes and every visit of a patient must remain in one split.",
        )
    for split, minimum in (("train", 12), ("validation", 10), ("test", 4)):
        if sum(v == {split} for v in groups.values()) < minimum:
            raise ResearchError(
                "INSUFFICIENT_PATIENTS",
                f"{split} requires at least {minimum} distinct patients for this research pipeline.",
            )
    if "external" in sites and sites["external"] & (
        sites.get("train", set()) | sites.get("validation", set())
    ):
        raise ResearchError(
            "SITE_LEAKAGE", "External sites overlap model development sites."
        )
    if strategy == "temporal":
        for early, late in (("train", "validation"), ("validation", "test")):
            if max(s.observed.visit_at for s in samples if s.split == early) >= min(
                s.index_date for s in samples if s.split == late
            ):
                raise ResearchError(
                    "TEMPORAL_LEAKAGE", "Earlier endpoints overlap later index dates."
                )


def tree_predict(tree, x):
    node = 0
    while tree["left"][node] != -1:
        node = (
            tree["left"][node]
            if x[tree["feature"][node]] <= tree["threshold"][node]
            else tree["right"][node]
        )
    return tree["value"][node]


def transformer():
    import torch
    from torch import nn

    class Temporal(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Linear(5, 16)
            layer = nn.TransformerEncoderLayer(
                16, 2, dim_feedforward=32, dropout=0.0, batch_first=True
            )
            self.encoder = nn.TransformerEncoder(layer, 1, enable_nested_tensor=False)
            self.head = nn.Sequential(nn.Linear(22, 16), nn.GELU(), nn.Linear(16, 2))

        def forward(self, sequence, mask, x):
            encoded = self.encoder(self.embedding(sequence), src_key_padding_mask=mask)
            last = (~mask).sum(1) - 1
            return self.head(torch.cat([encoded[torch.arange(len(x)), last], x], 1))

    return Temporal()


def tensors(sequences):
    import torch

    length = max(map(len, sequences))
    data = torch.zeros(len(sequences), length, 5)
    mask = torch.ones(len(sequences), length, dtype=torch.bool)
    for i, seq in enumerate(sequences):
        data[i, : len(seq)] = torch.tensor(seq)
        mask[i, : len(seq)] = False
    return data, mask


def predict_delta(artifact, x, sequence):
    z = (np.asarray(x) - artifact["mean"]) / np.asarray(artifact["scale"])
    if artifact["algorithm"] == "gradient_boosting":
        return np.array(
            [
                m["initial"]
                + m["learning_rate"] * sum(tree_predict(t, z) for t in m["trees"])
                for m in artifact["models"]
            ]
        )
    if artifact["algorithm"] == "mixed_effects":
        design = np.r_[1.0, z, z[0] * z[5], z[3] * z[5], z[4] * z[5]]
        return np.array(
            [
                np.dot(design[m["columns"]], m["fixed_effects"])
                for m in artifact["models"]
            ]
        )
    import torch

    with _TORCH_LOCK, torch.random.fork_rng(), torch.no_grad():
        model = transformer()
        model.load_state_dict(
            {k: torch.tensor(v) for k, v in artifact["weights"].items()}
        )
        model.eval()
        data, mask = tensors([sequence])
        return (
            model(
                data, mask, torch.tensor(z, dtype=torch.float32).reshape(1, -1)
            ).numpy()[0]
            * artifact["target_scale"]
        )


def fit(request, actor):
    validate_partitions(request.samples, request.split_strategy)
    train = [s for s in request.samples if s.split == "train"]
    prepared = {
        id(s): features(s.history, s.index_date, s.observed.visit_at, s.index_age)
        for s in request.samples
    }
    x = np.asarray([prepared[id(s)][0] for s in train])
    y = np.asarray([[s.observed.al_mm, s.observed.se_d] for s in train]) - np.asarray(
        [prepared[id(s)][2] for s in train]
    )
    mean, scale = x.mean(0), x.std(0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    artifact = {
        "algorithm": request.algorithm,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "features": FEATURES,
        "minimum": x.min(0).tolist(),
        "maximum": x.max(0).tolist(),
        "models": [],
        "seed": request.seed,
        "dataset_version": request.dataset_version,
        "split_strategy": request.split_strategy,
        "dataset_hash": digest(
            {
                "dataset_version": request.dataset_version,
                "samples": [s.model_dump(mode="json") for s in request.samples],
            }
        ),
        "validation_policy_id": request.validation_policy_id,
        "evidence_kind": request.evidence_kind,
        "created_at": now(),
        "actor": actor,
        "architecture_version": "npm-population-1",
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "environment": {
            "python": sys.version.split()[0],
            **{
                name: version(name)
                for name in ("numpy", "scipy", "scikit-learn", "statsmodels", "torch")
            },
        },
        "clinical_use_allowed": False,
        "status": "research_only",
    }
    if request.algorithm == "gradient_boosting":
        from sklearn.ensemble import GradientBoostingRegressor

        weights = np.array(
            [1 / sum(t.patient_id == s.patient_id for t in train) for s in train]
        )
        for endpoint in range(2):
            model = GradientBoostingRegressor(
                n_estimators=60,
                max_depth=2,
                random_state=request.seed,
                learning_rate=0.06,
            )
            model.fit(z, y[:, endpoint], sample_weight=weights)
            trees = []
            for estimator in model.estimators_[:, 0]:
                t = estimator.tree_
                trees.append(
                    {
                        "left": t.children_left.tolist(),
                        "right": t.children_right.tolist(),
                        "feature": t.feature.tolist(),
                        "threshold": t.threshold.tolist(),
                        "value": t.value[:, 0, 0].tolist(),
                    }
                )
            artifact["models"].append(
                {
                    "initial": float(model.init_.constant_[0, 0]),
                    "learning_rate": 0.06,
                    "trees": trees,
                }
            )
    elif request.algorithm == "mixed_effects":
        from statsmodels.regression.mixed_linear_model import MixedLM

        design = np.column_stack(
            [
                np.ones(len(z)),
                z,
                z[:, 0] * z[:, 5],
                z[:, 3] * z[:, 5],
                z[:, 4] * z[:, 5],
            ]
        )
        columns = [0]
        for col in range(1, design.shape[1]):
            if np.linalg.matrix_rank(design[:, columns + [col]]) > len(columns):
                columns.append(col)
        for endpoint in range(2):
            with warnings.catch_warnings(record=True) as notices:
                result = MixedLM(
                    y[:, endpoint],
                    design[:, columns],
                    groups=[s.patient_id for s in train],
                ).fit(method="powell", maxiter=200, disp=False)
            if not result.converged or not np.isfinite(result.fe_params).all():
                raise ResearchError(
                    "MODEL_NOT_CONVERGED",
                    "Mixed-effects estimation failed to converge.",
                )
            artifact["models"].append(
                {
                    "columns": columns,
                    "fixed_effects": result.fe_params.tolist(),
                    "random_intercept_variance": float(result.cov_re[0, 0]),
                    "fit_warnings": sorted({str(w.message) for w in notices}),
                }
            )
    else:
        import torch

        # fork_rng restores caller RNG state; inference uses no stochastic dropout.
        with _TORCH_LOCK, torch.random.fork_rng():
            torch.manual_seed(request.seed)
            model = transformer()
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.005)
            data, mask = tensors([prepared[id(s)][1] for s in train])
            target_scale = np.maximum(y.std(0), [0.05, 0.1])
            target = torch.tensor(y / target_scale, dtype=torch.float32)
            input_x = torch.tensor(z, dtype=torch.float32)
            counts = {
                s.patient_id: sum(t.patient_id == s.patient_id for t in train)
                for s in train
            }
            weights = torch.tensor([1 / counts[s.patient_id] for s in train])
            for _ in range(request.epochs):
                optimizer.zero_grad()
                loss = (
                    ((model(data, mask, input_x) - target) ** 2).mean(1) * weights
                ).sum() / weights.sum()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            artifact["weights"] = {
                k: v.detach().tolist() for k, v in model.state_dict().items()
            }
            artifact["target_scale"] = target_scale.tolist()
            artifact["epochs"] = request.epochs
    calibration = {}
    for s in request.samples:
        if s.split != "validation":
            continue
        fx, seq, baseline = prepared[id(s)]
        error = np.abs(
            predict_delta(artifact, fx, seq)
            + baseline
            - [s.observed.al_mm, s.observed.se_d]
        )
        calibration[s.patient_id] = np.maximum(
            calibration.get(s.patient_id, [0.0, 0.0]), error
        )
    scores = np.array(list(calibration.values()))
    rank = math.ceil((len(scores) + 1) * (1 - request.alpha))
    artifact["interval_radius"] = (
        np.sort(scores, axis=0)[rank - 1].tolist() if rank <= len(scores) else None
    )
    artifact["calibration_patients"] = len(scores)
    artifact["alpha"] = request.alpha
    predictions = []
    for s in request.samples:
        fx, seq, baseline = prepared[id(s)]
        predicted = (predict_delta(artifact, fx, seq) + baseline).tolist()
        predictions.append(
            {
                "patient_id": s.patient_id,
                "split": s.split,
                "age_group": "3-10" if s.index_age <= 10 else "11+",
                "sex_code": str(s.sex_code),
                "site_id": s.site_id,
                "observed": [s.observed.al_mm, s.observed.se_d],
                "predicted": predicted,
                "horizon_days": (s.observed.visit_at - s.index_date).days,
            }
        )
    artifact["report"] = metrics(predictions, artifact["interval_radius"])
    artifact["baseline_reports"] = {}
    for name in ("npm-carry-forward-v1", "npm-history-linear-v1"):
        comparator = []
        for s, row in zip(request.samples, predictions):
            p = baseline_forecast(s.history, s.index_date, s.observed.visit_at, name)
            comparator.append({**row, "predicted": [p["al_mm"], p["se_d"]]})
        artifact["baseline_reports"][name] = metrics(comparator, None)
    artifact["artifact_hash"] = digest(
        {k: v for k, v in artifact.items() if k not in {"created_at", "actor"}}
    )
    return artifact


def metrics(rows, radius):
    result = {}
    group_keys = [("split", k) for k in sorted({r["split"] for r in rows})]
    group_keys += [("age_group", k) for k in sorted({r["age_group"] for r in rows})]
    group_keys += [("site_id", k) for k in sorted({r["site_id"] for r in rows})]
    group_keys += [("sex_code", k) for k in sorted({r["sex_code"] for r in rows})]
    for field, key in group_keys:
        group = [
            r
            for r in rows
            if r[field] == key
            and (field == "split" or r["split"] in {"test", "external"})
        ]
        if not group:
            continue
        patients = {}
        for r in group:
            error = np.array(r["predicted"]) - r["observed"]
            patients.setdefault(r["patient_id"], []).append(error)
        sets = [np.array(v) for v in patients.values()]
        result[f"{field}:{key}"] = {
            "patients": len(patients),
            "endpoints": len(group),
            "mae_al_se": np.mean([np.abs(v).mean(0) for v in sets], axis=0).tolist(),
            "rmse_al_se": np.sqrt(
                np.mean([(v * v).mean(0) for v in sets], axis=0)
            ).tolist(),
            "bias_al_se": np.mean([v.mean(0) for v in sets], axis=0).tolist(),
            "interval_coverage_al_se": np.mean(
                [(np.abs(v) <= radius).mean(0) for v in sets], axis=0
            ).tolist()
            if radius
            else None,
        }
    return result
