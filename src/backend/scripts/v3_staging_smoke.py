"""Exercise real HTTP staging with synthetic-only ephemeral access codes.

python scripts/v3_staging_smoke.py /private/temp/staging-folder
No credential is printed or saved in the report. Refuses non-loopback URLs.
"""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nso.research_fixtures import optical_envelope


def run(folder, base):
    if urlparse(base).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This smoke check permits loopback staging only")
    access = json.loads((folder / "access-codes.json").read_text())
    if not access["synthetic_only"]:
        raise ValueError("Synthetic-only staging required")
    codes = access["codes"]
    checks = []
    with httpx.Client(base_url=base, timeout=120) as client:

        def request(method, path, body=None, actor="researcher", expected=200):
            headers = (
                {
                    "Authorization": "Bearer " + codes[actor],
                    "Idempotency-Key": str(uuid.uuid4()),
                }
                if actor
                else {}
            )
            response = client.request(method, path, json=body, headers=headers)
            if response.status_code != expected:
                raise AssertionError(
                    f"{method} {path}: expected {expected}, received {response.status_code}; {response.text[:300]}"
                )
            checks.append(
                {"method": method, "path": path, "status": response.status_code}
            )
            return response.json()

        health = request("GET", "/api/health", actor=None)
        assert health["authentication_required"] is True
        ready = request("GET", "/api/v3/ready")
        assert ready["status"] == "ready_for_research" and ready["python"] == "3.12.16"
        cases = request("GET", "/api/v3/cases")["cases"]
        assert cases and all(c["patient_id"].startswith("SYN-") for c in cases)
        request(
            "POST",
            "/api/predict",
            {"patient_id": cases[0]["patient_id"], "age": 10, "od": {}, "os": {}},
            actor=None,
            expected=401,
        )
        for assignment in ("randomized", "observational"):
            report = request(
                "POST", "/api/v3/demo/study", {"assignment": assignment}, actor=None
            )
            assert report["synthetic"] and report["adjusted"]["effect_mm"] is not None
        optics = request("POST", "/api/v3/demo/optics", {"seed": 17}, actor=None)
        assert optics["candidates"] and "noise_height_um" not in json.dumps(optics)
        demo = request("GET", "/api/v3/demo/training", actor=None)
        assert len(demo["models"]) == 3 and demo["synthetic"]
        dataset = json.loads((folder / "synthetic-training.json").read_text())
        policy = request(
            "POST",
            "/api/v3/models/policies",
            {
                "name": "Synthetic HTTP staging verification",
                "minimum_test_patients": 8,
                "minimum_coverage": 0.5,
            },
            actor="reviewer",
            expected=201,
        )
        dataset["validation_policy_id"] = policy["record_id"]
        job = request("POST", "/api/v3/models/train", dataset, expected=202)
        for _ in range(40):
            result = request("GET", "/api/v3/models/training/" + job["run_id"])
            if result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.25)
        assert result["status"] == "completed", result.get("code")
        model_id = result["model_id"]
        approval = request(
            "POST",
            "/api/v3/releases/review",
            {
                "target_kind": "model",
                "target_id": model_id,
                "policy_id": policy["record_id"],
                "decision": "approve",
                "reason": "Independent synthetic-only staging workflow verification",
            },
            actor="reviewer",
        )
        request(
            "POST",
            "/api/v3/releases/deploy",
            {
                "model_id": model_id,
                "review_id": approval["record_id"],
                "reason": "Separate operator testing a synthetic-only research deployment",
            },
            actor="operator",
        )
        sample = next(s for s in dataset["samples"] if s["split"] == "train")
        identity = {k: sample[k] for k in ("patient_id", "case_id", "eye")}
        forecast = request(
            "POST",
            "/api/v3/npm/predict",
            {
                **identity,
                "index_date": sample["index_date"],
                "index_age": sample["index_age"],
                "model_id": model_id,
                "untreated_history_confirmed": True,
            },
        )
        assert (
            forecast["forecasts"][0]["al_interval"]
            and not forecast["clinical_use_allowed"]
        )
        request(
            "POST",
            "/api/v3/outcomes/evaluate",
            {
                "prediction_id": forecast["prediction_id"],
                "observation": sample["observed"],
            },
        )
        env = request(
            "POST", "/api/v3/optimizer/envelopes", optical_envelope(), expected=201
        )
        optical_job = request(
            "POST",
            "/api/v3/optimizer/run",
            {**identity, "envelope_id": env["envelope_id"], "candidate_budget": 8},
            expected=202,
        )
        for _ in range(30):
            optical_result = request(
                "GET", "/api/v3/optimizer/" + optical_job["run_id"]
            )
            if optical_result["status"] != "queued":
                break
            time.sleep(0.25)
        assert (
            optical_result["status"] == "completed"
            and optical_result["calibration_status"] == "uncalibrated_reference"
        )
        request(
            "POST",
            "/api/v3/designs/approve",
            {
                "run_id": optical_job["run_id"],
                "design_id": optical_result["pareto_candidates"][0]["design_id"],
                "reason": "Synthetic candidate must not pass measured calibration gate",
            },
            actor="reviewer",
            expected=409,
        )
        request("GET", "/api/v3/operations", actor="operator")
        # Serving restrictions survive a withdrawn approval.
        request(
            "POST",
            "/api/v3/releases/review",
            {
                "target_kind": "model",
                "target_id": model_id,
                "policy_id": policy["record_id"],
                "decision": "reject",
                "reason": "Withdraw the synthetic staging model after completing tests",
            },
            actor="reviewer",
        )
        request(
            "POST",
            "/api/v3/npm/predict",
            {
                **identity,
                "index_date": sample["index_date"],
                "index_age": sample["index_age"],
                "model_id": model_id,
                "untreated_history_confirmed": True,
            },
            expected=409,
        )
    return {
        "synthetic_only": True,
        "python": ready["python"],
        "status": "PASS",
        "http_checks": checks,
        "browser_checked": False,
        "clinical_use_allowed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run(args.folder, args.base), indent=2))
