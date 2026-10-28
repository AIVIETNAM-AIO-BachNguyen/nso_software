"""Reproducible research-baseline evaluation, with no clinical promotion.

python scripts/v3_benchmark.py --synthetic
python scripts/v3_benchmark.py --dataset /approved/local/validation-request.json

Real datasets must follow the Validation request contract and reference cases
in NSO_DATABASE_URL. The synthetic mode uses an isolated in-memory store.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nso.engineering import ClinicalDigitalThread
from nso.manufacturing.store import InMemoryDesignStore
from nso.research import ResearchService
from nso.research_contracts import Validation


def synthetic_dataset():
    def obs(day, al, se):
        return {
            "visit_at": day,
            "al_mm": al,
            "se_d": se,
            "al_status": "measured",
            "se_status": "measured",
            "measurement_method": "synthetic arithmetic fixture",
            "source": "invented_not_clinical_evidence",
        }

    samples = []
    for i, split in enumerate(("train", "validation", "test", "external")):
        for n in range(3):
            baseline = 24 + n * 0.1
            samples.append(
                {
                    "patient_id": f"SYNTHETIC-{i}-{n}",
                    "case_id": f"SYNTHETIC-CASE-{i}-{n}",
                    "eye": "OD",
                    "split": split,
                    "site_id": "EXTERNAL" if split == "external" else "DEVELOPMENT",
                    "index_date": "2026-01-01",
                    "untreated_history_confirmed": True,
                    "history": [
                        obs("2025-01-01", baseline, -2),
                        obs("2026-01-01", baseline + 0.2, -2.3),
                    ],
                    "observed": obs("2027-01-01", baseline + 0.4, -2.6),
                }
            )
    return {
        "dataset_version": "synthetic-arithmetic-fixture-not-evidence",
        "model_id": "npm-history-linear-v1",
        "split_strategy": "external_site",
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--synthetic", action="store_true")
    group.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    if args.synthetic:
        payload = synthetic_dataset()
        service = ResearchService(InMemoryDesignStore())
        for sample in payload["samples"]:
            ClinicalDigitalThread(service.store).create_case(
                patient_id=sample["patient_id"],
                case_id=sample["case_id"],
                indication_code="SYNTHETIC",
                site_id=sample["site_id"],
                clinician_id="DEMO",
            )
    else:
        from research_api import service as configured_service

        service = configured_service()
        payload = json.loads(args.dataset.read_text())
    report = service.validate(Validation(**payload), "offline-benchmark")
    print(
        json.dumps(
            {
                "synthetic": args.synthetic,
                "clinical_use_allowed": False,
                "report": report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
