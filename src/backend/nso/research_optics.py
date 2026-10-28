"""Restricted scalar Fraunhofer reference engine and constrained Pareto search.

This phase-screen model is an executable engineering reference, not a full
ophthalmic ray tracer. Real-lens calibration and process approval are separate
immutable gates. No optical score is converted into a clinical benefit.
"""

from datetime import date
import hashlib
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from .research import ResearchError, digest
from .research_contracts import Contract

SIMULATOR_VERSION = "scalar-phase-fft-1.0"
PARAMETERS = {"sa_um", "noise_height_um", "fiber_height_um", "fiber_angle_deg"}
PUBLIC_METRICS = {"strehl", "mtf_20", "mtf_50", "glare_fraction", "psf_energy"}


def simulator_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class Envelope(Contract):
    name: str = Field(min_length=3, max_length=120)
    wavelength_nm: float = Field(default=550, ge=400, le=700)
    pupil_mm: float = Field(default=4, ge=2, le=8)
    refractive_index: float = Field(default=1.5, gt=1, lt=2)
    grid: Literal[64, 128, 256] = 128
    feature_width_um: float = Field(ge=10, le=2000)
    spacing_um: float = Field(ge=20, le=3000)
    feature_count: int = Field(default=12, ge=1, le=64)
    relief_limit_um: float = Field(gt=0, le=30)
    minimum_feature_um: float = Field(gt=0, le=2000)
    decentration_mm: float = Field(default=0.1, ge=0, le=0.5)
    rotation_deg: float = Field(default=5, ge=0, le=30)
    pupil_variation_mm: float = Field(default=0.2, ge=0, le=0.5)
    height_tolerance_fraction: float = Field(default=0.05, ge=0, le=0.3)
    bounds: dict[str, list[float]]
    process_reference: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def valid(self):
        if set(self.bounds) != PARAMETERS:
            raise ValueError("bounds must define the exact supported design parameters")
        for name, bound in self.bounds.items():
            if len(bound) != 2 or not np.isfinite(bound).all() or bound[0] > bound[1]:
                raise ValueError("invalid parameter bounds")
            if name == "fiber_angle_deg" and not (0 <= bound[0] <= bound[1] <= 180):
                raise ValueError("orientation must be 0–180 degrees")
            if name != "fiber_angle_deg" and not (
                0 <= bound[0] <= bound[1] <= self.relief_limit_um
            ):
                raise ValueError("parameter exceeds process relief limits")
        if (
            self.feature_width_um < self.minimum_feature_um
            or self.spacing_um < self.feature_width_um
        ):
            raise ValueError("feature width or spacing violates the process")
        sample_um = self.pupil_mm * 1000 / (self.grid / 2)
        if self.feature_width_um < 2 * sample_um:
            raise ValueError(
                "grid undersamples the minimum feature; supply a higher-resolution simulator"
            )
        return self


def centers(envelope, seed):
    rng = np.random.default_rng(seed)
    radius = envelope["pupil_mm"] / 2
    separation = envelope["spacing_um"] / 1000
    points = []
    for _ in range(5000):
        p = rng.uniform(-radius, radius, 2)
        if np.linalg.norm(p) > radius * 0.8:
            continue
        if all(np.linalg.norm(p - q) >= separation for q in points):
            points.append(p)
        if len(points) == envelope["feature_count"]:
            return np.array(points)
    raise ResearchError(
        "INFEASIBLE_DESIGN", "Requested feature count/spacing cannot fit in the pupil."
    )


