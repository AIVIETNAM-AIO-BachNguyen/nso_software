# Validation — V3 manufacturing and V3.1 shadow

28 October 2026. Python 3.12.16, Node 26.5.0, Next.js 15.5.28. PostgreSQL 16 uses an isolated test schema per fixture; SQLite and memory are also exercised. All new populations and local staging records are invented synthetic fixtures.

| Check | Final result | Evidence |
|---|---|---|
| Complete backend regression with PostgreSQL enabled | **585 passed, 1 skipped**, 305.75 s | [Full log](v31-backend-test-results.txt) |
| `nso` statement coverage | **92.98%**, 4214/4532 statements | [Coverage JSON](v31-backend-coverage.json) |
| New manufacturing/adaptive test matrix | 22 passing cases included in the full run; memory, SQLite and PostgreSQL | `test_v3_manufacturing_adaptive.py` |
| React component tests | **11 passed**, zero failures/skips | [Log](v31-frontend-test-results.txt) |
| Production frontend build | **PASS** | [Log](v31-frontend-build-results.txt) |
| npm dependency audit | **0 advisories reported** at execution time | [JSON](v31-frontend-dependency-audit.json) |
| Real HTTP manufacturing + adaptive rehearsal | **32 checks PASS**, including expected denials | [JSON](v31-staging-http-verification.json) |
| Frontend pages and assets | `/` and `/research` return 200; seven emitted assets per page all 200 | [JSON](v31-frontend-http-verification.json) |
| Black-box clinical boundaries | **PASS**, 10 responses, 3 bundles, 3 PDF pages | [JSON](v31-black-box-verification.json) |
| Focused browser interaction | **PASS**: sign-in, role options, trace, monitor, JSON upload, withdrawal error, eye-switch state clearing | [Record](v31-browser-verification.json), [screenshot](v31-browser-monitor.png) |
| Ruff F checks, ignoring E402 for import-path scripts | **PASS** | Command below |
| Whitespace diff | **PASS** | `git diff --check` |

The single skipped V2 test is `test_nso_package.py:673`, whose fixture does not cross the element-height threshold. One Starlette/AnyIO deprecation warning remains. Coverage concerns package `nso`; it is not a claim of branch coverage or complete coverage of every top-level API module.

The full regression initially exposed the old fail-closed clinical-ranking contract. The final implementation preserves `adaptive_ranking_enabled=false` and advertises the new capability separately as `adaptive_shadow_enabled`. The successful final run includes that original regression and the new shadow flag assertion.

The manufacturing suite checks the whole Visit-to-Validation thread, reuse of shared domain IDs, protected reference recipes, failed-lot quarantine and rework, revocation, self-approval, synthetic/measured separation, patient/eye mismatch, wrong QC units, incomplete QC, forged acceptance flags, idempotent replay/conflict and rollback of both QC records and audit on a simulated storage failure.

The adaptive suite checks synthetic known-effect recovery and held-out gates, patient/temporal leakage, missing-eye/patient handling, insufficient overlap, one-model-per-policy offline versioning, independent review, explicit deployment/rollback, unchanged treatment/manufacturing state after ranking, new-patient scope, OOD abstention, duplicate outcomes/logs and withdrawal. It does not establish clinical causal validity. The HTTP report contains held-out synthetic metrics only; their numerical improvements are not clinical benefit percentages.

Browser checks used the available 592-pixel-wide window with no document horizontal overflow. They are focused functional checks, not an exhaustive accessibility/mobile/device matrix. File upload was exercised through the browser chooser. No credential is stored in these reports/screenshots.

## Reproduction

From the repository root, using a test-only PostgreSQL database:

```sh
OMP_NUM_THREADS=1 NSO_TEST_POSTGRES_URL='postgresql:///postgres?host=/private/tmp/nso-v3-pg-socket&port=55432' \
  .venv312/bin/python -m pytest -q -rs src/backend \
  --cov=src/backend/nso --cov-report=term-missing:skip-covered
.venv312/bin/ruff check --isolated --select F --ignore E402 \
  src/backend/nso/research*.py src/backend/research*.py \
  src/backend/test_v3*.py src/backend/scripts/v3*.py
git diff --check
cd src/frontend
npm ci
npm test
npm audit
npm run build
```

See [implementation and local staging instructions](V3_MANUFACTURING_V31_COMPLETION_2026-10-28.md) for the HTTP rehearsal. The final rehearsal intentionally withdraws its model/plan after proving the positive path; subsequent requests with those approvals must be blocked.

Remote CI, container execution and production/cloud deployment were not performed. Real machine/process qualification, prospective study/ethics review and measured clinical validation remain external acceptance steps. The V3.1 learner is a binary-arm prototype; it does not validate continuous design-parameter effects or automatically enable clinical ranking.
