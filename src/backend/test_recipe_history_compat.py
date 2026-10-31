"""Incomplete historical records must not prevent new clinical recipes."""
import nso
from nso.manufacturing.store import InMemoryDesignStore


def test_recipe_registration_skips_unrelated_legacy_record():
    store = InMemoryDesignStore()
    store.put_record("recipe_version", "LEGACY", {"legacy_version": 1})
    thread = nso.ClinicalDigitalThread(store)
    first = thread.register_recipe(design_id="TEST-COMPAT", design_version="1", parameters={"test": 1})
    second = thread.register_recipe(design_id="TEST-COMPAT", design_version="2", parameters={"test": 2})
    assert first["recipe_version_id"] != second["recipe_version_id"]
    versions = store.list_records("recipe_version")
    assert [r["version"] for r in versions if r.get("recipe_id") == first["recipe_id"]] == [1, 2]
    assert store.get_record("recipe_version", "LEGACY") == {"legacy_version": 1}
