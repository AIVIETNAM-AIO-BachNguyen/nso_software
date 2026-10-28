"""Explicit research manufacturing bridge. Recipes are protected reference artifacts.

Synthetic rehearsals cannot become measured production. No machine job, shipment,
prescription or adaptive treatment assignment is issued by this module.
"""

from datetime import date
from typing import Literal
from pydantic import Field, model_validator
from .engineering import ClinicalDigitalThread
from .research import ResearchError, digest
from .research_contracts import Contract, PatientScope, Outcome
from .research_release import latest_review
from .research_optics import simulator_hash


class QCRequirement(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    unit: str = Field(min_length=1, max_length=30)
    lower: float
    upper: float

    @model_validator(mode="after")
    def ordered(self):
        if self.lower >= self.upper:
            raise ValueError("QC limits must be strictly ordered")
        return self


class ManufacturingPlan(PatientScope):
    prediction_id: str
    candidate_id: str
    mode: Literal["synthetic_rehearsal", "measured_research"]
    arm: Literal["SA_ONLY", "SA_BN", "SA_BN_FIBER"]
    process_reference: str = Field(min_length=5, max_length=200)
    material_code: str = Field(min_length=2, max_length=100)
    qc_requirements: list[QCRequirement] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique(self):
        if len({r.name for r in self.qc_requirements}) != len(self.qc_requirements):
            raise ValueError("QC names must be unique")
        return self


class ManufacturingDecision(Contract):
    plan_id: str
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=20, max_length=2000)
    process_qualification_reference: str = Field(min_length=5, max_length=200)


class LotRequest(Contract):
    plan_id: str
    lot_code: str = Field(min_length=3, max_length=100)
    manufacturer_id: str = Field(min_length=2, max_length=100)
    facility_id: str = Field(min_length=2, max_length=100)


class QCValue(Contract):
    name: str
    actual: float
    unit: str


class QCRequest(Contract):
    lot_id: str
    measurements: list[QCValue] = Field(min_length=1, max_length=12)
    evidence_reference: str = Field(min_length=5, max_length=200)


class DispenseRequest(Contract):
    lot_id: str
    start_at: date
    end_at: date | None = None
    adherence: float = Field(ge=0, le=1)
    authorization_reference: str = Field(min_length=5, max_length=200)

    @model_validator(mode="after")
    def dates(self):
        if self.end_at and self.end_at < self.start_at:
            raise ValueError("End precedes start")
        return self


class ManufacturingOutcome(Outcome):
    lot_id: str


def rows(svc, domain, field, value):
    return [r for r in svc.store.list_records("v3_" + domain) if r.get(field) == value]


def synthetic_case(svc, scope):
    return svc.case(scope).get("indication_code") == "SYNTHETIC"


def check_candidate(svc, plan, measured=False):
    if digest(svc.get("prediction", plan["prediction_id"])) != plan["prediction_hash"]:
        raise ResearchError(
            "ARTIFACT_CHANGED", "Frozen prediction integrity check failed.", 409
        )
    candidate = svc.get("optical_candidate", plan["candidate_id"])
    if not candidate["feasible"] or candidate["simulator_hash"] != simulator_hash():
        raise ResearchError(
            "STALE_OR_INFEASIBLE_DESIGN",
            "Recompute the candidate with the current simulator.",
            409,
        )
    if digest(candidate) != plan["candidate_hash"]:
        raise ResearchError(
            "ARTIFACT_CHANGED", "Candidate integrity check failed.", 409
        )
    if (
        digest(svc.get("optical_envelope", candidate["envelope_id"]))
        != plan["envelope_hash"]
    ):
        raise ResearchError("ARTIFACT_CHANGED", "Envelope integrity check failed.", 409)
    resolved = {r["event_id"] for r in svc.store.list_records("v3_event_resolution")}
    if any(
        e["patient_id"] == plan["patient_id"]
        and e["severity"] == "severe"
        and not e.get("resolved_at")
        and e["record_id"] not in resolved
        for e in svc.store.list_records("v3_study_event")
    ):
        raise ResearchError(
            "UNRESOLVED_SAFETY_EVENT",
            "Resolve severe safety events before proceeding.",
            409,
        )
    parameters = candidate["parameters"]
    noise, fiber = parameters["noise_height_um"], parameters["fiber_height_um"]
    compatible = {
        "SA_ONLY": noise == 0 and fiber == 0,
        "SA_BN": noise > 0 and fiber == 0,
        "SA_BN_FIBER": noise > 0 and fiber > 0,
    }
    if not compatible[plan["arm"]]:
        raise ResearchError(
            "ARM_DESIGN_MISMATCH",
            "Protected optical parameters do not match the declared research arm.",
            409,
        )
    if measured:
        review = latest_review(svc, "design", plan["candidate_id"])
        envelope_review = latest_review(svc, "envelope", candidate["envelope_id"])
        if (
            not review
            or review["decision"] != "approve"
            or review["target_hash"] != digest(candidate)
            or not envelope_review
            or envelope_review["decision"] != "approve"
        ):
            raise ResearchError(
                "DESIGN_NOT_APPROVED",
                "Current independently approved optical design/envelope required.",
                409,
            )
        calibration = svc.get("optical_calibration", envelope_review["evidence_id"])
        if (
            not calibration["eligible_for_measured_review"]
            or calibration["implementation_sha256"] != simulator_hash()
        ):
            raise ResearchError(
                "CALIBRATION_REQUIRED", "Current measured calibration required.", 409
            )
    return candidate


