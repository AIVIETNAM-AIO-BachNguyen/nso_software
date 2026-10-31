"""Persistent demo seeding must be repeatable and isolated from other records."""

import pytest

from nso.demo_patients import SITE, demo_dataset, seed_configured_demo, seed_demo_patients
from nso.manufacturing.store import InMemoryDesignStore, SQLiteDesignStore
from nso.research import ResearchService
from nso.research_contracts import PatientScope


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return (InMemoryDesignStore() if request.param == "memory"
            else SQLiteDesignStore(tmp_path / "demo.db"))


def test_seed_ten_patients_both_eyes_and_repeat_without_writes(store):
    store.put_record("patient", "EXISTING", {"patient_id": "EXISTING", "site_id": "OTHER"})
    result = seed_demo_patients(store)
    assert result["observations_added"] == 60
    assert len(result["patient_ids"]) == 10
    assert len(store.list_records("patient")) == 11
    assert len(store.list_records("case")) == 10
    assert len(store.list_records("eye")) == 20
    for p in demo_dataset()["patients"]:
        for eye in ("OD", "OS"):
            rows = ResearchService(store).observations(PatientScope(
                patient_id=p["patient_id"], case_id=p["case_id"], eye=eye))
            assert len(rows) == 3
            assert all(r["source"] == "SYNTHETIC_NOT_CLINICAL_EVIDENCE" for r in rows)
            assert rows[-1]["visit_at"] == "2026-11-01"
    assert seed_demo_patients(store)["observations_added"] == 0
    assert store.get_record("patient", "EXISTING")["site_id"] == "OTHER"
    assert len(store.list_records("v3_observation")) == 60


def test_identity_collision_rolls_back_all_new_demo_records(store):
    store.put_record("patient", "SYN-DEMO-010", {
        "patient_id": "SYN-DEMO-010", "site_id": "OTHER"})
    with pytest.raises(ValueError, match="identity collision"):
        seed_demo_patients(store)
    assert len(store.list_records("patient")) == 1
    assert not store.list_records("case")
    assert not store.list_records("v3_observation")


def test_later_demo_observation_is_preserved(store):
    seed_demo_patients(store)
    svc = ResearchService(store)
    from nso.research_contracts import ObservationBatch
    # A new visit is retained; it is not replaced by a seed replay.
    svc.ingest(ObservationBatch(patient_id="SYN-DEMO-001", case_id="SYN-DEMO-CASE-001",
        eye="OD", observations=[dict(visit_at="2026-12-01", al_mm=23.5,
        al_status="measured", source="later-demo-visit", measurement_method="invented")]), "test")
    seed_demo_patients(store)
    assert len(store.list_records("v3_observation")) == 61


def test_startup_seed_is_opt_in(store, monkeypatch):
    monkeypatch.delenv("NSO_DEMO_PATIENTS_ENABLED", raising=False)
    assert seed_configured_demo(store) is None
    assert not store.list_records("patient")
    monkeypatch.setenv("NSO_DEMO_PATIENTS_ENABLED", "true")
    assert seed_configured_demo(store)["observations_added"] == 60


def test_cloud_case_listing_respects_explicit_demo_scope(store, monkeypatch):
    seed_demo_patients(store)
    import research_api
    monkeypatch.setattr(research_api, "service", lambda: ResearchService(store))
    user = {"roles": ["clinical_admin"], "patient_ids": ["SYN-DEMO-001"]}
    assert [r["patient_id"] for r in research_api.cases(user)["cases"]] == ["SYN-DEMO-001"]
    user["patient_ids"] = [p["patient_id"] for p in demo_dataset()["patients"]]
    assert len(research_api.cases(user)["cases"]) == 10


def test_measurement_collision_preserves_original_and_rolls_back(store):
    from nso.engineering import ClinicalDigitalThread
    from nso.research_contracts import ObservationBatch
    ClinicalDigitalThread(store).create_case(patient_id="SYN-DEMO-010",
        case_id="SYN-DEMO-CASE-010", site_id=SITE, indication_code="SYNTHETIC", clinician_id="DEMO")
    ResearchService(store).ingest(ObservationBatch(patient_id="SYN-DEMO-010",
        case_id="SYN-DEMO-CASE-010", eye="OD", observations=[dict(
        visit_at="2025-11-01", al_mm=27, al_status="measured",
        measurement_method="existing", source="existing")]), "test")
    with pytest.raises(ValueError, match="observation collision"):
        seed_demo_patients(store)
    assert len(store.list_records("patient")) == 1
    assert len(store.list_records("v3_observation")) == 1
    assert store.list_records("v3_observation")[0]["al_mm"] == 27


def test_api_lifespan_seeds_configured_store(store, monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setenv("NSO_DEMO_PATIENTS_ENABLED", "true")
    monkeypatch.setattr(api.v2.REGISTRY, "_store_impl", store)
    with TestClient(api.app):
        assert len(store.list_records("patient")) == 10
        assert len(store.list_records("v3_observation")) == 60
