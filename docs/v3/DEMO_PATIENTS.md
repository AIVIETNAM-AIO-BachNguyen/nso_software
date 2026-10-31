# Ten synthetic demonstration patients

The fixture `src/backend/nso/data/demo_patients.json` contains exactly ten invented
patients (`SYN-DEMO-001` through `SYN-DEMO-010`), one case each, both OD and OS,
and visits on 2025-11-01, 2026-05-01 and 2026-11-01: 60 AL/SE observations.
All observations explicitly identify their synthetic origin. "Measured" is a
software provenance status in this fixture, not evidence of physical measurement.
No real names, contact details, credentials or clinical records are included.
The fixture is for UI rehearsal, not model training or scientific validation.

## Load on Render

Pushing code does not itself populate the deployed database. After the new commit
has deployed, set **nso-api → Environment → `NSO_DEMO_PATIENTS_ENABLED=true`** and
redeploy. Startup adds missing demo records to the configured database. Existing
records are preserved; identity or same-date measurement conflicts abort the seed
transaction rather than overwrite records. The flag is off by default. Only one
worker should perform the initial seed. Durable `NSO_DATABASE_URL` storage is
required to keep the records across redeployments.

Alternatively, run once from the backend root using the configured database:

```sh
python scripts/seed_demo_patients.py
```

Set the clinical account's `NSO_CLINICAL_ADMIN_PATIENT_IDS` to:

```json
["SYN-DEMO-001","SYN-DEMO-002","SYN-DEMO-003","SYN-DEMO-004","SYN-DEMO-005","SYN-DEMO-006","SYN-DEMO-007","SYN-DEMO-008","SYN-DEMO-009","SYN-DEMO-010"]
```

This is an explicit access-scope change to perform in the hosting dashboard.
The seeder does not create accounts, change passwords or grant permissions.
After redeployment, sign in again; the patient selector should contain these ten
IDs and Patient History should display three visits per eye. Current fitting
inputs remain manually confirmed; historical SE is not automatically treated as
sphere, and the fixture does not invent CSF, corneal or binocular measurements.

## Local isolated rehearsal

```sh
NSO_DATABASE_URL=sqlite:////private/tmp/nso-demo-patients.db \
  .venv312/bin/python src/backend/scripts/seed_demo_patients.py
```

Running again reports zero added observations. Deleting or correcting demo
records is not part of the seed operation.

## Verification (1 November 2026)

48 targeted tests passed across demo seeding, clinical authentication, historical
recipe compatibility and V2.1/V2.2 acceptance. Demo-specific checks run against
both in-memory and SQLite stores, covering both eyes, repeated seeding, preservation
of unrelated/later records, identity and measurement collisions with rollback,
patient-scoped case listing and FastAPI startup integration. The CLI was also run
twice against an isolated SQLite file: 60 observations added, then 0 on replay.
No cloud database was modified by these checks.
