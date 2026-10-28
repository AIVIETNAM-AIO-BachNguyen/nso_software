"""Authenticated readiness and operational counters, without clinical payloads."""

import os
import sys
from research_api import Principal, permit, router, service
from nso.manufacturing.store import InMemoryDesignStore


@router.get("/ready")
def readiness(user: Principal):
    permit(user, "read")
    store = service().store
    checks = {
        "database": True,
        "durable_store": not isinstance(store, InMemoryDesignStore),
        "python_312": sys.version_info[:2] == (3, 12),
        "clinical_use_allowed": False,
    }
    try:
        store.list_records("v3_training_job")
    except Exception:
        checks["database"] = False
    return {
        "status": "ready_for_research"
        if checks["database"] and checks["durable_store"] and checks["python_312"]
        else "development_only",
        "python": sys.version.split()[0],
        "checks": checks,
        "deployment_environment": os.getenv("NSO_ENV", "development"),
    }


@router.get("/operations")
def operations(user: Principal):
    permit(user, "deploy")
    store = service().store
    training = store.list_records("v3_training_job")
    optimizer = store.list_records("v3_optimization")
    return {
        "training_jobs": len(training),
        "optimizer_jobs": len(optimizer),
        "training_queued": sum(
            not store.related("v3_training_result", r["record_id"]) for r in training
        ),
        "optimizer_queued": sum(
            service().optimizer_status(r["record_id"])["status"] == "queued"
            for r in optimizer
        ),
        "access_denials": sum(
            e.get("event_type") == "V3_API_ACCESS" and e.get("status_code", 0) >= 400
            for e in store.audits()
        ),
    }
