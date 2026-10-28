"""Authenticated workflow endpoints; mounted on the existing V3 router."""

from typing import Annotated

from fastapi import BackgroundTasks, Header, Request

from research_api import (
    Principal,
    get_record,
    mutate,
    permit,
    record_scope,
    require_feature,
    router,
    scope,
    service,
)
from nso.research_data import (
    Correction,
    Enrollment,
    Protocol,
    StudyEvent,
    correct,
    enroll,
    EventResolution,
    resolve_event,
)
from nso.research_learning import TrainRequest
from nso.research_causal import CausalRequest, analyze
from nso.research_optics import Envelope, CalibrationRequest, calibrate
from nso.research_release import (
    Deployment,
    ReleasePolicy,
    Review,
    Rollback,
    deploy,
    review,
    rollback,
)

Key = Annotated[str, Header(alias="Idempotency-Key")]


def model_scope(user, model_id):
    model = get_record("trained_model", model_id)
    for patient_id in model.get("training_patient_ids", []):
        scope(user, patient_id)


@router.post("/observations/correct")
def correction(inp: Correction, request: Request, user: Principal, key: Key = ""):
    permit(user, "clinical")
    scope(user, inp.patient_id)
    return mutate(
        request, user, inp, key, lambda: correct(service(), inp, user["actor"])
    )


@router.post("/studies/protocols")
def protocol(inp: Protocol, request: Request, user: Principal, key: Key = ""):
    permit(user, "ipm")
    require_feature("ipm_research")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: service().save(
            "protocol", "PRO", inp.model_dump(mode="json"), user["actor"]
        ),
        201,
    )


@router.post("/studies/enrollments")
def enrollment(inp: Enrollment, request: Request, user: Principal, key: Key = ""):
    permit(user, "clinical")
    scope(user, inp.patient_id)
    require_feature("ipm_research")
    return mutate(
        request, user, inp, key, lambda: enroll(service(), inp, user["actor"]), 201
    )


@router.post("/studies/events")
def study_event(inp: StudyEvent, request: Request, user: Principal, key: Key = ""):
    permit(user, "clinical")
    scope(user, inp.patient_id)

    def save():
        service().case(inp)
        service().get("protocol", inp.protocol_id)
        enrollment = [
            r
            for r in service().records("enrollment", inp)
            if r["protocol_id"] == inp.protocol_id
        ]
        if (
            len(enrollment) != 1
            or inp.event_at.isoformat() < enrollment[0]["index_date"]
        ):
            from nso.research import ResearchError

            raise ResearchError(
                "ENROLLMENT_REQUIRED",
                "Record a matching enrollment before reporting post-index study events.",
            )
        return service().save(
            "study_event", "SEV", inp.model_dump(mode="json"), user["actor"]
        )

    return mutate(request, user, inp, key, save, 201)


@router.post("/ipm/analyze")
def causal(inp: CausalRequest, request: Request, user: Principal, key: Key = ""):
    permit(user, "ipm")
    require_feature("ipm_research")
    record_scope(user, get_record("cohort", inp.cohort_id))
    return mutate(
        request, user, inp, key, lambda: analyze(service(), inp, user["actor"])
    )


@router.post("/studies/events/resolve")
def event_resolution(
    inp: EventResolution, request: Request, user: Principal, key: Key = ""
):
    permit(user, "clinical")
    scope(user, inp.patient_id)
    return mutate(
        request, user, inp, key, lambda: resolve_event(service(), inp, user["actor"])
    )


@router.post("/models/policies")
def release_policy(
    inp: ReleasePolicy, request: Request, user: Principal, key: Key = ""
):
    permit(user, "validate")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: service().save(
            "release_policy", "POL", inp.model_dump(), user["actor"]
        ),
        201,
    )


@router.post("/models/train", status_code=202)
def train(
    inp: TrainRequest,
    request: Request,
    background: BackgroundTasks,
    user: Principal,
    key: Key = "",
):
    permit(user, "validate")
    require_feature("npm")
    for sample in inp.samples:
        scope(user, sample.patient_id)

    def submit():
        job = service().queue_training(inp, user["actor"])
        background.add_task(service().execute_training, job["record_id"])
        return {
            "run_id": job["record_id"],
            "status": "queued",
            "clinical_use_allowed": False,
        }

    return mutate(request, user, inp, key, submit, 202)


@router.get("/models/training/{run_id}")
def training_status(run_id: str, user: Principal):
    permit(user, "read")
    job = get_record("training_job", run_id)
    for sample in job["request"]["samples"]:
        scope(user, sample["patient_id"])
    return service().training_status(run_id)


@router.get("/models/available")
def models(user: Principal):
    permit(user, "read")
    from nso.research_release import deployment_history, latest_review

    history = deployment_history(service().store)
    active = history[-1]["model_id"] if history else None
    ids = sorted({r["model_id"] for r in history})
    return {
        "models": [
            {"model_id": key, "active": key == active}
            for key in ids
            if latest_review(service(), "model", key)["decision"] == "approve"
        ]
    }


@router.post("/optimizer/envelopes")
def envelope(inp: Envelope, request: Request, user: Principal, key: Key = ""):
    permit(user, "optimizer")
    require_feature("optimizer")

    def save():
        result = service().save(
            "optical_envelope", "ENV", inp.model_dump(mode="json"), user["actor"]
        )
        return {
            "envelope_id": result["record_id"],
            "status": "uncalibrated_reference",
            "clinical_use_allowed": False,
        }

    return mutate(request, user, inp, key, save, 201)


@router.post("/optimizer/calibrations")
def calibration(
    inp: CalibrationRequest, request: Request, user: Principal, key: Key = ""
):
    permit(user, "optimizer")
    require_feature("optimizer")

    def run():
        report = calibrate(service(), inp, user["actor"])
        return {
            k: report[k]
            for k in (
                "record_id",
                "passed",
                "eligible_for_measured_review",
                "simulator_version",
            )
        }

    return mutate(request, user, inp, key, run)


@router.post("/releases/review")
def approve(inp: Review, request: Request, user: Principal, key: Key = ""):
    permit(user, "validate" if inp.target_kind == "model" else "approve")
    if inp.target_kind == "model":
        model_scope(user, inp.target_id)
    elif inp.target_kind == "design":
        candidate = get_record("optical_candidate", inp.target_id)
        record_scope(user, get_record("optimization", candidate["run_id"]))
    return mutate(
        request, user, inp, key, lambda: review(service(), inp, user["actor"])
    )


@router.post("/releases/deploy")
def promote(inp: Deployment, request: Request, user: Principal, key: Key = ""):
    permit(user, "deploy")
    model_scope(user, inp.model_id)
    return mutate(
        request, user, inp, key, lambda: deploy(service(), inp, user["actor"])
    )


@router.post("/releases/rollback")
def restore(inp: Rollback, request: Request, user: Principal, key: Key = ""):
    permit(user, "deploy")
    target = get_record("model_deployment", inp.target_deployment_id)
    model_scope(user, target["model_id"])
    return mutate(
        request, user, inp, key, lambda: rollback(service(), inp, user["actor"])
    )
