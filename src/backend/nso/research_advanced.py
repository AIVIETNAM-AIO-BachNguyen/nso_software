"""Integration of data, learning, optics and independent research release services."""

from datetime import date
import hashlib
from pathlib import Path

import numpy as np

from .research import (
    MODELS,
    ResearchError,
    ResearchService,
    digest,
    months_after,
    now,
    transactional,
)
from .research_contracts import Observation


class AdvancedResearchService(ResearchService):
    @transactional
    def queue_training(self, inp, actor):
        from .research_learning import validate_partitions

        validate_partitions(inp.samples, inp.split_strategy)
        for sample in inp.samples:
            self.case(sample)
            if self.treatment_overlap(
                sample,
                min(r.visit_at for r in sample.history),
                sample.observed.visit_at,
            ):
                raise ResearchError(
                    "TREATMENT_HISTORY_UNSUITABLE",
                    "Training endpoints overlap a recorded treatment.",
                )
        if inp.validation_policy_id:
            self.get("release_policy", inp.validation_policy_id)
        return self.save(
            "training_job",
            "TR3",
            {
                "request": inp.model_dump(mode="json"),
                "status": "queued",
                "actor": actor,
            },
            actor,
        )

    def execute_training(self, run_id):
        from .research_jobs import job_lease

        with job_lease(self.store, run_id) as acquired:
            if not acquired:
                return {"run_id": run_id, "status": "running"}
            return self._execute_training(run_id)

    def _execute_training(self, run_id):
        from .research_learning import TrainRequest, fit

        job = self.get("training_job", run_id)
        if self.store.related("v3_training_result", run_id):
            return self.store.related("v3_training_result", run_id)[-1]
        try:
            artifact = fit(TrainRequest(**job["request"]), job["actor"])
            artifact["training_patient_ids"] = sorted(
                {s["patient_id"] for s in job["request"]["samples"]}
            )
            with self.store.transaction():
                stored = self.save("trained_model", "NPM3", artifact, job["actor"])
                from .governance import GovernanceRegistry

                registry = GovernanceRegistry(self.store).register_model(
                    family="research-" + artifact["algorithm"],
                    version=artifact["artifact_hash"][:12],
                    feature_schema_version=stored["schema_version"],
                    training_dataset_version=artifact["dataset_version"],
                    patient_count=len(
                        {s["patient_id"] for s in job["request"]["samples"]}
                    ),
                    algorithm=artifact["algorithm"],
                    target="SE_AL_research_forecast",
                    artifact_hash=artifact["artifact_hash"],
                    artifact_uri="record://" + stored["record_id"],
                    deployment_context="research_only",
                    initial_status="Development",
                    actor=job["actor"],
                )
                result = {
                    "run_id": run_id,
                    "status": "completed",
                    "model_id": stored["record_id"],
                    "model_registry_id": registry["model_id"],
                    "report": artifact["report"],
                    "clinical_use_allowed": False,
                }
                self.store.append_related("v3_training_result", run_id, result)
                return result
        except (ResearchError, ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
            result = {
                "run_id": run_id,
                "status": "failed",
                "code": getattr(exc, "code", "TRAINING_FAILED"),
                "message": str(exc),
                "clinical_use_allowed": False,
            }
            self.store.append_related("v3_training_result", run_id, result)
            return result

    def training_status(self, run_id):
        job = self.get("training_job", run_id)
        results = self.store.related("v3_training_result", run_id)
        return results[-1] if results else {"run_id": run_id, "status": job["status"]}

    def trained_point(self, artifact, history, index, target, age):
        from .research_learning import features, predict_delta
        from . import research_learning

        if (
            artifact.get("implementation_sha256")
            != hashlib.sha256(Path(research_learning.__file__).read_bytes()).hexdigest()
        ):
            raise ResearchError(
                "MODEL_ARTIFACT_CHANGED",
                "The model's serving implementation changed; retrain and independently review a versioned artifact.",
                409,
            )

        empty = {
            "se_d": None,
            "al_mm": None,
            "delta_al_mm": None,
            "delta_se_d": None,
            "se_interval": None,
            "al_interval": None,
            "se_reference_at": index.isoformat(),
            "al_reference_at": index.isoformat(),
        }
        if age is None:
            return {**empty, "applicability_flags": ["INDEX_AGE_REQUIRED"]}
        try:
            x, sequence, baseline = features(history, index, target, age)
        except ResearchError as exc:
            return {**empty, "applicability_flags": [exc.code]}
        minimum, maximum = np.array(artifact["minimum"]), np.array(artifact["maximum"])
        tolerance = np.maximum(
            (maximum - minimum) * 0.1, [0.0, 0.1, 0.1, 0.05, 0.1, 0.01]
        )
        if np.any(np.array(x) < minimum - tolerance) or np.any(
            np.array(x) > maximum + tolerance
        ):
            return {**empty, "applicability_flags": ["OUT_OF_DISTRIBUTION"]}
        delta = predict_delta(artifact, x, sequence)
        values = delta + baseline
        if not (18 <= values[0] <= 35 and -20 <= values[1] <= 15):
            return {**empty, "applicability_flags": ["OUT_OF_DISTRIBUTION"]}
        radius = artifact["interval_radius"]
        return {
            "al_mm": float(values[0]),
            "se_d": float(values[1]),
            "delta_al_mm": float(delta[0]),
            "delta_se_d": float(delta[1]),
            "al_interval": [float(values[0] - radius[0]), float(values[0] + radius[0])]
            if radius
            else None,
            "se_interval": [float(values[1] - radius[1]), float(values[1] + radius[1])]
            if radius
            else None,
            "al_reference_at": index.isoformat(),
            "se_reference_at": index.isoformat(),
            "applicability_flags": [],
        }

    @transactional
    def forecast(self, inp, actor):
        if inp.model_id in MODELS:
            return super().forecast(inp, actor)
        case = self.case(inp)
        history = [
            {k: r[k] for k in Observation.model_fields}
            for r in self.observations(inp)
            if r["visit_at"] <= inp.index_date.isoformat()
        ]
        if not history:
            raise ResearchError("INSUFFICIENT_HISTORY", "No pre-index observations.")
        if not inp.untreated_history_confirmed or self.treatment_overlap(
            inp, date.fromisoformat(history[0]["visit_at"]), inp.index_date
        ):
            raise ResearchError(
                "TREATMENT_HISTORY_UNSUITABLE",
                "Confirm an untreated pre-index history.",
            )
        from .research_release import deployment_history, latest_review

        active = deployment_history(self.store)
        if not active or active[-1]["model_id"] != inp.model_id:
            raise ResearchError(
                "UNVALIDATED_MODEL",
                "This model has not been explicitly approved and deployed for research.",
                409,
            )
        approval = latest_review(self, "model", inp.model_id)
        if not approval or approval["decision"] != "approve":
            raise ResearchError(
                "APPROVAL_WITHDRAWN",
                "This model's research approval has been withdrawn.",
                409,
            )
        artifact = self.get("trained_model", inp.model_id)
        if (
            artifact.get("evidence_kind") == "synthetic_fixture"
            and case.get("indication_code") != "SYNTHETIC"
        ):
            raise ResearchError(
                "SYNTHETIC_MODEL_RESTRICTED",
                "A model trained on invented data can only serve explicitly synthetic cases.",
                409,
            )
        forecasts = [
            {
                "horizon_months": h,
                "target_at": months_after(inp.index_date, h).isoformat(),
                "elapsed_days": (months_after(inp.index_date, h) - inp.index_date).days,
                **self.trained_point(
                    artifact,
                    history,
                    inp.index_date,
                    months_after(inp.index_date, h),
                    inp.index_age,
                ),
            }
            for h in inp.horizons_months
        ]
        registry = next(
            r
            for r in self.store.list_records("model")
            if r.get("artifact_uri") == "record://" + inp.model_id
        )
        record = self.save(
            "prediction",
            "PR3",
            {
                **inp.model_dump(mode="json"),
                "forecasts": forecasts,
                "history_snapshot": history,
                "dataset_hash": digest(history),
                "model_artifact_hash": artifact["artifact_hash"],
                "model_registry_id": registry["model_id"],
                "status": "research_only",
                "clinical_use_allowed": False,
                "interval_status": "patient_split_calibrated"
                if artifact["interval_radius"]
                else "unavailable_pending_held_out_calibration",
            },
            actor,
        )
        return {k: v for k, v in record.items() if k != "history_snapshot"} | {
            "prediction_id": record["record_id"]
        }

    @transactional
    def evaluate(self, inp, actor):
        run = self.get("prediction", inp.prediction_id)
        if run["model_id"] in MODELS:
            return super().evaluate(inp, actor)
        index = date.fromisoformat(run["index_date"])
        if inp.observation.visit_at <= index:
            raise ResearchError(
                "INVALID_FOLLOWUP_DATE", "Follow-up must be after index."
            )
        artifact = self.get("trained_model", run["model_id"])
        predicted = self.trained_point(
            artifact,
            run["history_snapshot"],
            index,
            inp.observation.visit_at,
            run["index_age"],
        )
        metrics = {}
        for name, field in (("al", "al_mm"), ("se", "se_d")):
            rows = [
                r
                for r in run["history_snapshot"]
                if r[name + "_status"] == "measured" and r["quality_flag"] == "ACCEPTED"
            ]
            eligible = (
                getattr(inp.observation, name + "_status") == "measured"
                and inp.observation.quality_flag == "ACCEPTED"
                and bool(rows)
            )
            actual = getattr(inp.observation, field) if eligible else None
            delta = actual - rows[-1][field] if eligible else None
            days = (
                (
                    inp.observation.visit_at - date.fromisoformat(rows[-1]["visit_at"])
                ).days
                if eligible
                else None
            )
            metrics[name] = {
                "observed": actual,
                "observed_change": delta,
                "annualized_change": delta * 365.25 / days if eligible else None,
                "predicted_at_observed_date": predicted[field],
                "residual_observed_minus_predicted": actual - predicted[field]
                if eligible and predicted[field] is not None
                else None,
                "primary_endpoint_eligible": eligible,
                "reference_at": rows[-1]["visit_at"] if rows else None,
                "elapsed_days_from_reference": days,
            }
            interval = predicted[name + "_interval"]
            metrics[name]["prediction_interval_covered"] = (
                bool(interval[0] <= actual <= interval[1])
                if eligible and interval
                else None
            )
        return self.save(
            "outcome",
            "OUT3",
            {
                "prediction_id": inp.prediction_id,
                "patient_id": run["patient_id"],
                "case_id": run["case_id"],
                "eye": run["eye"],
                "observation": inp.observation.model_dump(mode="json"),
                "metrics": metrics,
                "observed_at": inp.observation.visit_at.isoformat(),
                "elapsed_days": (inp.observation.visit_at - index).days,
                "status": "research_only",
                "calibration": None,
            },
            actor,
        )

    @transactional
    def execute_optimizer(self, run_id, actor):
        from .research_optics import optimize, PUBLIC_METRICS, simulator_hash

        job = self.get("optimization", run_id)
        try:
            return self.get("optimization_result", run_id)
        except ResearchError:
            pass
        try:
            envelope = self.get("optical_envelope", job["envelope_id"])
        except ResearchError:
            output = {
                "run_id": run_id,
                "status": "blocked",
                "code": "ENVELOPE_NOT_REGISTERED",
                "message": "Register a protected manufacturing envelope before running the reference optical search.",
                "pareto_candidates": [],
                "optical_metrics": None,
                "clinical_use_allowed": False,
                "completed_at": now(),
            }
            self.store.put_record("v3_optimization_result", run_id, output)
            self.store.append_audit(
                {
                    "action": "V3_OPTIMIZATION_BLOCKED",
                    "object_id": run_id,
                    "actor": actor,
                    "timestamp": now(),
                    "result": "blocked",
                }
            )
            return output
        try:
            result = optimize(envelope, job["seed"], job["candidate_budget"])
            candidates = []
            for p in result["pareto"]:
                candidate = self.save(
                    "optical_candidate",
                    "RES-DES",
                    {
                        **p,
                        "envelope_id": job["envelope_id"],
                        "run_id": run_id,
                        "feasible": True,
                        "simulator_hash": simulator_hash(),
                        "actor": actor,
                    },
                    actor,
                )
                candidates.append(
                    {
                        "design_id": candidate["record_id"],
                        "metrics": {
                            k: v for k, v in p["metrics"].items() if k in PUBLIC_METRICS
                        },
                        "worst_quality": p["worst_quality"],
                    }
                )
            from .research_release import latest_review
            from .research_optics import simulator_hash

            approval = latest_review(self, "envelope", job["envelope_id"])
            calibrated = bool(
                approval
                and approval["decision"] == "approve"
                and self.get("optical_calibration", approval["evidence_id"])[
                    "implementation_sha256"
                ]
                == simulator_hash()
            )
            output = {
                "run_id": run_id,
                "status": "completed",
                "feasibility": True,
                "pareto_candidates": candidates,
                "optical_metrics": {
                    "evaluated": result["evaluated"],
                    "rejected": result["rejected"],
                },
                "calibration_status": "measured_review_passed"
                if calibrated
                else "uncalibrated_reference",
                "simulator_version": result["simulator_version"],
                "configuration_hash": result["configuration_hash"],
                "clinical_use_allowed": False,
                "completed_at": now(),
            }
        except (ResearchError, ValueError) as exc:
            output = {
                "run_id": run_id,
                "status": "failed",
                "code": getattr(exc, "code", "SIMULATION_FAILED"),
                "message": str(exc),
                "pareto_candidates": [],
                "clinical_use_allowed": False,
                "completed_at": now(),
            }
        self.store.put_record("v3_optimization_result", run_id, output)
        self.store.append_audit(
            {
                "action": "V3_OPTIMIZATION_COMPLETED",
                "object_id": run_id,
                "actor": actor,
                "timestamp": now(),
                "result": output["status"],
            }
        )
        return output
