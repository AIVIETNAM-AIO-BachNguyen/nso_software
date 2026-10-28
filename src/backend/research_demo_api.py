"""Bounded demonstrations on invented fixtures; never reads the configured store."""

from functools import lru_cache
import json
from pathlib import Path
from typing import Literal

from research_api import router, fail
from nso.research_contracts import Contract


class StudyDemo(Contract):
    assignment: Literal["randomized", "observational"] = "randomized"


@lru_cache(maxsize=2)
def sample_study(assignment):
    from nso.manufacturing.store import InMemoryDesignStore
    from nso.research_advanced import AdvancedResearchService
    from nso.research_fixtures import study
    from nso.research_causal import CausalRequest, analyze

    svc = AdvancedResearchService(InMemoryDesignStore())
    frozen = study(svc, assignment, n=80 if assignment == "observational" else 40)
    request = CausalRequest(
        cohort_id=frozen["cohort_id"],
        method="randomized_ancova"
        if assignment == "randomized"
        else "observational_aipw",
        bootstrap_reps=100,
    )
    return {
        "synthetic": True,
        "persisted": False,
        "clinical_use_allowed": False,
        "descriptive": svc.estimate(frozen["cohort_id"], "synthetic-demo"),
        "adjusted": analyze(svc, request, "synthetic-demo"),
    }


@router.post("/demo/study")
def study_demo(inp: StudyDemo):
    return sample_study(inp.assignment)


class OpticalDemo(Contract):
    seed: Literal[1, 17, 42] = 17


@lru_cache(maxsize=3)
def sample_optics(seed):
    from nso.research_fixtures import optical_envelope
    from nso.research_optics import optimize, PUBLIC_METRICS

    result = optimize(optical_envelope(), seed, 12)
    return {
        "synthetic": True,
        "persisted": False,
        "clinical_use_allowed": False,
        "calibration_status": "uncalibrated_reference",
        "simulator_version": result["simulator_version"],
        "evaluated": result["evaluated"],
        "rejected": result["rejected"],
        "candidates": [
            {
                "design_id": f"SYN-CANDIDATE-{i + 1}",
                "metrics": {
                    k: v for k, v in c["metrics"].items() if k in PUBLIC_METRICS
                },
                "worst_quality": c["worst_quality"],
            }
            for i, c in enumerate(result["pareto"])
        ],
    }


@router.post("/demo/optics")
def optical_demo(inp: OpticalDemo):
    return sample_optics(inp.seed)


@router.get("/demo/training")
def training_demo():
    path = Path(__file__).with_name("nso") / "data" / "research_demo_training.json"
    if not path.exists():
        fail(
            "DEMO_NOT_PRECOMPUTED",
            "Run scripts/v3_training_demo.py to build the synthetic example.",
            503,
        )
    return json.loads(path.read_text())
