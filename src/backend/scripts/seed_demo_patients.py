"""Explicitly add ten synthetic demo patients to the configured database."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    if not os.getenv("NSO_DATABASE_URL"):
        raise SystemExit("Set NSO_DATABASE_URL to the intended durable database first.")
    import nso
    from nso.demo_patients import seed_demo_patients

    print(json.dumps(seed_demo_patients(nso.REGISTRY._store_impl), indent=2))
