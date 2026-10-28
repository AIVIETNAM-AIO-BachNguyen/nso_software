"""V3 research services over the existing immutable V2 store.

No trained model, causal individual effect, clinical approval or calibrated
optical simulator is implied by these independently testable services.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import statistics
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from functools import wraps

from .research_contracts import Observation

SCHEMA_VERSION = "3.0.0-research.1"
MODELS = {
    "npm-carry-forward-v1": {
        "minimum_points": 1,
        "algorithm": "last measured observation",
    },
    "npm-history-linear-v1": {
        "minimum_points": 2,
        "algorithm": "within-eye ordinary least squares over real days",
    },
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()
    ).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def artifact_hash(model_id):
    return digest(
        {
            "model": MODELS[model_id],
            "schema": SCHEMA_VERSION,
            "implementation": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "contracts": hashlib.sha256(
                Path(__file__).with_name("research_contracts.py").read_bytes()
            ).hexdigest(),
        }
    )


def months_after(day, months):
    ordinal = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(ordinal, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class ResearchError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def checked_history(observations, index):
    rows = [
        r.model_dump(mode="json") if isinstance(r, Observation) else r
        for r in observations
    ]
    days = [date.fromisoformat(r["visit_at"]) for r in rows]
    if len(set(days)) != len(days):
        raise ResearchError(
            "DUPLICATE_VISIT", "Resolve duplicate per-eye dates before forecasting."
        )
    if any(d > index for d in days):
        raise ResearchError(
            "POST_INDEX_INFORMATION",
            "Forecast history contains post-index observations.",
        )
    return sorted(rows, key=lambda r: r["visit_at"])


def baseline_forecast(history, index, target, model_id):
    """Measured, accepted observations only. Null means abstention, never imputation."""
    if model_id not in MODELS:
        raise ResearchError(
            "UNVALIDATED_MODEL", "No executable research baseline with this ID."
        )
    rows = checked_history(history, index)
    output, flags = {}, []
    for name, field in (("se", "se_d"), ("al", "al_mm")):
        points = [
            (date.fromisoformat(r["visit_at"]), r[field])
            for r in rows
            if r.get(name + "_status") == "measured"
            and r.get(field) is not None
            and r["quality_flag"] == "ACCEPTED"
        ]
        estimate = delta = None
        if len(points) < MODELS[model_id]["minimum_points"]:
            flags.append(f"INSUFFICIENT_HISTORY_{name.upper()}")
        else:
            first_day, _ = points[0]
            x = [(d - first_day).days for d, _ in points]
            y = [v for _, v in points]
            slope = 0.0
            if model_id == "npm-history-linear-v1":
                mean_x, mean_y = statistics.mean(x), statistics.mean(y)
                slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / sum(
                    (a - mean_x) ** 2 for a in x
                )
                intercept = mean_y - slope * mean_x
            else:
                intercept = y[-1]
            predicted = intercept + slope * (target - first_day).days
            lower, upper = (-20, 15) if name == "se" else (18, 35)
            if not math.isfinite(predicted) or not lower <= predicted <= upper:
                flags.append(f"OUT_OF_DISTRIBUTION_{name.upper()}")
            else:
                estimate = round(predicted, 6)
                delta = round(predicted - y[-1], 6)
                if points[-1][0] != index:
                    flags.append(f"NO_INDEX_DATE_MEASUREMENT_{name.upper()}")
        output[field] = estimate
        output["delta_" + field] = delta
        output[name + "_interval"] = None
        output[name + "_reference_at"] = points[-1][0].isoformat() if points else None
    output["applicability_flags"] = flags
    return output


def transactional(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.store.transaction():
            return method(self, *args, **kwargs)

    return call


class ResearchService:
    def __init__(self, store):
        self.store = store

    @transactional
    def save(self, domain, prefix, data, actor):
        key = f"{prefix}-{uuid.uuid4().hex[:24].upper()}"
        record = {
            **data,
            "record_id": key,
            "schema_version": SCHEMA_VERSION,
            "created_at": now(),
            "created_by": actor,
        }
        self.store.put_record("v3_" + domain, key, record)
        self.store.append_audit(
            {
                "object_id": key,
                "object_type": "v3_" + domain,
                "action": "V3_" + domain.upper() + "_CREATED",
                "actor": actor,
                "timestamp": now(),
                "result": "success",
                "content_hash": digest(data),
            }
        )
        return record

    def get(self, domain, key):
        try:
            return self.store.get_record("v3_" + domain, key)
        except KeyError:
            raise ResearchError(
                "NOT_FOUND", "Research record unavailable.", 404
            ) from None

    def case(self, scope):
        try:
            case = self.store.get_record("case", scope.case_id)
        except KeyError:
            raise ResearchError("NOT_FOUND", "Case unavailable.", 404) from None
        if case["patient_id"] != scope.patient_id:
            raise ResearchError("FORBIDDEN", "Patient and case do not match.", 403)
        return case

    def records(self, domain, scope):
        return [
            r
            for r in self.store.list_records("v3_" + domain)
            if all(
                r.get(k) == getattr(scope, k) for k in ("patient_id", "case_id", "eye")
            )
        ]

    def treatment_overlap(self, scope, start, end):
        # Treatment follows the patient/eye across cases, including legacy lots.
        rows = [
            r
            for r in self.store.list_records("v3_exposure")
            if r.get("patient_id") == scope.patient_id
            and r.get("eye") == scope.eye
            and r["arm"] != "NONE"
        ]
        eye_ids = {
            r["eye_id"]
            for r in self.store.list_records("eye")
            if r.get("patient_id") == scope.patient_id
            and r.get("laterality") == scope.eye
        }
        rows += [
            {
                "start_at": r["exposure_start"],
                "end_at": r.get("exposure_end"),
                "legacy": True,
            }
            for r in self.store.list_records("product_exposure")
            if r.get("eye_id") in eye_ids
        ]
        return [
            r
            for r in rows
            if r["start_at"] <= end.isoformat()
            and (not r.get("end_at") or r["end_at"] >= start.isoformat())
        ]

    def ensure_baseline(self, model_id, actor):
        from .governance import GovernanceRegistry, model_id_for

        family = "v3-" + (model_id[:-3] if model_id.endswith("-v1") else model_id)
        key = model_id_for(family, "1.0.0")
        expected_hash = artifact_hash(model_id)
        try:
            record = self.store.get_record("model", key)
            if record["artifact_hash"] != expected_hash:
                raise ResearchError(
                    "MODEL_ARTIFACT_CHANGED",
                    "Baseline implementation changed; version and register a new model before use.",
                    409,
                )
            return key
        except KeyError:
            try:
                GovernanceRegistry(self.store).register_model(
                    family=family,
                    version="1.0.0",
                    feature_schema_version=SCHEMA_VERSION,
                    training_dataset_version="none-untrained-baseline",
                    algorithm=MODELS[model_id]["algorithm"],
                    target="research_SE_AL_forecast",
                    artifact_uri="builtin://" + model_id,
                    artifact_hash=expected_hash,
                    deployment_context="research-only",
                    initial_status="Development",
                    actor=actor,
                )
            except ValueError:
                # Another request may have registered the identical artifact first.
                registered = self.store.get_record("model", key)
                if registered["artifact_hash"] != expected_hash:
                    raise ResearchError(
                        "MODEL_ARTIFACT_CHANGED",
                        "Conflicting registered baseline artifact.",
                        409,
                    ) from None
            return key

    def observations(self, scope):
        """Reuse V2 visits without silently treating legacy imputation as measured AL."""
        explicit = self.records("observation", scope)
        revisions = self.store.list_records("v3_observation_correction")
        corrected = []
        for row in explicit:
            versions = [r for r in revisions if r["observation_id"] == row["record_id"]]
            latest = max(versions, key=lambda r: r["revision"]) if versions else None
            corrected.append(
                {
                    **row,
                    **(latest["replacement"] if latest else {}),
                    "revision": latest["revision"] if latest else 0,
                }
            )
        result = {r["visit_at"]: r for r in corrected}
        visits = {
            r["visit_id"]: r
            for r in self.store.list_records("visit")
            if r.get("case_id") == scope.case_id
            and r.get("patient_id") == scope.patient_id
        }
        legacy = {}
        for m in self.store.list_records("clinical_measurement"):
            visit = visits.get(m.get("visit_id"))
            if (
                not visit
                or m.get("laterality") != scope.eye
                or m.get("missing_data_flag")
            ):
                continue
            kind = m.get("measurement_type")
            if kind not in {"axial_length", "spherical_equivalent"}:
                continue
            if m.get("source") != "objective" or m.get("quality_flag") != "ACCEPTED":
                continue
            field, status = (
                ("al_mm", "al_status")
                if kind == "axial_length"
                else ("se_d", "se_status")
            )
            row = legacy.setdefault(
                visit["visit_date"],
                {
                    "visit_at": visit["visit_date"],
                    "se_d": None,
                    "al_mm": None,
                    "se_status": "missing",
                    "al_status": "missing",
                    "quality_flag": "ACCEPTED",
                    "measurement_method": "V2 objective measurement",
                    "source": "V2 clinical digital thread",
                },
            )
            # Ambiguous duplicates are an error, not an arbitrary last-write win.
            if row[field] is not None:
                raise ResearchError(
                    "DUPLICATE_VISIT",
                    "Resolve duplicate V2 measurements for this eye and date.",
                )
            row[field], row[status] = m["value"], "measured"
        for day, row in legacy.items():
            if day not in result:
                result[day] = Observation(**row).model_dump(mode="json")
        return sorted(result.values(), key=lambda r: r["visit_at"])

    @transactional
    def ingest(self, inp, actor):
        self.case(inp)
        rows = checked_history(inp.observations, date.max)
        existing = {r["visit_at"] for r in self.observations(inp)}
        if existing & {r["visit_at"] for r in rows}:
            raise ResearchError(
                "DUPLICATE_VISIT",
                "An observation for this eye and date already exists.",
            )
        base = inp.model_dump(mode="json", exclude={"observations"})
        # Validate the whole batch before writing any member.
        saved = []
        for r in rows:
            key = "OBS-" + digest({**base, "visit_at": r["visit_at"]})[:24].upper()
            saved.append(
                {
                    **base,
                    **r,
                    "record_id": key,
                    "schema_version": SCHEMA_VERSION,
                    "created_at": now(),
                }
            )
        try:
            self.store.put_records_atomic(
                [("v3_observation", r["record_id"], r) for r in saved]
            )
        except ValueError:
            raise ResearchError(
                "DUPLICATE_VISIT",
                "An observation for this eye and date already exists.",
                409,
            ) from None
        for r in saved:
            self.store.append_audit(
                {
                    "object_id": r["record_id"],
                    "action": "V3_OBSERVATION_CREATED",
                    "actor": actor,
                    "timestamp": now(),
                    "content_hash": digest(r),
                    "result": "success",
                }
            )
        return {"observation_ids": [r["record_id"] for r in saved], "count": len(saved)}

    @transactional
    def exposure(self, inp, actor):
        self.case(inp)
        for prior in self.store.list_records("v3_exposure"):
            if prior["patient_id"] != inp.patient_id or prior["eye"] != inp.eye:
                continue
            end = date.fromisoformat(prior["end_at"]) if prior["end_at"] else date.max
            if inp.start_at <= end and date.fromisoformat(prior["start_at"]) <= (
                inp.end_at or date.max
            ):
                raise ResearchError(
                    "OVERLAPPING_EXPOSURE",
                    "Exposure intervals for this eye may not overlap.",
                )
        if inp.design_id:
            if not self.store.has(inp.design_id):
                # V3 research product IDs deliberately stay outside the V2 vendor
                # export registry: reference recipes are not machine toolpaths.
                from .research_manufacturing import lot_ready

                lots = [
                    r
                    for r in self.store.list_records("v3_manufacturing_lot")
                    if r["design_id"] == inp.design_id
                    and all(
                        r[k] == getattr(inp, k)
                        for k in ("patient_id", "case_id", "eye")
                    )
                ]
                if not lots:
                    raise ResearchError("NOT_FOUND", "Design unavailable.", 404)
                ready = False
                for lot in lots:
                    try:
                        lot_ready(self, lot["record_id"])
                        ready = True
                        break
                    except ResearchError:
                        continue
                if not ready:
                    raise ResearchError(
                        "MISSING_OR_FAILED_QC",
                        "No currently approved passing research lot is available.",
                        409,
                    )
            if (
                self.store.has(inp.design_id)
                and self.store.get(inp.design_id).get("patient_id") != inp.patient_id
            ):
                raise ResearchError(
                    "FORBIDDEN", "Design belongs to another patient.", 403
                )
        return self.save("exposure", "EXP", inp.model_dump(mode="json"), actor)

    @transactional
    def forecast(self, inp, actor):
        self.case(inp)
        all_history = self.observations(inp)
        # Persisted future visits are excluded by the index snapshot.
        history = [
            {k: r[k] for k in Observation.model_fields}
            for r in all_history
            if date.fromisoformat(r["visit_at"]) <= inp.index_date
        ]
        if not history:
            raise ResearchError(
                "INSUFFICIENT_HISTORY", "No pre-index observations for this eye."
            )
        active_history = self.treatment_overlap(
            inp, date.fromisoformat(history[0]["visit_at"]), inp.index_date
        )
        if not inp.untreated_history_confirmed or active_history:
            raise ResearchError(
                "TREATMENT_HISTORY_UNSUITABLE",
                "NPM requires confirmed untreated history; treatment-era trends are not natural progression.",
            )
        forecasts = [
            {
                "horizon_months": h,
                "target_at": months_after(inp.index_date, h).isoformat(),
                "elapsed_days": (months_after(inp.index_date, h) - inp.index_date).days,
                **baseline_forecast(
                    history,
                    inp.index_date,
                    months_after(inp.index_date, h),
                    inp.model_id,
                ),
            }
            for h in sorted(inp.horizons_months)
        ]
        registry_id = self.ensure_baseline(inp.model_id, actor)
        data = {
            **inp.model_dump(mode="json"),
            "forecasts": forecasts,
            "history_snapshot": history,
            "dataset_hash": digest(history),
            "model_artifact_hash": artifact_hash(inp.model_id),
            "model_registry_id": registry_id,
            "status": "research_only",
            "interval_status": "unavailable_pending_held_out_calibration",
            "clinical_use_allowed": False,
        }
        stored = self.save("prediction", "PR3", data, actor)
        return {k: v for k, v in stored.items() if k != "history_snapshot"} | {
            "prediction_id": stored["record_id"]
        }

    @transactional
    def evaluate(self, inp, actor):
        run = self.get("prediction", inp.prediction_id)
        obs = inp.observation.model_dump(mode="json")
        index = date.fromisoformat(run["index_date"])
        if inp.observation.visit_at <= index:
            raise ResearchError(
                "INVALID_FOLLOWUP_DATE", "Follow-up must be after the frozen index."
            )
        predicted = baseline_forecast(
            run["history_snapshot"], index, inp.observation.visit_at, run["model_id"]
        )
        values = {}
        for name, field in (("se", "se_d"), ("al", "al_mm")):
            baseline = [
                r
                for r in run["history_snapshot"]
                if r.get(name + "_status") == "measured"
                and r.get(field) is not None
                and r["quality_flag"] == "ACCEPTED"
            ]
            eligible = (
                obs[name + "_status"] == "measured"
                and obs["quality_flag"] == "ACCEPTED"
                and bool(baseline)
            )
            actual = obs[field] if eligible else None
            delta = actual - baseline[-1][field] if eligible else None
            reference_days = (
                (
                    inp.observation.visit_at
                    - date.fromisoformat(baseline[-1]["visit_at"])
                ).days
                if eligible
                else None
            )
            values[name] = {
                "observed": actual,
                "observed_change": delta,
                "reference_at": baseline[-1]["visit_at"] if baseline else None,
                "elapsed_days_from_reference": reference_days,
                "annualized_change": delta * 365.25 / reference_days
                if eligible
                else None,
                "predicted_at_observed_date": predicted[field],
                "residual_observed_minus_predicted": actual - predicted[field]
                if eligible and predicted[field] is not None
                else None,
                "primary_endpoint_eligible": eligible,
            }
        stored = self.save(
            "outcome",
            "OUT3",
            {
                "prediction_id": inp.prediction_id,
                "patient_id": run["patient_id"],
                "case_id": run["case_id"],
                "eye": run["eye"],
                "observed_at": obs["visit_at"],
                "observation": obs,
                "elapsed_days": (inp.observation.visit_at - index).days,
                "metrics": values,
                "calibration": None,
                "status": "research_only",
            },
            actor,
        )
        return stored

    @transactional
    def freeze_cohort(self, inp, actor):
        members = []
        if inp.protocol_id:
            protocol = self.get("protocol", inp.protocol_id)
            if protocol["assignment"] != inp.assignment:
                raise ResearchError(
                    "PROTOCOL_MISMATCH",
                    "Cohort assignment differs from its locked protocol.",
                )
        target = months_after(inp.index_date, inp.horizon_months)
        for member in inp.members:
            self.case(member)
            rows = self.observations(member)
            baseline = [
                r
                for r in rows
                if r["visit_at"] == inp.index_date.isoformat()
                and r["al_status"] == "measured"
                and r["quality_flag"] == "ACCEPTED"
            ]
            followups = [
                r
                for r in rows
                if abs((date.fromisoformat(r["visit_at"]) - target).days)
                <= inp.visit_window_days
                and r["visit_at"] > inp.index_date.isoformat()
                and r["al_status"] == "measured"
                and r["quality_flag"] == "ACCEPTED"
            ]
            exposures = [
                r
                for r in self.store.list_records("v3_exposure")
                if r["patient_id"] == member.patient_id and r["eye"] == member.eye
            ]
            assigned = [
                r
                for r in exposures
                if r["start_at"] <= inp.index_date.isoformat()
                and (not r["end_at"] or r["end_at"] >= inp.index_date.isoformat())
            ]
            arm = assigned[0]["arm"] if len(assigned) == 1 else None
            follow = (
                min(
                    followups,
                    key=lambda r: (
                        abs((date.fromisoformat(r["visit_at"]) - target).days),
                        r["visit_at"],
                    ),
                )
                if followups
                else None
            )
            enrollment = (
                [
                    r
                    for r in self.records("enrollment", member)
                    if r["protocol_id"] == inp.protocol_id
                    and r["index_date"] == inp.index_date.isoformat()
                ]
                if inp.protocol_id
                else []
            )
            events = (
                [
                    r
                    for r in self.records("study_event", member)
                    if r["protocol_id"] == inp.protocol_id
                ]
                if inp.protocol_id
                else []
            )
            reasons = []
            if inp.protocol_id and (
                len(enrollment) != 1 or not enrollment[0]["eligible"]
            ):
                reasons.append("INELIGIBLE_OR_MISSING_ENROLLMENT")
            if not baseline:
                reasons.append("MISSING_MEASURED_BASELINE_AL")
            if not follow:
                reasons.append("MISSING_MEASURED_FOLLOWUP_AL")
            if arm not in getattr(
                inp, "study_arms", (inp.intervention, inp.comparator)
            ):
                reasons.append("MISSING_OR_INELIGIBLE_ARM")
            endpoint = follow["visit_at"] if follow else target.isoformat()
            if any(
                r.get("legacy")
                for r in self.treatment_overlap(
                    member, inp.index_date, date.fromisoformat(endpoint)
                )
            ):
                reasons.append("LEGACY_EXPOSURE_REQUIRES_RECONCILIATION")
            switches = [
                r
                for r in exposures
                if inp.index_date.isoformat() < r["start_at"] <= endpoint
            ]
            if switches:
                reasons.append("TREATMENT_SWITCH_OR_RESTART")
            if assigned and assigned[0]["end_at"] and assigned[0]["end_at"] < endpoint:
                reasons.append("DISCONTINUED_BEFORE_ENDPOINT")
            days = (
                (date.fromisoformat(follow["visit_at"]) - inp.index_date).days
                if follow
                else None
            )
            members.append(
                {
                    **member.model_dump(),
                    "arm": arm,
                    "exclusions": reasons,
                    "adherence": assigned[0]["adherence"] if assigned else None,
                    "baseline": baseline[0] if baseline else None,
                    "followup": follow,
                    "elapsed_days": days,
                    "delta_al_mm": follow["al_mm"] - baseline[0]["al_mm"]
                    if not reasons
                    else None,
                    "enrollment": enrollment[0] if enrollment else None,
                    "study_events": events,
                }
            )
        data = inp.model_dump(mode="json", exclude={"members"}) | {
            "members": members,
            "dataset_hash": digest(members),
            "status": "research_only",
            "causal_effect_identified": False,
            "assignment_status": "user_declared_not_independently_verified",
        }
        if inp.protocol_id:
            data["analysis_plan"] = protocol["analysis_plan"]
            data["protocol_hash"] = digest(protocol)
        saved = self.save("cohort", "COH", data, actor)
        return {
            "cohort_id": saved["record_id"],
            "dataset_hash": saved["dataset_hash"],
            "members": len(members),
            "eligible_eyes": sum(not r["exclusions"] for r in members),
            "status": "research_only",
        }

    @transactional
    def estimate(self, cohort_id, actor):
        cohort = self.get("cohort", cohort_id)
        groups = []
        for arm in (cohort["comparator"], cohort["intervention"]):
            records = [
                r for r in cohort["members"] if r["arm"] == arm and not r["exclusions"]
            ]
            # Average each patient's eyes first; binocular records are not independent patients.
            patients = {}
            for r in records:
                patients.setdefault(r["patient_id"], []).append(r["delta_al_mm"])
            values = [statistics.mean(v) for v in patients.values()]
            groups.append(
                {
                    "arm": arm,
                    "patients": len(values),
                    "eyes": len(records),
                    "mean_observed_delta_al_mm": statistics.mean(values)
                    if values
                    else None,
                    "patient_level_sd_mm": statistics.stdev(values)
                    if len(values) > 1
                    else None,
                    "mean_elapsed_days": statistics.mean(
                        r["elapsed_days"] for r in records
                    )
                    if records
                    else None,
                    "uncertainty_interval": None,
                }
            )
        result = {
            "cohort_id": cohort_id,
            "dataset_hash": cohort["dataset_hash"],
            "groups": groups,
            "excluded_eyes": sum(bool(r["exclusions"]) for r in cohort["members"]),
            "exclusion_reasons": {
                reason: sum(reason in r["exclusions"] for r in cohort["members"])
                for reason in sorted(
                    {x for r in cohort["members"] for x in r["exclusions"]}
                )
            },
            "status": "descriptive_only",
            "ite": None,
            "cate": None,
            "causal_effect": None,
            "readiness": {
                "assignment_verified": False,
                "confounding_assessed": False,
                "overlap_assessed": False,
                "locked_plan_recorded": bool(cohort["analysis_plan"]),
            },
            "limitations": [
                "Observed arm summaries are not causal treatment effects.",
                "Missing endpoints and switching are excluded and require sensitivity analysis.",
                "No individual benefit or uncertainty interval has been validated.",
            ],
        }
        return self.save("arm_report", "ARM", result, actor)

    @transactional
    def submit_optimizer(self, inp, actor):
        self.case(inp)
        return self.save(
            "optimization",
            "OPT",
            {
                **inp.model_dump(mode="json"),
                "status": "queued",
                "clinical_use_allowed": False,
            },
            actor,
        )

    @transactional
    def execute_optimizer(self, run_id, actor):
        """Fail closed until a calibrated, approved simulator/envelope is supplied.

        Intentionally no numerical optical scores from the existing heuristic
        candidate ranking. A separate worker can process immutable job events.
        """
        self.get("optimization", run_id)
        try:
            return self.get("optimization_result", run_id)
        except ResearchError:
            result = {
                "run_id": run_id,
                "status": "blocked",
                "code": "SIMULATOR_NOT_CONFIGURED",
                "message": "A measured-QC-calibrated optical simulator and approved design envelope are required.",
                "feasibility": None,
                "pareto_candidates": [],
                "optical_metrics": None,
                "clinical_use_allowed": False,
                "completed_at": now(),
            }
            try:
                self.store.put_record("v3_optimization_result", run_id, result)
            except ValueError:
                return self.get("optimization_result", run_id)
            self.store.append_audit(
                {
                    "object_id": run_id,
                    "action": "V3_OPTIMIZER_BLOCKED",
                    "actor": actor,
                    "timestamp": now(),
                    "result": "blocked",
                }
            )
            return result

    def optimizer_status(self, run_id):
        job = self.get("optimization", run_id)
        try:
            result = self.get("optimization_result", run_id)
        except ResearchError:
            result = {"status": "queued", "pareto_candidates": []}
        return {**job, **result, "run_id": run_id}

    @transactional
    def validate(self, inp, actor):
        splits, sites, dates, endpoint_dates = {}, {}, {}, {}
        for sample in inp.samples:
            self.case(sample)
            splits.setdefault(sample.patient_id, set()).add(sample.split)
            sites.setdefault(sample.split, set()).add(sample.site_id)
            dates.setdefault(sample.split, []).append(sample.index_date)
            endpoint_dates.setdefault(sample.split, []).append(sample.observed.visit_at)
            checked_history(sample.history, sample.index_date)
            if sample.observed.visit_at <= sample.index_date:
                raise ResearchError(
                    "POST_INDEX_INFORMATION",
                    "Validation endpoint must be after the index.",
                )
            if not sample.untreated_history_confirmed:
                raise ResearchError(
                    "TREATMENT_HISTORY_UNSUITABLE",
                    "Benchmark samples require untreated-history attestation.",
                )
            first_date = min(r.visit_at for r in sample.history)
            if self.treatment_overlap(sample, first_date, sample.observed.visit_at):
                raise ResearchError(
                    "TREATMENT_HISTORY_UNSUITABLE",
                    "Recorded exposure overlaps an untreated benchmark sample.",
                )
        if any(len(s) != 1 for s in splits.values()):
            raise ResearchError(
                "PATIENT_LEAKAGE",
                "A patient appears in multiple splits, including across eyes.",
            )
        if not {"train", "validation", "test"} <= set(dates):
            raise ResearchError(
                "INVALID_SPLITS", "Train, validation and test patients are required."
            )
        identities = [
            (s.patient_id, s.eye, s.index_date, s.observed.visit_at)
            for s in inp.samples
        ]
        if len(set(identities)) != len(identities):
            raise ResearchError(
                "DUPLICATE_SAMPLE", "Duplicate validation endpoints are not allowed."
            )
        if inp.split_strategy == "temporal" and not (
            max(endpoint_dates["train"]) < min(dates["validation"])
            and max(endpoint_dates["validation"]) < min(dates["test"])
        ):
            raise ResearchError(
                "TEMPORAL_LEAKAGE",
                "Temporal splits must separate prior endpoints from later index dates.",
            )
        if inp.split_strategy == "external_site":
            development = sites["train"] | sites["validation"]
            if "external" not in sites or sites["external"] & development:
                raise ResearchError(
                    "SITE_LEAKAGE", "External validation requires held-out sites."
                )
        metrics = {}
        for split in sorted(dates):
            metrics[split] = {}
            samples = [s for s in inp.samples if s.split == split]
            for name, field in (("se", "se_d"), ("al", "al_mm")):
                errors, patient_errors = [], {}
                for s in samples:
                    forecast = baseline_forecast(
                        s.history, s.index_date, s.observed.visit_at, inp.model_id
                    )
                    if (
                        getattr(s.observed, name + "_status") != "measured"
                        or s.observed.quality_flag != "ACCEPTED"
                        or forecast[field] is None
                    ):
                        continue
                    error = forecast[field] - getattr(s.observed, field)
                    errors.append(error)
                    patient_errors.setdefault(s.patient_id, []).append(error)
                # Equal patient weight; eyes and repeated visits are clustered by patient.
                per_patient = list(patient_errors.values())
                metrics[split][name] = {
                    "n_endpoints": len(errors),
                    "n_patients": len(per_patient),
                    "mae": statistics.mean(
                        statistics.mean(abs(e) for e in es) for es in per_patient
                    )
                    if errors
                    else None,
                    "rmse": math.sqrt(
                        statistics.mean(
                            statistics.mean(e * e for e in es) for es in per_patient
                        )
                    )
                    if errors
                    else None,
                    "bias_predicted_minus_observed": statistics.mean(
                        statistics.mean(es) for es in per_patient
                    )
                    if errors
                    else None,
                    "interval_coverage": None,
                    "calibration": None,
                    "abstained_or_ineligible": len(samples) - len(errors),
                }
        snapshot = self.save(
            "benchmark_dataset",
            "DS3",
            {
                "dataset_version": inp.dataset_version,
                "dataset_hash": digest(inp.model_dump(mode="json")),
                "samples": inp.model_dump(mode="json")["samples"],
            },
            actor,
        )
        registry_id = self.ensure_baseline(inp.model_id, actor)
        data = {
            "model_id": inp.model_id,
            "model_registry_id": registry_id,
            "dataset_version": inp.dataset_version,
            "dataset_id": snapshot["record_id"],
            "dataset_hash": snapshot["dataset_hash"],
            "split_strategy": inp.split_strategy,
            "metrics": metrics,
            "status": "benchmark_only",
            "approval": None,
            "validated_for_clinical_use": False,
            "model_artifact_hash": artifact_hash(inp.model_id),
            "limitations": [
                "Baselines only; no trained Transformer, mixed-effects or boosted model.",
                "Prediction intervals, subgroup calibration and prospective validation remain unavailable.",
                "Input provenance and untreated status require independent data review.",
            ],
        }
        return self.save("validation", "VAL3", data, actor)
