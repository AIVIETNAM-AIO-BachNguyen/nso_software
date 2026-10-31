"""Opt-in synthetic UI records. Never training data or clinical evidence."""

import json
import os
from pathlib import Path

from .engineering import ClinicalDigitalThread
from .research import ResearchService
from .research_contracts import ObservationBatch, PatientScope

SITE = "SYNTHETIC-DEMO"
ACTOR = "synthetic-demo-seeder"


def demo_dataset():
    return json.loads((Path(__file__).parent / "data/demo_patients.json").read_text())


def seed_demo_patients(store):
    """Add missing demo records atomically; refuse collisions, never overwrite."""
    dataset = demo_dataset()
    svc = ResearchService(store)
    thread = ClinicalDigitalThread(store)
    added = 0
    with store.transaction():
        for patient in dataset["patients"]:
            pid, cid = patient["patient_id"], patient["case_id"]
            for domain, key in (("patient", pid), ("case", cid)):
                try:
                    record = store.get_record(domain, key)
                except KeyError:
                    continue
                if record.get("site_id") != SITE or record.get("patient_id") != pid:
                    raise ValueError(f"Demo identity collision: {key}")
            try:
                store.get_record("case", cid)
            except KeyError:
                thread.create_case(patient_id=pid, case_id=cid, site_id=SITE,
                                   indication_code="SYNTHETIC_NOT_CLINICAL_EVIDENCE",
                                   clinician_id="DEMO", actor=ACTOR)
            thread.ensure_eyes(pid, actor=ACTOR)
            for eye, rows in patient["eyes"].items():
                batch = ObservationBatch(patient_id=pid, case_id=cid, eye=eye,
                                         observations=rows)
                existing = {r["visit_at"]: r for r in svc.observations(
                    PatientScope(patient_id=pid, case_id=cid, eye=eye))}
                missing = []
                for row in batch.model_dump(mode="json")["observations"]:
                    previous = existing.get(row["visit_at"])
                    if previous is None:
                        missing.append(row)
                    elif any(previous.get(k) != v for k, v in row.items()):
                        raise ValueError(f"Demo observation collision: {pid}/{eye}/{row['visit_at']}")
                if missing:
                    svc.ingest(ObservationBatch(patient_id=pid, case_id=cid,
                                                eye=eye, observations=missing), ACTOR)
                    added += len(missing)
    return {"synthetic_only": True, "patients": 10, "observations_added": added,
            "patient_ids": [p["patient_id"] for p in dataset["patients"]]}


def seed_configured_demo(store):
    if os.getenv("NSO_DEMO_PATIENTS_ENABLED", "false").lower() == "true":
        return seed_demo_patients(store)
    return None
