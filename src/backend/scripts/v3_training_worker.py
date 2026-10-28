"""Recover queued training jobs after worker exit; live leases prevent duplication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_api import service

if __name__ == "__main__":
    svc = service()
    count = 0
    for job in svc.store.list_records("v3_training_job"):
        if not svc.store.related("v3_training_result", job["record_id"]):
            result = svc.execute_training(job["record_id"])
            count += result["status"] != "running"
    print(f"Training jobs recovered: {count}")
