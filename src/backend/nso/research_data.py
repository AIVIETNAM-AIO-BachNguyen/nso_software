"""Research protocol records and append-only, optimistic observation corrections."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .research_contracts import Contract, Observation, PatientScope
from .research import ResearchError


class Correction(PatientScope):
    observation_id: str
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=10, max_length=1000)
    replacement: Observation


class Protocol(Contract):
    name: str = Field(min_length=3, max_length=120)
    version: str = Field(min_length=1, max_length=60)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=30)
    exclusion_criteria: list[str] = Field(min_length=1, max_length=30)
    estimand: str = Field(min_length=20, max_length=2000)
    assignment: Literal["randomized", "observational"]
    analysis_population: Literal["intention_to_treat", "per_protocol"] = (
        "intention_to_treat"
    )
    covariates: list[
        Literal["age", "baseline_al", "baseline_se", "prior_al_slope", "sex_code"]
    ] = Field(min_length=1, max_length=5)
    missingness_plan: str = Field(min_length=20, max_length=2000)
    switching_plan: str = Field(min_length=20, max_length=2000)
    safety_plan: str = Field(min_length=20, max_length=2000)
    analysis_plan: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def unique_covariates(self):
        if len(set(self.covariates)) != len(self.covariates):
            raise ValueError("protocol covariates must be unique")
        return self


class Enrollment(PatientScope):
    protocol_id: str
    index_date: date
    eligible: bool
    assigned_arm: Literal["NONE", "SA_ONLY", "SA_BN", "SA_BN_FIBER", "OTHER"]
    eligibility_reasons: list[str] = Field(min_length=1, max_length=30)
    age: float = Field(ge=3, le=100)
    baseline_al: float = Field(ge=18, le=35)
    baseline_se: float = Field(ge=-20, le=15)
    prior_al_slope: float = Field(ge=-2, le=3)
    sex_code: Literal[0, 1]
    allocation_reference: str | None = Field(default=None, max_length=200)


class StudyEvent(PatientScope):
    protocol_id: str
    event_at: date
    kind: Literal[
        "adverse_event",
        "lost_followup",
        "withdrawal",
        "protocol_deviation",
        "followup_completed",
    ]
    severity: Literal["mild", "moderate", "severe", "not_applicable"]
    description: str = Field(min_length=10, max_length=2000)
    resolved_at: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.resolved_at and self.resolved_at < self.event_at:
            raise ValueError("resolution precedes event")
        if self.kind == "adverse_event" and self.severity == "not_applicable":
            raise ValueError("adverse events require severity")
        return self


class EventResolution(PatientScope):
    event_id: str = Field(min_length=1, max_length=120)
    resolved_at: date
    reason: str = Field(min_length=10, max_length=1000)


def resolve_event(svc, inp, actor):
    with svc.store.transaction():
        svc.case(inp)
        original = svc.get("study_event", inp.event_id)
        if any(
            original[k] != getattr(inp, k) for k in ("patient_id", "case_id", "eye")
        ):
            raise ResearchError(
                "FORBIDDEN", "Event belongs to another patient/eye.", 403
            )
        if inp.resolved_at.isoformat() < original["event_at"]:
            raise ResearchError(
                "INVALID_RESOLUTION_DATE", "Resolution cannot precede the event."
            )
        if original.get("resolved_at") or any(
            r["event_id"] == inp.event_id
            for r in svc.store.list_records("v3_event_resolution")
        ):
            raise ResearchError(
                "ALREADY_RESOLVED", "This event already has a resolution record.", 409
            )
        return svc.save("event_resolution", "RES", inp.model_dump(mode="json"), actor)


def correct(svc, inp, actor):
    with svc.store.transaction():
        svc.case(inp)
        original = svc.get("observation", inp.observation_id)
        if any(
            original.get(k) != getattr(inp, k) for k in ("patient_id", "case_id", "eye")
        ):
            raise ResearchError(
                "FORBIDDEN", "Observation belongs to another scope.", 403
            )
        versions = [
            r
            for r in svc.store.list_records("v3_observation_correction")
            if r["observation_id"] == inp.observation_id
        ]
        revision = max((r["revision"] for r in versions), default=0)
        if revision != inp.expected_revision:
            raise ResearchError(
                "REVISION_CONFLICT",
                "Refresh the observation before correcting it.",
                409,
            )
        if inp.replacement.visit_at.isoformat() != original["visit_at"]:
            raise ResearchError(
                "DATE_IDENTITY_CHANGE",
                "Reject the old row and import a new date instead of moving its identity.",
            )
        return svc.save(
            "observation_correction",
            "COR",
            {**inp.model_dump(mode="json"), "revision": revision + 1},
            actor,
        )


def enroll(svc, inp, actor):
    with svc.store.transaction():
        svc.case(inp)
        protocol = svc.get("protocol", inp.protocol_id)
        if protocol["assignment"] == "randomized" and not inp.allocation_reference:
            raise ResearchError(
                "ALLOCATION_REFERENCE_REQUIRED",
                "Record the trial allocation reference.",
            )
        existing = [
            r
            for r in svc.records("enrollment", inp)
            if r["protocol_id"] == inp.protocol_id
        ]
        if existing:
            raise ResearchError(
                "DUPLICATE_ENROLLMENT",
                "Enrollment is immutable; create a new protocol version for corrections.",
                409,
            )
        return svc.save("enrollment", "ENR", inp.model_dump(mode="json"), actor)
