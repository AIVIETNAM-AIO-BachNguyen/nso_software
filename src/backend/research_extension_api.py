"""Additive V3 manufacturing and V3.1 shadow workflows on existing auth/transactions."""

from typing import Annotated
from fastapi import Header, Request
from research_api import (
    Principal,
    router,
    service,
    permit,
    scope,
    record_scope,
    get_record,
    require_feature,
    mutate,
)
from nso import research_manufacturing as manufacturing
from nso import research_adaptive as adaptive

Key = Annotated[str, Header(alias="Idempotency-Key")]


def scoped(user, domain, key):
    record = get_record(domain, key)
    record_scope(user, record)
    return record


def adaptive_scope(user, policy):
    for pid in adaptive.policy_patients(service(), policy):
        scope(user, pid)


def adaptive_model_scope(user, model_id):
    model = get_record("adaptive_model", model_id)
    for pid in model["patient_ids"]:
        scope(user, pid)
    return model


def model_summary(model):
    return {
        k: model[k]
        for k in (
            "record_id",
            "policy_id",
            "actor",
            "evidence_kind",
            "artifact_hash",
            "report",
            "validation_passed",
            "gates",
            "ranking_mode",
            "clinical_use_allowed",
            "model_family",
            "arm_names",
            "comparator",
            "estimand",
        )
        if k in model
    }


@router.post("/manufacturing/plans")
def create_plan(
    inp: manufacturing.ManufacturingPlan,
    request: Request,
    user: Principal,
    key: Key = "",
):
    permit(user, "manufacture")
    scope(user, inp.patient_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.create_plan(service(), inp, user["actor"]),
        201,
    )


@router.post("/manufacturing/reviews")
def review_plan(
    inp: manufacturing.ManufacturingDecision,
    request: Request,
    user: Principal,
    key: Key = "",
):
    permit(user, "approve")
    scoped(user, "manufacturing_plan", inp.plan_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.decide_plan(service(), inp, user["actor"]),
    )


@router.post("/manufacturing/lots")
def create_lot(
    inp: manufacturing.LotRequest, request: Request, user: Principal, key: Key = ""
):
    permit(user, "manufacture")
    scoped(user, "manufacturing_plan", inp.plan_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.create_lot(service(), inp, user["actor"]),
        201,
    )


@router.post("/manufacturing/qc")
def record_qc(
    inp: manufacturing.QCRequest, request: Request, user: Principal, key: Key = ""
):
    permit(user, "manufacture")
    scoped(user, "manufacturing_lot", inp.lot_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.record_qc(service(), inp, user["actor"]),
    )


@router.post("/manufacturing/exposures")
def record_exposure(
    inp: manufacturing.DispenseRequest, request: Request, user: Principal, key: Key = ""
):
    permit(user, "clinical")
    scoped(user, "manufacturing_lot", inp.lot_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.record_dispense(service(), inp, user["actor"]),
    )


@router.post("/manufacturing/outcomes")
def record_outcome(
    inp: manufacturing.ManufacturingOutcome,
    request: Request,
    user: Principal,
    key: Key = "",
):
    permit(user, "clinical")
    scoped(user, "manufacturing_lot", inp.lot_id)
    require_feature("manufacturing")
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: manufacturing.record_outcome(service(), inp, user["actor"]),
    )


@router.get("/manufacturing/cases/{case_id}/trace")
def manufacturing_trace(case_id: str, user: Principal):
    permit(user, "read")
    require_feature("manufacturing")
    try:
        case = service().store.get_record("case", case_id)
    except KeyError:
        from research_api import fail

        fail("NOT_FOUND", "Case unavailable.", 404)
    scope(user, case["patient_id"])
    return manufacturing.trace(service(), case_id)


@router.post("/adaptive/policies")
def adaptive_policy(
    inp: adaptive.AdaptivePolicy, request: Request, user: Principal, key: Key = ""
):
    permit(user, "adaptive")
    require_feature("adaptive_ranking")
    for cid in (inp.train_cohort_id, inp.test_cohort_id, inp.external_cohort_id):
        record_scope(user, get_record("cohort", cid))
    if inp.prior_model_id:
        adaptive_model_scope(user, inp.prior_model_id)
    return mutate(
        request, user, inp, key, lambda: service_policy(inp, user["actor"]), 201
    )


def service_policy(inp, actor):
    result = adaptive.lock_policy(service(), inp, actor)
    return {
        "record_id": result["record_id"],
        "feature_schema": result["feature_schema"],
        "clinical_use_allowed": False,
    }


@router.post("/adaptive/train")
def adaptive_train(
    inp: adaptive.AdaptiveTrain, request: Request, user: Principal, key: Key = ""
):
    permit(user, "adaptive")
    require_feature("adaptive_ranking")
    adaptive_scope(user, get_record("adaptive_policy", inp.policy_id))
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: model_summary(adaptive.train(service(), inp, user["actor"])),
        201,
    )


