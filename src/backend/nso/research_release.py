"""Independent research review and explicit deployment/rollback; no clinical release."""

from typing import Literal

from pydantic import Field

from .research import ResearchError, digest
from .research_contracts import Contract


class ReleasePolicy(Contract):
    name: str = Field(min_length=3, max_length=120)
    max_al_mae: float = Field(default=0.2, gt=0, le=1)
    max_se_mae: float = Field(default=0.5, gt=0, le=3)
    minimum_coverage: float = Field(default=0.85, ge=0.5, le=1)
    minimum_test_patients: int = Field(default=20, ge=4, le=10000)
    require_external: bool = True
    minimum_relative_improvement: float = Field(default=0.05, ge=0, le=0.5)


class Review(Contract):
    target_kind: Literal["model", "envelope", "design"]
    target_id: str
    evidence_id: str | None = None
    policy_id: str | None = None
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=20, max_length=2000)


class Deployment(Contract):
    model_id: str
    review_id: str
    reason: str = Field(min_length=20, max_length=2000)


class Rollback(Contract):
    target_deployment_id: str
    reason: str = Field(min_length=20, max_length=2000)


def deployment_history(store):
    return sorted(
        store.related("v3_npm_deployment", "npm-research"),
        key=lambda r: r.get("sequence", 0),
    )


def latest_review(svc, kind, target_id):
    reviews = [
        r
        for r in svc.store.list_records("v3_release_review")
        if r["target_kind"] == kind and r["target_id"] == target_id
    ]
    return max(reviews, key=lambda r: r.get("sequence", 0)) if reviews else None


def review(svc, inp, actor):
    with svc.store.transaction():
        domain = {
            "model": "trained_model",
            "envelope": "optical_envelope",
            "design": "optical_candidate",
        }[inp.target_kind]
        target = svc.get(domain, inp.target_id)
        author = target.get("actor", target.get("created_by"))
        if inp.decision == "approve" and author == actor:
            raise ResearchError(
                "INDEPENDENT_REVIEW_REQUIRED",
                "Authors cannot approve their own artifact.",
                403,
            )
        checks = {}
        if inp.target_kind == "model":
            if not inp.policy_id or target.get("validation_policy_id") != inp.policy_id:
                raise ResearchError(
                    "LOCKED_POLICY_REQUIRED",
                    "Review must use the policy frozen before training.",
                )
            policy = svc.get("release_policy", inp.policy_id)
            metrics = target["report"]
            for split in (
                ["test", "external"] if policy["require_external"] else ["test"]
            ):
                m = metrics.get("split:" + split)
                checks[split] = bool(
                    m
                    and m["patients"] >= policy["minimum_test_patients"]
                    and m["mae_al_se"][0] <= policy["max_al_mae"]
                    and m["mae_al_se"][1] <= policy["max_se_mae"]
                    and m["interval_coverage_al_se"] is not None
                    and min(m["interval_coverage_al_se"]) >= policy["minimum_coverage"]
                )
            if target["algorithm"] == "temporal_transformer":
                comparisons = list(target["baseline_reports"].values())
                comparisons += [
                    m["report"]
                    for m in svc.store.list_records("v3_trained_model")
                    if m["dataset_hash"] == target["dataset_hash"]
                    and m["algorithm"] != "temporal_transformer"
                ]
                for split in (
                    ["test", "external"] if policy["require_external"] else ["test"]
                ):
                    eligible = [
                        m["split:" + split]["mae_al_se"]
                        for m in comparisons
                        if "split:" + split in m
                    ]
                    best = (
                        [min(v[i] for v in eligible) for i in range(2)]
                        if eligible
                        else None
                    )
                    checks["transformer_improves_" + split] = bool(
                        best
                        and all(
                            target["report"]["split:" + split]["mae_al_se"][i]
                            <= best[i] * (1 - policy["minimum_relative_improvement"])
                            for i in range(2)
                        )
                    )
        elif inp.target_kind == "envelope":
            if not inp.evidence_id:
                raise ResearchError(
                    "CALIBRATION_REQUIRED",
                    "An independent measured calibration report is required.",
                )
            evidence = svc.get("optical_calibration", inp.evidence_id)
            from .research_optics import simulator_hash

            checks["matching_envelope"] = evidence["envelope_id"] == inp.target_id
            checks["measured_verification"] = evidence["eligible_for_measured_review"]
            checks["independent_calibrator"] = evidence.get("created_by") != actor
            checks["current_simulator"] = (
                evidence["implementation_sha256"] == simulator_hash()
            )
        else:
            approved = latest_review(svc, "envelope", target["envelope_id"])
            from .research_optics import simulator_hash

            checks["approved_envelope"] = bool(
                approved and approved["decision"] == "approve"
            )
            checks["simulator_constraints_passed"] = target.get("feasible", False)
            calibration = (
                svc.get("optical_calibration", approved["evidence_id"])
                if approved and approved.get("evidence_id")
                else None
            )
            checks["current_simulator"] = bool(
                calibration
                and calibration["implementation_sha256"] == simulator_hash()
                and target.get("simulator_hash") == simulator_hash()
            )
            job = svc.get("optimization", target["run_id"])
            resolved = {
                r["event_id"] for r in svc.store.list_records("v3_event_resolution")
            }
            events = [
                e
                for e in svc.store.list_records("v3_study_event")
                if e["patient_id"] == job["patient_id"]
                and e["severity"] == "severe"
                and not e.get("resolved_at")
                and e["record_id"] not in resolved
            ]
            checks["no_unresolved_severe_event"] = not events
        if inp.decision == "approve" and not all(checks.values()):
            raise ResearchError(
                "RELEASE_GATE_FAILED",
                "The measured evidence or validation thresholds did not pass.",
                409,
            )
        previous = latest_review(svc, inp.target_kind, inp.target_id)
        data = {
            **inp.model_dump(mode="json"),
            "checks": checks,
            "target_hash": digest(target),
            "sequence": previous.get("sequence", 0) + 1 if previous else 1,
            "actor": actor,
            "purpose": "research_only",
            "clinical_use_allowed": False,
        }
        return svc.save("release_review", "REV", data, actor)