def simulate(parameters, envelope, seed=1, perturb=None, return_psf=False):
    env = Envelope.model_validate(
        {k: envelope[k] for k in Envelope.model_fields}
    ).model_dump()
    if set(parameters) != PARAMETERS:
        raise ResearchError("INVALID_DESIGN", "Unexpected optical parameters.")
    for key, value in parameters.items():
        if (
            not np.isfinite(value)
            or not env["bounds"][key][0] <= value <= env["bounds"][key][1]
        ):
            raise ResearchError(
                "INFEASIBLE_DESIGN", "Parameters exceed their frozen envelope."
            )
    perturb = perturb or {}
    n = env["grid"]
    radius = env["pupil_mm"] / 2
    dx = env["pupil_mm"] / (n / 2)
    axis = (np.arange(n) - n // 2) * dx
    x, y = np.meshgrid(axis, axis)
    actual_radius = radius + perturb.get("pupil_delta", 0) / 2
    pupil = (x - perturb.get("decenter", 0)) ** 2 + y * y <= actual_radius**2
    rho2 = (x * x + y * y) / radius**2
    sa = parameters["sa_um"] * np.sqrt(5) * (6 * rho2**2 - 6 * rho2 + 1)
    noise = np.zeros_like(x)
    width = env["feature_width_um"] / 1000
    for cx, cy in centers(env, seed):
        noise += np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * (width / 2.355) ** 2))
    theta = np.deg2rad(parameters["fiber_angle_deg"] + perturb.get("rotation", 0))
    perpendicular = x * np.cos(theta) + y * np.sin(theta)
    fiber = np.exp(-(perpendicular**2) / (2 * (width / 2.355) ** 2))
    relief = (
        noise * parameters["noise_height_um"] + fiber * parameters["fiber_height_um"]
    ) * (1 + perturb.get("height_error", 0))
    if relief[pupil].max() > env["relief_limit_um"]:
        raise ResearchError(
            "INFEASIBLE_DESIGN", "Combined relief exceeds the manufacturing envelope."
        )
    opd = sa + (env["refractive_index"] - 1) * relief
    phase = opd * 2 * np.pi / (env["wavelength_nm"] / 1000)
    amplitude = pupil * np.exp(1j * phase)
    psf = np.abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(amplitude)))) ** 2
    psf /= psf.sum()
    ideal = (
        np.abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(pupil.astype(float))))) ** 2
    )
    ideal /= ideal.sum()
    otf = np.abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(psf))))
    otf /= otf[n // 2, n // 2]
    angular_step = env["wavelength_nm"] * 1e-6 / (n * dx)
    xx, yy = np.meshgrid(np.arange(n) - n // 2, np.arange(n) - n // 2)
    outside = np.sqrt(xx * xx + yy * yy) * angular_step > 3 * env[
        "wavelength_nm"
    ] * 1e-6 / (2 * actual_radius)

    def mtf(fraction):
        freq = fraction * (2 * actual_radius / dx)
        angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        return float(
            np.mean(
                [
                    otf[
                        int(round(n / 2 + freq * np.sin(a))) % n,
                        int(round(n / 2 + freq * np.cos(a))) % n,
                    ]
                    for a in angles
                ]
            )
        )

    result = {
        "strehl": float(psf.max() / ideal.max()),
        "mtf_20": mtf(0.2),
        "mtf_50": mtf(0.5),
        "glare_fraction": float(psf[outside].sum()),
        "wavefront_rms_um": float(opd[pupil].std()),
        "relief_max_um": float(relief[pupil].max()),
        "psf_energy": float(psf.sum()),
    }
    return (result, psf, otf) if return_psf else result


def dominates(a, b):
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def optimize(envelope, seed, budget):
    env = Envelope.model_validate(
        {k: envelope[k] for k in Envelope.model_fields}
    ).model_dump()
    rng = np.random.default_rng(seed)
    keys = sorted(PARAMETERS)
    population, rejected = [], 0
    for i in range(budget):
        # Seeded evolutionary mutation around the non-dominated archive, with exploration.
        if population and i % 3:
            base = population[int(rng.integers(len(population)))]["parameters"]
            params = {
                k: float(
                    np.clip(
                        base[k]
                        + rng.normal(0, 0.18)
                        * (env["bounds"][k][1] - env["bounds"][k][0]),
                        *env["bounds"][k],
                    )
                )
                for k in keys
            }
        else:
            params = {k: float(rng.uniform(*env["bounds"][k])) for k in keys}
        try:
            nominal = simulate(params, env, seed)
            variants = [
                simulate(params, env, seed, p)
                for p in (
                    {"decenter": env["decentration_mm"]},
                    {"decenter": -env["decentration_mm"]},
                    {"rotation": env["rotation_deg"]},
                    {"pupil_delta": env["pupil_variation_mm"]},
                    {"height_error": env["height_tolerance_fraction"]},
                )
            ]
        except ResearchError:
            rejected += 1
            continue
        quality = (nominal["mtf_20"] + nominal["mtf_50"]) / 2
        worst = min((m["mtf_20"] + m["mtf_50"]) / 2 for m in variants)
        costs = [
            1 - quality,
            nominal["glare_fraction"],
            max(0, quality - worst),
            nominal["relief_max_um"],
        ]
        candidate = {
            "parameters": params,
            "metrics": nominal,
            "worst_quality": worst,
            "costs": costs,
        }
        if not any(dominates(p["costs"], costs) for p in population):
            population = [p for p in population if not dominates(costs, p["costs"])] + [
                candidate
            ]
    if not population:
        raise ResearchError(
            "INFEASIBLE_DESIGN", "No candidate satisfies the manufacturing constraints."
        )
    return {
        "simulator_version": SIMULATOR_VERSION,
        "seed": seed,
        "evaluated": budget,
        "rejected": rejected,
        "pareto": population,
        "configuration_hash": digest(env),
        "clinical_use_allowed": False,
    }


class CalibrationPoint(Contract):
    parameters: dict[str, float]
    seed: int = Field(default=1, ge=0)
    measurement_reference: str = Field(min_length=3, max_length=200)
    split: Literal["calibration", "verification"]
    measured_mtf_20: float = Field(ge=0, le=1)
    measured_mtf_50: float = Field(ge=0, le=1)
    qc_passed: bool


class CalibrationRequest(Contract):
    envelope_id: str
    # Acceptance tolerances are prespecified, never inferred from verification outcomes.
    max_absolute_mtf_error: float = Field(gt=0, le=0.2)
    points: list[CalibrationPoint] = Field(min_length=5, max_length=100)
    evidence_kind: Literal["measured_lens", "synthetic_fixture"]
    measured_at: date


def calibrate(svc, inp, actor):
    envelope = svc.get("optical_envelope", inp.envelope_id)
    references = [p.measurement_reference for p in inp.points]
    if len(set(references)) != len(references):
        raise ResearchError(
            "DUPLICATE_MEASUREMENT",
            "Calibration and verification references must be disjoint.",
        )
    if (
        sum(p.split == "verification" for p in inp.points) < 2
        or sum(p.split == "calibration" for p in inp.points) < 3
    ):
        raise ResearchError(
            "INVALID_SPLITS",
            "Require three calibration and two independent verification measurements.",
        )
    residuals = []
    for point in inp.points:
        prediction = simulate(point.parameters, envelope, point.seed)
        residuals.append(
            {
                "split": point.split,
                "reference": point.measurement_reference,
                "absolute_error": max(
                    abs(prediction["mtf_20"] - point.measured_mtf_20),
                    abs(prediction["mtf_50"] - point.measured_mtf_50),
                ),
                "qc_passed": point.qc_passed,
            }
        )
    passed = all(
        p["qc_passed"] and p["absolute_error"] <= inp.max_absolute_mtf_error
        for p in residuals
    )
    return svc.save(
        "optical_calibration",
        "CAL",
        {
            **inp.model_dump(mode="json"),
            "residuals": residuals,
            "passed": passed,
            "eligible_for_measured_review": passed
            and inp.evidence_kind == "measured_lens",
            "simulator_version": SIMULATOR_VERSION,
            "implementation_sha256": simulator_hash(),
            "envelope_hash": digest(envelope),
        },
        actor,
    )
