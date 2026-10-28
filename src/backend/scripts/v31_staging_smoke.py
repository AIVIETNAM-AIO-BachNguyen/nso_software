"""Real-loopback HTTP rehearsal. Only invented fixtures; never prints credentials."""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlparse
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nso.research_fixtures import optical_envelope, observation


def run(folder, base):
    if urlparse(base).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Loopback only")
    access = json.loads((folder / "access-codes.json").read_text())
    if not access["synthetic_only"]:
        raise ValueError("Synthetic-only staging required")
    context = json.loads((folder / "extension-context.json").read_text())
    scope = context["scope"]
    checks = []
    with httpx.Client(base_url=base, timeout=180) as client:

        def request(method, path, body=None, actor="researcher", expected=200):
            headers = (
                {
                    "Authorization": "Bearer " + access["codes"][actor],
                    "Idempotency-Key": str(uuid.uuid4()),
                }
                if actor
                else {}
            )
            response = client.request(method, path, json=body, headers=headers)
            if response.status_code != expected:
                raise AssertionError(
                    f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:250]}"
                )
            checks.append(
                {"method": method, "path": path, "status": response.status_code}
            )
            return response.json()

        health = request("GET", "/api/v3/health", actor=None)
        assert (
            health["features"]["adaptive_shadow_enabled"]
            and health["features"]["manufacturing_enabled"]
        )
        request(
            "POST",
            "/api/v3/adaptive/train",
            {"policy_id": "UNKNOWN"},
            actor=None,
            expected=401,
        )
        forecast = request(
            "POST",
            "/api/v3/npm/predict",
            {**scope, "index_date": "2026-01-01", "untreated_history_confirmed": True},
        )
        plans = []
        for arm in ("SA_ONLY", "SA_BN"):
            env = optical_envelope()
            env["bounds"]["fiber_height_um"] = [0, 0]
            if arm == "SA_ONLY":
                env["bounds"]["noise_height_um"] = [0, 0]
            env_id = request("POST", "/api/v3/optimizer/envelopes", env, expected=201)[
                "envelope_id"
            ]
            job = request(
                "POST",
                "/api/v3/optimizer/run",
                {
                    **scope,
                    "envelope_id": env_id,
                    "seed": 9,
                    "candidate_budget": 8,
                    "objective_version": "optical-quality-v1",
                },
                expected=202,
            )
            for _ in range(100):
                result = request("GET", "/api/v3/optimizer/" + job["run_id"])
                if result["status"] != "queued":
                    break
                time.sleep(0.1)
            assert result["status"] == "completed"
            plan = request(
                "POST",
                "/api/v3/manufacturing/plans",
                {
                    **scope,
                    "prediction_id": forecast["prediction_id"],
                    "candidate_id": result["pareto_candidates"][0]["design_id"],
                    "mode": "synthetic_rehearsal",
                    "arm": arm,
                    "process_reference": "SYNTHETIC-NOT-A-QUALIFIED-PROCESS",
                    "material_code": "SYN-MATERIAL",
                    "qc_requirements": [
                        {
                            "name": "surface_error",
                            "unit": "um",
                            "lower": 0,
                            "upper": 0.2,
                        }
                    ],
                },
                expected=201,
            )
            request(
                "POST",
                "/api/v3/manufacturing/reviews",
                {
                    "plan_id": plan["record_id"],
                    "decision": "approve",
                    "reason": "Independent invented reference recipe acceptance.",
                    "process_qualification_reference": "SYNTHETIC-NOT-QUALIFIED",
                },
                actor="reviewer",
            )
            plans.append(plan)
        ids = context["cohort_ids"]
        policy = request(
            "POST",
            "/api/v3/adaptive/policies",
            {
                "name": "Synthetic HTTP shadow policy",
                "train_cohort_id": ids[0],
                "test_cohort_id": ids[1],
                "external_cohort_id": ids[2],
                "evidence_kind": "synthetic",
                "minimum_patients_per_arm": 20,
                "analysis_plan": "Prespecified synthetic DR held-out software check.",
                "identification_assumptions": "Invented randomized assignment; consistency, positivity, no interference.",
            },
            expected=201,
        )
        model = request(
            "POST",
            "/api/v3/adaptive/train",
            {"policy_id": policy["record_id"]},
            expected=201,
        )
        assert model["validation_passed"], model["report"]
        review = request(
            "POST",
            "/api/v3/adaptive/reviews",
            {
                "model_id": model["record_id"],
                "decision": "approve",
                "reason": "Independent review of synthetic held-out software gates.",
                "scientific_review_reference": "SYNTHETIC-SCIENTIFIC-REVIEW",
            },
            actor="reviewer",
        )
        deployment = request(
            "POST",
            "/api/v3/adaptive/deployments",
            {
                "model_id": model["record_id"],
                "review_id": review["record_id"],
                "reason": "Enable the synthetic shadow rehearsal only.",
            },
            actor="operator",
        )
        # A fresh cohort enrollment is created once for the dedicated shadow case.
        try:
            en = request(
                "POST",
                "/api/v3/studies/enrollments",
                {
                    **scope,
                    "protocol_id": context["protocol_id"],
                    "index_date": "2026-01-01",
                    "eligible": True,
                    "assigned_arm": "SA_ONLY",
                    "eligibility_reasons": ["Invented shadow fixture"],
                    "age": 12,
                    "baseline_al": 24,
                    "baseline_se": -2,
                    "prior_al_slope": 0.25,
                    "sex_code": 0,
                    "allocation_reference": "SYN-SHADOW-ALLOCATION",
                },
                expected=201,
            )
            enrollment_id = en["record_id"]
        except AssertionError:
            # Rehearsal reruns must use a fresh dedicated DB/context, not guess IDs.
            raise RuntimeError(
                "Enrollment already exists or failed: use a fresh synthetic staging database."
            ) from None
        log = request(
            "POST",
            "/api/v3/adaptive/shadow",
            {
                **scope,
                "enrollment_id": enrollment_id,
                "plan_ids": [p["record_id"] for p in plans],
            },
        )
        assert (
            log["status"] == "shadow_logged"
            and not log["actual_assignment_changed"]
            and not log["manufacturing_authorized"]
        )
        lot = request(
            "POST",
            "/api/v3/manufacturing/lots",
            {
                "plan_id": plans[0]["record_id"],
                "lot_code": "SYN-HTTP-" + uuid.uuid4().hex[:8],
                "manufacturer_id": "SYN-OEM",
                "facility_id": "SYN-FAC",
            },
            actor="operator",
            expected=201,
        )
        exposure = {
            "lot_id": lot["record_id"],
            "start_at": "2026-01-02",
            "adherence": 0.95,
            "authorization_reference": "SYNTHETIC-REHEARSAL-ONLY",
        }
        request("POST", "/api/v3/manufacturing/exposures", exposure, expected=409)
        qc = request(
            "POST",
            "/api/v3/manufacturing/qc",
            {
                "lot_id": lot["record_id"],
                "measurements": [
                    {"name": "surface_error", "actual": 0.1, "unit": "um"}
                ],
                "evidence_reference": "SYNTHETIC-QC-NOT-A-REAL-MEASUREMENT",
            },
            actor="operator",
        )
        assert qc["passed"]
        request("POST", "/api/v3/manufacturing/exposures", exposure)
        follow = observation("2027-01-01", 24.2, -2.2).model_dump(mode="json")
        validated = request(
            "POST",
            "/api/v3/manufacturing/outcomes",
            {
                "lot_id": lot["record_id"],
                "prediction_id": forecast["prediction_id"],
                "observation": follow,
            },
        )
        assert (
            validated["primary_endpoint_eligible"]
            and not validated["model_approval_granted"]
        )
        request(
            "POST",
            "/api/v3/adaptive/outcomes",
            {
                "shadow_id": log["record_id"],
                "observed_arm": "SA_ONLY",
                "observation": follow,
                "adherence": 0.95,
                "source_reference": "SYNTHETIC-FOLLOWUP",
            },
        )
        monitor = request(
            "GET", "/api/v3/adaptive/models/" + model["record_id"] + "/monitor"
        )
        trace = request(
            "GET", "/api/v3/manufacturing/cases/" + scope["case_id"] + "/trace"
        )
        assert len(trace["manufacturing_threads"]) == 2
        assert "parameters" not in json.dumps(
            trace
        ) and "qc_requirements" not in json.dumps(trace)
        request(
            "POST",
            "/api/v3/adaptive/deployments",
            {
                "model_id": model["record_id"],
                "review_id": review["record_id"],
                "rollback_to_deployment_id": deployment["record_id"],
                "reason": "Rehearse explicit rollback to the prior approved shadow version.",
            },
            actor="operator",
        )
        request(
            "POST",
            "/api/v3/adaptive/reviews",
            {
                "model_id": model["record_id"],
                "decision": "reject",
                "reason": "Withdraw the synthetic shadow model after rehearsal.",
                "scientific_review_reference": "SYNTHETIC-WITHDRAWAL",
            },
            actor="reviewer",
        )
        request(
            "POST",
            "/api/v3/adaptive/shadow",
            {
                **scope,
                "enrollment_id": enrollment_id,
                "plan_ids": [p["record_id"] for p in plans],
            },
            expected=409,
        )
        request(
            "POST",
            "/api/v3/manufacturing/reviews",
            {
                "plan_id": plans[0]["record_id"],
                "decision": "reject",
                "reason": "Withdraw synthetic manufacturing plan after rehearsal.",
                "process_qualification_reference": "SYNTHETIC-REVIEW",
            },
            actor="reviewer",
        )
        request(
            "POST",
            "/api/v3/manufacturing/lots",
            {
                "plan_id": plans[0]["record_id"],
                "lot_code": "MUST-BE-BLOCKED",
                "manufacturer_id": "SYN-OEM",
                "facility_id": "SYN-FAC",
            },
            actor="operator",
            expected=409,
        )
    return {
        "status": "PASS",
        "synthetic_only": True,
        "clinical_use_allowed": False,
        "machine_instructions": False,
        "ranking_mode": "shadow_only",
        "http_checks": checks,
        "manufacturing_chain": [
            "Observation",
            "Prediction",
            "Candidate",
            "Independent approval",
            "Reference recipe",
            "Lot",
            "QC",
            "Exposure",
            "Outcome",
            "Validation",
        ],
        "held_out_report": model["report"],
        "monitor": {k: v for k, v in monitor.items() if k != "model_id"},
        "browser_tested": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run(args.folder, args.base), indent=2))