@router.get("/adaptive/models/{model_id}")
def adaptive_model(model_id: str, user: Principal):
    permit(user, "read")
    require_feature("adaptive_ranking")
    return model_summary(adaptive_model_scope(user, model_id))


@router.post("/adaptive/reviews")
def adaptive_review(
    inp: adaptive.AdaptiveReview, request: Request, user: Principal, key: Key = ""
):
    permit(user, "validate")
    require_feature("adaptive_ranking")
    adaptive_model_scope(user, inp.model_id)
    return mutate(
        request, user, inp, key, lambda: adaptive.review(service(), inp, user["actor"])
    )


@router.post("/adaptive/deployments")
def adaptive_deploy(
    inp: adaptive.ShadowDeployment, request: Request, user: Principal, key: Key = ""
):
    permit(user, "deploy")
    require_feature("adaptive_ranking")
    adaptive_model_scope(user, inp.model_id)
    return mutate(
        request, user, inp, key, lambda: adaptive.deploy(service(), inp, user["actor"])
    )


@router.post("/adaptive/shadow")
def adaptive_shadow(
    inp: adaptive.ShadowRequest, request: Request, user: Principal, key: Key = ""
):
    permit(user, "adaptive")
    require_feature("adaptive_ranking")
    scope(user, inp.patient_id)
    # The model needs both analysis support and engineering approval. Ranking
    # never invokes manufacturing and ignores any treatment assignment action.
    return mutate(
        request, user, inp, key, lambda: adaptive.shadow(service(), inp, user["actor"])
    )


@router.post("/adaptive/outcomes")
def adaptive_outcome(
    inp: adaptive.ShadowOutcome, request: Request, user: Principal, key: Key = ""
):
    permit(user, "clinical")
    require_feature("adaptive_ranking")
    scoped(user, "adaptive_shadow", inp.shadow_id)
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: adaptive.followup(service(), inp, user["actor"]),
    )


@router.get("/adaptive/models/{model_id}/monitor")
def adaptive_monitor(model_id: str, user: Principal):
    permit(user, "read")
    require_feature("adaptive_ranking")
    adaptive_model_scope(user, model_id)
    for log in adaptive.rows(service(), "adaptive_shadow", "model_id", model_id):
        record_scope(user, log)
    return adaptive.monitor(service(), model_id)


@router.get("/adaptive/health")
def adaptive_health():
    from research_api import enabled

    return {
        "status": "ok",
        "enabled": enabled("adaptive_ranking"),
        "mode": "shadow_only",
        "clinical_use_allowed": False,
    }


@router.get("/manufacturing/health")
def manufacturing_health():
    from research_api import enabled

    return {
        "status": "ok",
        "enabled": enabled("manufacturing"),
        "recipe_kind": "protected_reference",
        "machine_instructions": False,
        "clinical_use_allowed": False,
    }


from nso.research_multiarm import (
    MultiArmCohort,
    MultiArmPolicy,
    freeze_cohort as freeze_multiarm,
)


@router.post("/adaptive/multiarm/cohorts")
def multiarm_cohort(
    inp: MultiArmCohort, request: Request, user: Principal, key: Key = ""
):
    permit(user, "adaptive")
    require_feature("adaptive_ranking")
    for member in inp.members:
        scope(user, member.patient_id)
    return mutate(
        request,
        user,
        inp,
        key,
        lambda: freeze_multiarm(service(), inp, user["actor"]),
        201,
    )


@router.post("/adaptive/multiarm/policies")
def multiarm_policy(
    inp: MultiArmPolicy, request: Request, user: Principal, key: Key = ""
):
    permit(user, "adaptive")
    require_feature("adaptive_ranking")
    for cid in (inp.train_cohort_id, inp.test_cohort_id, inp.external_cohort_id):
        record_scope(user, get_record("cohort", cid))
    if inp.prior_model_id:
        adaptive_model_scope(user, inp.prior_model_id)
    return mutate(
        request, user, inp, key, lambda: service_policy(inp, user["actor"]), 201
    )


@router.get("/adaptive/models/{model_id}/design-analysis")
def design_analysis(model_id: str, user: Principal):
    permit(user, "read")
    require_feature("adaptive_ranking")
    model = adaptive_model_scope(user, model_id)
    report = model.get(
        "incremental_design_report",
        {
            "status": "unavailable",
            "reason": "LEGACY_BINARY_MODEL",
            "causal_design_effects_identified": False,
        },
    )

    return {**report, "evidence_kind": model["evidence_kind"]}


@router.get("/adaptive/shadows/{shadow_id}")
def inspect_shadow(shadow_id: str, user: Principal):
    permit(user, "read")
    require_feature("adaptive_ranking")
    record = scoped(user, "adaptive_shadow", shadow_id)
    return {k: v for k, v in record.items() if k != "features"}
