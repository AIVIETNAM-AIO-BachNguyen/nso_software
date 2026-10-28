"""Strict, versioned research contracts. Dates are ISO calendar dates, durations real days."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Observation(Contract):
    visit_at: date
    se_d: float | None = Field(default=None, ge=-20, le=15)
    al_mm: float | None = Field(default=None, ge=18, le=35)
    se_status: Literal["measured", "imputed", "missing"] = "missing"
    al_status: Literal["measured", "imputed", "missing"] = "missing"
    measurement_method: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=120)
    quality_flag: Literal["ACCEPTED", "WARNING", "REJECTED"] = "ACCEPTED"

    @model_validator(mode="after")
    def provenance(self):
        for name in ("se", "al"):
            value = getattr(self, "se_d" if name == "se" else "al_mm")
            if (value is None) != (getattr(self, name + "_status") == "missing"):
                raise ValueError(
                    f"{name}: value and measured/imputed/missing status disagree"
                )
        if self.al_mm is None and self.se_d is None:
            raise ValueError("at least one observation value is required")
        return self


class PatientScope(Contract):
    patient_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    eye: Literal["OD", "OS"]


class ObservationBatch(PatientScope):
    observations: list[Observation] = Field(min_length=1, max_length=200)


class Exposure(PatientScope):
    arm: Literal["NONE", "SA_ONLY", "SA_BN", "SA_BN_FIBER", "OTHER"]
    start_at: date
    end_at: date | None = None
    design_id: str | None = Field(default=None, max_length=120)
    adherence: float | None = Field(default=None, ge=0, le=1)
    discontinuation_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def chronology(self):
        if self.end_at and self.end_at < self.start_at:
            raise ValueError("exposure end precedes start")
        return self


class Forecast(PatientScope):
    index_date: date = Field(le=date(9997, 12, 31))
    horizons_months: list[Literal[6, 12, 24]] = Field(
        default=[6, 12, 24], min_length=1, max_length=3
    )
    model_id: str = Field(default="npm-history-linear-v1", min_length=1, max_length=120)
    index_age: float | None = Field(default=None, ge=3, le=100)
    # This is an attestation, checked against recorded exposure history as well.
    untreated_history_confirmed: bool = False

    @model_validator(mode="after")
    def unique_horizons(self):
        if len(set(self.horizons_months)) != len(self.horizons_months):
            raise ValueError("duplicate horizons")
        return self


class Outcome(Contract):
    prediction_id: str = Field(min_length=1, max_length=120)
    observation: Observation


class Cohort(Contract):
    protocol_id: str | None = None
    cohort_name: str = Field(min_length=1, max_length=120)
    eligibility_version: str = Field(min_length=1, max_length=120)
    assignment: Literal["randomized", "observational"]
    comparator: Literal["NONE", "SA_ONLY", "SA_BN", "SA_BN_FIBER", "OTHER"]
    intervention: Literal["SA_ONLY", "SA_BN", "SA_BN_FIBER", "OTHER"]
    index_date: date = Field(le=date(9998, 12, 31))
    horizon_months: Literal[12] = 12
    # Prospectively prespecified visit window; descriptive endpoints are actual changes.
    visit_window_days: int = Field(default=30, ge=0, le=60)
    members: list[PatientScope] = Field(min_length=2, max_length=500)
    analysis_plan: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def arms(self):
        if self.comparator == self.intervention:
            raise ValueError("intervention and comparator must differ")
        identities = [(x.patient_id, x.eye) for x in self.members]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate cohort member")
        return self


class Estimate(Contract):
    cohort_id: str = Field(min_length=1, max_length=120)


class Optimization(PatientScope):
    objective_version: Literal["optical-quality-v1"] = "optical-quality-v1"
    envelope_id: str = Field(min_length=1, max_length=120)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    candidate_budget: int = Field(default=32, ge=1, le=128)


class DesignApproval(Contract):
    run_id: str = Field(min_length=1, max_length=120)
    design_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=10, max_length=1000)


class BenchmarkSample(PatientScope):
    split: Literal["train", "validation", "test", "external"]
    site_id: str = Field(min_length=1, max_length=120)
    index_date: date
    untreated_history_confirmed: bool
    history: list[Observation] = Field(min_length=1, max_length=200)
    observed: Observation


class Validation(Contract):
    dataset_version: str = Field(min_length=1, max_length=120)
    model_id: Literal["npm-carry-forward-v1", "npm-history-linear-v1"]
    split_strategy: Literal["patient", "temporal", "external_site"]
    samples: list[BenchmarkSample] = Field(min_length=3, max_length=2000)


class HorizonForecast(Contract):
    horizon_months: Literal[6, 12, 24]
    target_at: date
    elapsed_days: int = Field(gt=0)
    se_d: float | None
    al_mm: float | None
    delta_se_d: float | None
    delta_al_mm: float | None
    se_interval: list[float] | None
    al_interval: list[float] | None
    se_reference_at: date | None
    al_reference_at: date | None
    applicability_flags: list[str]


class ForecastResult(Forecast):
    record_id: str
    prediction_id: str
    schema_version: str
    created_at: str
    created_by: str
    dataset_hash: str
    model_artifact_hash: str
    model_registry_id: str
    forecasts: list[HorizonForecast]
    status: Literal["research_only"]
    interval_status: Literal[
        "unavailable_pending_held_out_calibration", "patient_split_calibrated"
    ]
    clinical_use_allowed: Literal[False]


class OptimizationQueued(Contract):
    run_id: str
    status: Literal["queued"]
    clinical_use_allowed: Literal[False]


class OptimizationState(Optimization):
    run_id: str
    record_id: str
    schema_version: str
    created_at: str
    created_by: str
    status: Literal["queued", "blocked", "completed", "failed"]
    clinical_use_allowed: Literal[False]
    feasibility: bool | None = None
    pareto_candidates: list[dict] = Field(default_factory=list)
    optical_metrics: dict | None = None
    code: str | None = None
    message: str | None = None
    completed_at: str | None = None
    calibration_status: str | None = None
    simulator_version: str | None = None
    configuration_hash: str | None = None
