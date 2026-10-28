"""Recover queued reference optical searches after an API restart.

Run from src/backend with the same NSO_DATABASE_URL: python scripts/v3_optimizer_worker.py
Jobs with no registered envelope are blocked; completed searches remain research-only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_api import service


def run_once():
    svc = service()
    completed = 0
    for job in svc.store.list_records("v3_optimization"):
        if svc.optimizer_status(job["record_id"])["status"] == "queued":
            svc.execute_optimizer(job["record_id"], "optimizer-recovery-worker")
            completed += 1
    return completed


if __name__ == "__main__":
    print(f"Readiness jobs processed: {run_once()}")