def visit_link(svc, patient_scope, observed_at, source_kind, source_id, actor):
    """Reuse a V2 Visit identity; preserve measurements in their source records.

    A metadata-only imported visit never relabels imputed research data as a V2
    objective measurement. V3 observations/outcomes remain the measured source.
    """
    case = svc.case(patient_scope)
    visits = [
        v
        for v in svc.store.list_records("visit")
        if v["case_id"] == patient_scope.case_id and v["visit_date"] == observed_at
    ]
    if len(visits) > 1:
        raise ResearchError(
            "AMBIGUOUS_VISIT",
            "Reconcile multiple visit identities for the same case/date before linking.",
        )
    if visits:
        visit_id = visits[0]["visit_id"]
    else:
        visit = ClinicalDigitalThread(svc.store).record_visit(
            case_id=patient_scope.case_id,
            visit_code="V3-" + source_kind,
            visit_type="baseline" if source_kind == "prediction" else "followup",
            visit_date=observed_at,
            clinician_id=case.get("clinician_id", "research-import"),
            site_id=case["site_id"],
            measurements=[],
            actor=actor,
        )
        visit_id = visit["visit_id"]
    link = svc.save(
        "manufacturing_visit_link",
        "MVIS",
        {
            "patient_id": patient_scope.patient_id,
            "case_id": patient_scope.case_id,
            "eye": patient_scope.eye,
            "visit_id": visit_id,
            "visit_at": observed_at,
            "source_kind": source_kind,
            "source_id": source_id,
            "measurement_values_copied": False,
        },
        actor,
    )
    return visit_id, link["record_id"]


