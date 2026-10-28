"""Generate a precomputed software demo. Never use its metrics as clinical evidence."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nso.research_fixtures import learning_request
from nso.research_learning import fit

if __name__ == "__main__":
    reports = []
    for name in ("mixed_effects", "gradient_boosting", "temporal_transformer"):
        fitted = fit(learning_request(name), "synthetic-software-demonstration")
        reports.append(
            {
                "algorithm": name,
                "report": fitted["report"],
                "baseline_reports": fitted["baseline_reports"],
                "calibration_patients": fitted["calibration_patients"],
                "artifact_hash": fitted["artifact_hash"],
            }
        )
    path = (
        Path(__file__).resolve().parents[1]
        / "nso"
        / "data"
        / "research_demo_training.json"
    )
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "precomputed": True,
                "clinical_use_allowed": False,
                "models": reports,
            },
            indent=2,
        )
    )
    print("Synthetic training demonstration generated; no clinical performance claim.")
