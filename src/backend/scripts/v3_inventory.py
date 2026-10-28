"""Read-only architecture inventory; never exports patients, keys, recipes or env values.

Run from src/backend: python scripts/v3_inventory.py > ../../docs/v3/inventory.json
"""

import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import api
import nso
from nso.research import SCHEMA_VERSION
from research_api import health


def inventory():
    source_paths = [
        "api.py",
        "research_api.py",
        "research_workflows_api.py",
        "research_extension_api.py",
        "research_operations_api.py",
        "research_demo_api.py",
        "nso/manufacturing/store.py",
        "schema_v22.sql",
        "migrations/v3_001.sql",
        "migrations/v3_002.sql",
    ]
    source_paths += [
        str(p.relative_to(BACKEND))
        for p in sorted((BACKEND / "nso").glob("research*.py"))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "store": nso.REGISTRY.backend,
        "routes": [
            {"path": r.path, "methods": sorted(r.methods)}
            for r in api.app.routes
            if hasattr(r, "methods")
        ],
        "source_sha256": {
            p: hashlib.sha256((BACKEND / p).read_bytes()).hexdigest()
            for p in source_paths
        },
        "research_state": health(),
        "inspection_scope": "Local source/configuration structure only; no production access or patient export.",
        "entity_mapping": {
            "clinical_observation": "domain_records/v3_observation plus conservative V2 visit/clinical_measurement adapter",
            "treatment_exposure": "domain_records/v3_exposure",
            "prediction_run": "domain_records/v3_prediction",
            "causal_cohort": "domain_records/v3_cohort",
            "optimization_run": "domain_records/v3_optimization + v3_optimization_result",
            "outcome_evaluation": "domain_records/v3_outcome",
            "model_validation": "v3_validation benchmark plus immutable v3_trained_model artifacts and v3_training_result reports",
            "v31_shadow": "v3_adaptive_policy/model/review/deployment/shadow/outcome; controlled binary arm research, no prescribing",
            "v3_manufacturing": "v3_manufacturing_* provenance reuses recipe_version, manufacturing_lot, qc_measurement and product_exposure",
            "release_history": "v3_release_review and v3_npm_deployment append-only records",
            "observation_correction": "v3_observation_correction preserves original observation",
            "job_lease": "v3_job_leases, additive SQL table",
            "patient_case_visit_eye": "Reuse existing V2 domains and identifiers",
            "design_recipe_lot_qc": "Reuse V2 registry/vault and physical-product records; no V3 manufacturing release",
            "idempotency": "v3_operations, additive SQL table",
        },
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
