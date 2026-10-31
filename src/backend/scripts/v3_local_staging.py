"""Run production-mode local staging against an explicit, synthetic-only SQL DB.

Writes one-time study access codes and invented import fixtures to a private
temporary directory. Never accepts a database containing non-synthetic patients.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def configure(url, extensions=False, multiarm=False):
    os.environ["NSO_DATABASE_URL"] = url
    os.environ["NSO_ENV"] = "production"
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:3000,http://localhost:3000"
    os.environ["DESIGN_ID_SECRET"] = secrets.token_urlsafe(48)
    for name in ("NPM", "IPM_RESEARCH", "OPTIMIZER"):
        os.environ["NSO_V3_" + name + "_ENABLED"] = "true"
    import nso
    from nso.research_advanced import AdvancedResearchService
    from nso.research_contracts import ObservationBatch
    from nso.research_fixtures import learning_request, seed_learning_cases

    svc = AdvancedResearchService(nso.REGISTRY._store_impl)
    patients = svc.store.list_records("patient")
    if any(not p["patient_id"].startswith("SYN-") for p in patients):
        raise ValueError(
            "Local staging refuses databases containing non-synthetic patients"
        )
    dataset = learning_request()
    if not patients:
        seed_learning_cases(svc, dataset)
        seen = set()
        for sample in dataset.samples:
            key = (sample.patient_id, sample.eye)
            if key in seen:
                continue
            seen.add(key)
            svc.ingest(
                ObservationBatch(
                    patient_id=sample.patient_id,
                    case_id=sample.case_id,
                    eye=sample.eye,
                    observations=sample.history,
                ),
                "synthetic-staging",
            )
    extension_context = None
    if extensions or multiarm:
        os.environ["NSO_V3_MANUFACTURING_ENABLED"] = "true"
        os.environ["NSO_V3_ADAPTIVE_RANKING_ENABLED"] = "true"
        from nso.research_extension_fixtures import cohort_fixture, scope_case

        saved = svc.store.list_records(
            "v3_extension_context_multiarm" if multiarm else "v3_extension_context"
        )
        if saved:
            extension_context = saved[0]["payload"]
        else:
            with svc.store.transaction():
                if multiarm:
                    from nso.research_multiarm_fixtures import staging_context

                    extension_context = staging_context(svc)
                else:
                    cohorts = cohort_fixture(svc)
                    shadow_scope = scope_case(
                        svc, "SYN-SHADOW-LIVE", "SYN-SHADOW-LIVE-CASE"
                    )
                    extension_context = {
                        "cohort_ids": cohorts,
                        "scope": shadow_scope,
                        "protocol_id": svc.get("cohort", cohorts[0])["protocol_id"],
                    }
                svc.save(
                    "extension_context_multiarm" if multiarm else "extension_context",
                    "EXT",
                    {"payload": extension_context},
                    "synthetic-staging",
                )
    ids = [p["patient_id"] for p in svc.store.list_records("patient")]
    from clinical_admin_auth import password_hash

    os.environ.setdefault("NSO_CLINICAL_ADMIN_USERNAME", "nso")
    os.environ.setdefault("NSO_CLINICAL_ADMIN_PASSWORD_HASH", password_hash("2026nso"))
    os.environ["NSO_CLINICAL_ADMIN_PATIENT_IDS"] = json.dumps(ids)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
    codes = {}
    principals = []
    for actor, roles in (
        (
            "researcher",
            [
                "researcher",
                "validator",
                "optical_engineer",
                "manufacturing_engineer",
                "adaptive_researcher",
            ],
        ),
        ("reviewer", ["validator", "design_approver"]),
        ("operator", ["deployer", "design_approver", "manufacturing_engineer"]),
    ):
        code = secrets.token_urlsafe(32)
        codes[actor] = code
        principals.append(
            {
                "actor": actor,
                "token_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "roles": roles,
                "patient_ids": ids,
                "expires_at": expiry,
            }
        )
    os.environ["NSO_V3_PRINCIPALS"] = json.dumps(principals)
    folder = Path(tempfile.mkdtemp(prefix="nso-local-staging-"))
    folder.chmod(0o700)
    for filename, payload in (
        (
            "access-codes.json",
            {"synthetic_only": True, "expires_at": expiry, "codes": codes},
        ),
        ("synthetic-training.json", dataset.model_dump(mode="json")),
    ):
        path = folder / filename
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as f:
            json.dump(payload, f, indent=2)
    if extension_context:
        context_path = folder / "extension-context.json"
        descriptor = os.open(context_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as f:
            json.dump(extension_context, f, indent=2)
    print("Synthetic-only staging: http://127.0.0.1:8000", flush=True)
    print("Private access/import files: " + str(folder), flush=True)
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--extensions",
        action="store_true",
        help="Seed invented manufacturing/V3.1 rehearsal cohorts",
    )
    parser.add_argument(
        "--multiarm",
        action="store_true",
        help="Seed three-arm and pre-index design-value software fixtures",
    )
    args = parser.parse_args()
    configure(args.database_url, args.extensions, args.multiarm)
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000)