def deploy(svc, inp, actor):
    with svc.store.transaction():
        model = svc.get("trained_model", inp.model_id)
        approval = svc.get("release_review", inp.review_id)
        if (
            approval["target_kind"] != "model"
            or approval["target_id"] != inp.model_id
            or approval["decision"] != "approve"
            or approval["target_hash"] != digest(model)
        ):
            raise ResearchError(
                "APPROVAL_MISMATCH",
                "Approval does not match this immutable model artifact.",
            )
        latest = latest_review(svc, "model", inp.model_id)
        if not latest or latest["record_id"] != inp.review_id:
            raise ResearchError(
                "APPROVAL_WITHDRAWN", "The supplied approval has been superseded.", 409
            )
        if actor in {approval["actor"], model["actor"]}:
            raise ResearchError(
                "SEPARATION_OF_DUTIES", "Deployment requires a separate operator.", 403
            )
        history = deployment_history(svc.store)
        event = svc.save(
            "model_deployment",
            "DEP3",
            {
                **inp.model_dump(),
                "actor": actor,
                "previous_deployment_id": history[-1]["deployment_id"]
                if history
                else None,
                "action": "promote",
                "clinical_use_allowed": False,
            },
            actor,
        )
        svc.store.append_related(
            "v3_npm_deployment",
            "npm-research",
            {
                "deployment_id": event["record_id"],
                "model_id": inp.model_id,
                "sequence": len(history) + 1,
            },
        )
        return event


def rollback(svc, inp, actor):
    with svc.store.transaction():
        history = deployment_history(svc.store)
        target = svc.get("model_deployment", inp.target_deployment_id)
        if not history or target["record_id"] not in {
            r["deployment_id"] for r in history[:-1]
        }:
            raise ResearchError(
                "INVALID_ROLLBACK_TARGET",
                "Rollback must restore a previously deployed artifact.",
            )
        current = latest_review(svc, "model", target["model_id"])
        if not current or current["decision"] != "approve":
            raise ResearchError(
                "APPROVAL_WITHDRAWN",
                "Rollback target no longer has a valid approval.",
                409,
            )
        event = svc.save(
            "model_deployment",
            "DEP3",
            {
                "model_id": target["model_id"],
                "review_id": target["review_id"],
                "reason": inp.reason,
                "actor": actor,
                "action": "rollback",
                "previous_deployment_id": history[-1]["deployment_id"],
                "clinical_use_allowed": False,
            },
            actor,
        )
        svc.store.append_related(
            "v3_npm_deployment",
            "npm-research",
            {
                "deployment_id": event["record_id"],
                "model_id": target["model_id"],
                "sequence": len(history) + 1,
            },
        )
        return event
