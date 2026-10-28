"""Three-arm real-HTTP rehearsal on explicit synthetic-only loopback staging."""

import argparse, json, uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx


def run(folder, base):
    if urlparse(base).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Loopback only")
    access = json.loads((folder / "access-codes.json").read_text())
    context = json.loads((folder / "extension-context.json").read_text())
    if not access["synthetic_only"]:
        raise ValueError("Synthetic-only credentials required")
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
                    f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:200]}"
                )
            checks.append(
                {"method": method, "path": path, "status": response.status_code}
            )
            return response.json()

        state = request("GET", "/api/v3/health", actor=None)
        assert (
            state["features"]["adaptive_shadow_enabled"]
            and state["features"]["adaptive_ranking_enabled"] is False
        )
        frozen = [
            request("POST", "/api/v3/adaptive/multiarm/cohorts", body, expected=201)
            for body in context["three_arm_cohort_requests"]
        ]
        assert all(c["design_linked_eyes"] == 90 for c in frozen)
        body = {
            "name": "Synthetic three-arm HTTP locked policy",
            "train_cohort_id": frozen[0]["cohort_id"],
            "test_cohort_id": frozen[1]["cohort_id"],
            "external_cohort_id": frozen[2]["cohort_id"],
            "evidence_kind": "synthetic",
            "minimum_patients_per_arm": 20,
            "max_group_calibration_error_mm": 0.2,
            "shrinkage": 10,
            "require_design_analysis": True,
            "bootstrap_reps": 200,
            "permutation_reps": 3,
            "analysis_plan": "Prespecified three-arm DR and independent predictive design-value evaluation.",
            "identification_assumptions": "Invented random allocation with known probabilities; consistency and no interference.",
        }
        policy = request(
            "POST", "/api/v3/adaptive/multiarm/policies", body, expected=201
        )
        model = request(
            "POST",
            "/api/v3/adaptive/train",
            {"policy_id": policy["record_id"]},
            expected=201,
        )
        assert model["validation_passed"] and model["arm_names"] == [
            "SA_ONLY",
            "SA_BN",
            "SA_BN_FIBER",
        ]
        analysis = request(
            "GET", "/api/v3/adaptive/models/" + model["record_id"] + "/design-analysis"
        )
        assert (
            analysis["status"] == "completed"
            and not analysis["causal_design_effects_identified"]
        )
        assert all(
            r["stages"]["design"]["mse_mm2"] < r["stages"]["arm"]["mse_mm2"]
            for r in analysis["report"].values()
        )
        request(
            "GET",
            "/api/v3/adaptive/models/" + model["record_id"] + "/design-analysis",
            actor=None,
            expected=401,
        )
        review_body = {
            "model_id": model["record_id"],
            "decision": "approve",
            "reason": "Independent synthetic three-arm validation review only.",
            "scientific_review_reference": "SYNTHETIC-THREE-ARM-REVIEW",
        }
        request("POST", "/api/v3/adaptive/reviews", review_body, expected=403)
        review = request(
            "POST", "/api/v3/adaptive/reviews", review_body, actor="reviewer"
        )
        request(
            "POST",
            "/api/v3/adaptive/deployments",
            {
                "model_id": model["record_id"],
                "review_id": review["record_id"],
                "reason": "Enable three-arm synthetic shadow ranking only.",
            },
            actor="operator",
        )
        logs = {}
        for kind, key in [
            ("complete", "three_arm_full_request"),
            ("partial", "three_arm_partial_request"),
            ("abstained", "three_arm_abstain_request"),
        ]:
            logs[kind] = request("POST", "/api/v3/adaptive/shadow", context[key])
        assert (
            logs["complete"]["ranking_complete"]
            and len(logs["complete"]["candidates"]) == 3
        )
        assert (
            logs["partial"]["status"] == "partial_shadow_logged"
            and not logs["partial"]["ranking_complete"]
            and len(logs["partial"]["candidates"]) == 2
        )
        assert (
            logs["abstained"]["status"] == "abstained"
            and logs["abstained"]["candidates"] == []
        )
        assert all(
            not log["manufacturing_authorized"]
            and not log["actual_assignment_changed"]
            and not log["clinical_use_allowed"]
            for log in logs.values()
        )
        for log in logs.values():
            persisted = request("GET", "/api/v3/adaptive/shadows/" + log["record_id"])
            assert "features" not in persisted
        missing_arm = next(
            arm
            for arm, s in logs["partial"]["arm_support"].items()
            if not s["supported"]
        )
        request(
            "POST",
            "/api/v3/adaptive/outcomes",
            {
                "shadow_id": logs["partial"]["record_id"],
                "observed_arm": missing_arm,
                "adherence": 0.95,
                "source_reference": "SYNTHETIC-UNSUPPORTED-ARM",
                "observation": {
                    "visit_at": "2031-01-01",
                    "al_mm": 24.2,
                    "al_status": "measured",
                    "se_status": "missing",
                    "measurement_method": "SYNTHETIC",
                    "source": "SYNTHETIC_NOT_CLINICAL_EVIDENCE",
                    "quality_flag": "ACCEPTED",
                },
            },
            expected=422,
        )
        request("POST", "/api/v3/adaptive/multiarm/policies", body, expected=409)
        monitor = request(
            "GET", "/api/v3/adaptive/models/" + model["record_id"] + "/monitor"
        )
        assert monitor["shadow_logs"] == 3 and not monitor["automatic_promotion"]
        request(
            "POST",
            "/api/v3/adaptive/shadow",
            context["three_arm_full_request"],
            expected=409,
        )
    return {
        "status": "PASS",
        "synthetic_only": True,
        "clinical_use_allowed": False,
        "clinical_ranking_enabled": False,
        "http_checks": checks,
        "model_id": model["record_id"],
        "shadow_ids": {kind: log["record_id"] for kind, log in logs.items()},
        "ranking_examples": {
            kind: {
                k: log[k]
                for k in (
                    "status",
                    "ranking_complete",
                    "comparator",
                    "estimand",
                    "arm_support",
                    "candidates",
                )
            }
            for kind, log in logs.items()
        },
        "held_out_report": model["report"],
        "incremental_design_report": analysis,
        "limitations": [
            "Synthetic software proof, not clinical benefit or causal design-parameter evidence.",
            "Bulk fixture records are invented historical manufacturing/provenance joins; no physical lenses were manufactured.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run(args.folder, args.base), indent=2))