def create_plan(svc, inp, actor):
    with svc.store.transaction():
        is_synthetic = synthetic_case(svc, inp)
        if is_synthetic != (inp.mode == "synthetic_rehearsal"):
            raise ResearchError(
                "EVIDENCE_MODE_MISMATCH",
                "Synthetic cases require synthetic rehearsal; measured research requires a non-synthetic case.",
                409,
            )
        prediction = svc.get("prediction", inp.prediction_id)
        if any(
            prediction[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")
        ):
            raise ResearchError(
                "FORBIDDEN", "Prediction does not match patient, case and eye.", 403
            )
        if prediction.get("status") == "abstained":
            raise ResearchError(
                "INVALID_PREDICTION",
                "An abstained forecast cannot anchor a manufacturing plan.",
                409,
            )
        candidate = svc.get("optical_candidate", inp.candidate_id)
        job = svc.get("optimization", candidate["run_id"])
        if any(job[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")):
            raise ResearchError(
                "FORBIDDEN", "Candidate does not match patient, case and eye.", 403
            )
        index_rows = [
            r
            for r in prediction["history_snapshot"]
            if r["visit_at"] == prediction["index_date"]
            and r["al_status"] == "measured"
            and r["quality_flag"] == "ACCEPTED"
        ]
        if not index_rows:
            raise ResearchError(
                "INSUFFICIENT_HISTORY",
                "A manufacturing plan requires accepted measured AL at the forecast index.",
            )
        index_visit_id, index_visit_link_id = visit_link(
            svc, inp, prediction["index_date"], "prediction", inp.prediction_id, actor
        )
        data = {
            **inp.model_dump(mode="json"),
            "index_visit_id": index_visit_id,
            "index_visit_link_id": index_visit_link_id,
            "candidate_hash": digest(candidate),
            "envelope_hash": digest(
                svc.get("optical_envelope", candidate["envelope_id"])
            ),
            "prediction_hash": digest(prediction),
            "actor": actor,
            "clinical_use_allowed": False,
            "machine_instructions": False,
        }
        check_candidate(svc, data, inp.mode == "measured_research")
        return public_plan(svc.save("manufacturing_plan", "MPL", data, actor))


def public_plan(plan):
    return {
        k: plan.get(k)
        for k in (
            "record_id",
            "patient_id",
            "case_id",
            "eye",
            "prediction_id",
            "candidate_id",
            "mode",
            "arm",
            "clinical_use_allowed",
            "machine_instructions",
            "index_visit_id",
            "index_visit_link_id",
        )
    }


def latest_decision(svc, plan_id):
    history = rows(svc, "manufacturing_decision", "plan_id", plan_id)
    return max(history, key=lambda r: r["sequence"]) if history else None


def approved_plan(svc, plan_id):
    plan = svc.get("manufacturing_plan", plan_id)
    decision = latest_decision(svc, plan_id)
    if (
        not decision
        or decision["decision"] != "approve"
        or decision["plan_hash"] != digest(plan)
    ):
        raise ResearchError(
            "MANUFACTURING_APPROVAL_REQUIRED",
            "A current independent approval of this immutable plan is required.",
            409,
        )
    check_candidate(svc, plan, plan["mode"] == "measured_research")
    return plan, decision


def decide_plan(svc, inp, actor):
    with svc.store.transaction():
        plan = svc.get("manufacturing_plan", inp.plan_id)
        if inp.decision == "approve":
            if actor == plan["actor"]:
                raise ResearchError(
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "Plan authors cannot approve their own plans.",
                    403,
                )
            check_candidate(svc, plan, plan["mode"] == "measured_research")
        previous = latest_decision(svc, inp.plan_id)
        return svc.save(
            "manufacturing_decision",
            "MREV",
            {
                **inp.model_dump(),
                "sequence": previous["sequence"] + 1 if previous else 1,
                "plan_hash": digest(plan),
                "actor": actor,
                "clinical_use_allowed": False,
            },
            actor,
        )


def create_lot(svc, inp, actor):
    with svc.store.transaction():
        plan, decision = approved_plan(svc, inp.plan_id)
        if actor == decision["actor"]:
            raise ResearchError(
                "SEPARATION_OF_DUTIES",
                "Manufacturing operator must differ from the approver.",
                403,
            )
        if rows(svc, "manufacturing_lot", "lot_code", inp.lot_code):
            raise ResearchError("DUPLICATE_LOT", "Lot code already exists.", 409)
        candidate = svc.get("optical_candidate", plan["candidate_id"])
        thread = ClinicalDigitalThread(svc.store)
        design_id = "RD3-" + digest(plan)[:24].upper()
        prior = rows(svc, "manufacturing_lot", "plan_id", inp.plan_id)
        if prior:
            recipe = {k: prior[0][k] for k in ("recipe_id", "recipe_version_id")}
        else:
            recipe = thread.register_recipe(
                design_id=design_id,
                design_version=plan["candidate_hash"],
                parameters={
                    "reference_optical_parameters": candidate["parameters"],
                    "simulation_seed": svc.get("optimization", candidate["run_id"])[
                        "seed"
                    ],
                    "envelope": svc.get("optical_envelope", candidate["envelope_id"]),
                    "machine_instructions": False,
                    "plan_id": inp.plan_id,
                },
                tolerances={
                    "requirements": plan["qc_requirements"],
                    "process_reference": plan["process_reference"],
                    "evidence_mode": plan["mode"],
                },
                actor=actor,
            )
        lot = thread.create_manufacturing_lot(
            recipe_version_id=recipe["recipe_version_id"],
            lot_code=inp.lot_code,
            material_code=plan["material_code"],
            process_version=plan["process_reference"],
            manufacturer_id=inp.manufacturer_id,
            facility_id=inp.facility_id,
            actor=actor,
            research_context={
                "mode": plan["mode"],
                "clinical_use_allowed": False,
                "machine_instructions": False,
            },
        )
        # Shared V2 domain stores physical identifiers; V3 stores research provenance.
        svc.store.put_record(
            "v3_manufacturing_lot",
            lot["lot_id"],
            {
                "record_id": lot["lot_id"],
                **lot,
                **{
                    k: plan[k]
                    for k in (
                        "patient_id",
                        "case_id",
                        "eye",
                        "mode",
                        "prediction_id",
                        "candidate_id",
                    )
                },
                "plan_id": inp.plan_id,
                "decision_id": decision["record_id"],
                "clinical_use_allowed": False,
            },
        )
        svc.store.append_audit(
            {
                "object_id": lot["lot_id"],
                "action": "V3_RESEARCH_LOT_LINKED",
                "actor": actor,
                "result": "success",
            }
        )
        return svc.get("manufacturing_lot", lot["lot_id"])


def record_qc(svc, inp, actor):
    with svc.store.transaction():
        lot = svc.get("manufacturing_lot", inp.lot_id)
        plan, _ = approved_plan(svc, lot["plan_id"])
        required = {r["name"]: r for r in plan["qc_requirements"]}
        supplied = {m.name: m for m in inp.measurements}
        if len(supplied) != len(inp.measurements) or set(supplied) != set(required):
            raise ResearchError(
                "INCOMPLETE_QC", "Supply each locked QC metric exactly once."
            )
        passed = True
        for name, rule in required.items():
            m = supplied[name]
            if m.unit != rule["unit"]:
                raise ResearchError(
                    "QC_UNIT_MISMATCH", "QC units differ from the locked plan."
                )
            passed &= rule["lower"] <= m.actual <= rule["upper"]
        protected = svc.save(
            "manufacturing_qc",
            "MQC",
            {
                **inp.model_dump(),
                "plan_id": lot["plan_id"],
                "patient_id": lot["patient_id"],
                "case_id": lot["case_id"],
                "passed": bool(passed),
            },
            actor,
        )
        # Reuse legacy QC identity without exposing the protected measurements.
        qc = ClinicalDigitalThread(svc.store).record_qc(
            lot_id=inp.lot_id,
            measurement_type="v3_locked_plan",
            target=None,
            actual=None,
            unit="protected",
            passed=passed,
            measurement_data={"evidence_id": protected["record_id"]},
            actor=actor,
        )
        return {
            "qc_id": qc["qc_id"],
            "evidence_id": protected["record_id"],
            "lot_id": inp.lot_id,
            "passed": bool(passed),
            "clinical_use_allowed": False,
        }


def lot_ready(svc, lot_id):
    lot = svc.get("manufacturing_lot", lot_id)
    plan, _ = approved_plan(svc, lot["plan_id"])
    qcs = rows(svc, "manufacturing_qc", "lot_id", lot_id)
    if not qcs or any(not q["passed"] for q in qcs):
        raise ResearchError(
            "MISSING_OR_FAILED_QC",
            "Every lot requires complete passing QC; failed lots remain quarantined. Rework requires a new lot.",
            409,
        )
    return lot, plan


def record_dispense(svc, inp, actor):
    from .research_contracts import Exposure

    with svc.store.transaction():
        lot, plan = lot_ready(svc, inp.lot_id)
        prediction = svc.get("prediction", plan["prediction_id"])
        if inp.start_at < date.fromisoformat(prediction["index_date"]):
            raise ResearchError(
                "INVALID_EXPOSURE_DATE", "Exposure cannot precede the indexed forecast."
            )
        if rows(svc, "manufacturing_dispense", "lot_id", inp.lot_id):
            raise ResearchError(
                "LOT_ALREADY_LINKED",
                "A patient-specific lot can only be linked once.",
                409,
            )
        exposure = svc.exposure(
            Exposure(
                patient_id=lot["patient_id"],
                case_id=lot["case_id"],
                eye=lot["eye"],
                arm=plan["arm"],
                design_id=lot["design_id"],
                start_at=inp.start_at,
                end_at=inp.end_at,
                adherence=inp.adherence,
            ),
            actor,
        )
        thread = ClinicalDigitalThread(svc.store)
        eye_id = thread.ensure_eyes(lot["patient_id"], actor=actor)[lot["eye"]]
        physical = thread.record_exposure(
            case_id=lot["case_id"],
            eye_id=eye_id,
            lot_id=inp.lot_id,
            exposure_start=inp.start_at.isoformat(),
            exposure_end=inp.end_at.isoformat() if inp.end_at else None,
            compliance=str(inp.adherence),
            actor=actor,
        )
        return svc.save(
            "manufacturing_dispense",
            "MDSP",
            {
                **inp.model_dump(mode="json"),
                **{
                    k: lot[k]
                    for k in ("patient_id", "case_id", "eye", "mode", "prediction_id")
                },
                "research_exposure_id": exposure["record_id"],
                "product_exposure_id": physical["exposure_id"],
                "clinical_use_allowed": False,
            },
            actor,
        )


def record_outcome(svc, inp, actor):
    with svc.store.transaction():
        lot = svc.get("manufacturing_lot", inp.lot_id)
        if (
            lot["mode"] == "measured_research"
            and inp.observation.visit_at > date.today()
        ):
            raise ResearchError(
                "FUTURE_OUTCOME", "Measured follow-up cannot be in the future."
            )
        if lot["prediction_id"] != inp.prediction_id:
            raise ResearchError(
                "FORBIDDEN", "Outcome prediction does not belong to this lot.", 403
            )
        dispenses = rows(svc, "manufacturing_dispense", "lot_id", inp.lot_id)
        if not dispenses or inp.observation.visit_at <= date.fromisoformat(
            dispenses[0]["start_at"]
        ):
            raise ResearchError(
                "EXPOSURE_REQUIRED", "Follow-up must be after the recorded exposure."
            )
        outcome = svc.evaluate(
            Outcome(prediction_id=inp.prediction_id, observation=inp.observation), actor
        )
        eligible = outcome["metrics"]["al"]["primary_endpoint_eligible"]
        patient_scope = PatientScope(
            patient_id=lot["patient_id"], case_id=lot["case_id"], eye=lot["eye"]
        )
        followup_visit_id, followup_visit_link_id = visit_link(
            svc,
            patient_scope,
            inp.observation.visit_at.isoformat(),
            "outcome",
            outcome["record_id"],
            actor,
        )
        return svc.save(
            "manufacturing_validation",
            "MVAL",
            {
                "lot_id": inp.lot_id,
                "plan_id": lot["plan_id"],
                "prediction_id": inp.prediction_id,
                "outcome_id": outcome["record_id"],
                "followup_visit_id": followup_visit_id,
                "followup_visit_link_id": followup_visit_link_id,
                "patient_id": lot["patient_id"],
                "case_id": lot["case_id"],
                "eye": lot["eye"],
                "primary_endpoint_eligible": eligible,
                "mode": lot["mode"],
                "clinical_use_allowed": False,
                "model_approval_granted": False,
            },
            actor,
        )


def trace(svc, case_id):
    plans = rows(svc, "manufacturing_plan", "case_id", case_id)
    result = []
    for plan in plans:
        lots = rows(svc, "manufacturing_lot", "plan_id", plan["record_id"])
        result.append(
            {
                "plan": public_plan(plan),
                "approval": latest_decision(svc, plan["record_id"]),
                "observation_ids": [
                    r["record_id"]
                    for r in svc.store.list_records("v3_observation")
                    if r["case_id"] == case_id and r["eye"] == plan["eye"]
                ],
                "lots": [
                    {
                        **lot,
                        "qc": [
                            {"qc_id": r["record_id"], "passed": r["passed"]}
                            for r in rows(
                                svc, "manufacturing_qc", "lot_id", lot["record_id"]
                            )
                        ],
                        "exposures": rows(
                            svc, "manufacturing_dispense", "lot_id", lot["record_id"]
                        ),
                        "validations": rows(
                            svc, "manufacturing_validation", "lot_id", lot["record_id"]
                        ),
                    }
                    for lot in lots
                ],
            }
        )
    return {
        "case_id": case_id,
        "manufacturing_threads": result,
        "clinical_use_allowed": False,
        "machine_instructions": False,
    }
