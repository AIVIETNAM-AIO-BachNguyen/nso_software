# Three-arm validation — 29 October 2026

Runtime: Python 3.12.16 in `.venv312`, Node 26.5.0, Next.js 15.5.28. PostgreSQL 16 uses isolated fixture schemas. No real patient or measured-lens data was used.

## Evidence

- Full backend regression with PostgreSQL: **593 passed, 1 skipped**, 383.73 seconds; [log](multiarm-backend-test-results.txt), [coverage JSON](multiarm-backend-coverage.json).
- Package statement coverage: **92.57%**, 4682/5058 statements.
- Focused final three-arm tests: **8 passed**, covering memory/SQLite/PostgreSQL, no skips. [Log](multiarm-targeted-tests.txt).
- Frontend component tests: **14 passed**, zero failures/skips. [Log](multiarm-frontend-test-results.txt).
- Production build: **PASS**. [Log](multiarm-frontend-build-results.txt).
- npm audit: **0 reported advisories** at execution time. [JSON](multiarm-dependency-audit.json).
- Final real-loopback HTTP three-arm rehearsal: **21 checks PASS**, including expected 401/403/409/422 denials. [JSON](multiarm-staging-http-verification.json).
- Final read projection and frontend: **PASS**, synthetic label preserved; `/` and `/research` return 200, each with seven assets returning 200. [JSON](multiarm-final-http-checks.json).
- Black-box clinical boundary regression: **PASS**, 10 responses, 3 bundles, 3 PDF pages; no forbidden design/storage patterns found within the scanner's scope. [JSON](multiarm-black-box-verification.json).
- Browser: complete/partial/abstained states, support counts/ESS and nested predictive model tables inspected. [Scope record](multiarm-browser-verification.json), [ranking screenshot](multiarm-browser-ranking.png), [design-value screenshot](multiarm-browser-design-value.png). The final backend-only pre-index QC refinement was tested via pytest/HTTP; a final browser recheck was blocked because browser use was disabled in Work settings. These are focused UI checks, not an exhaustive device/accessibility matrix.
- Ruff `F` checks (ignoring E402 for import-path scripts) and `git diff --check`: **PASS**.

The tests exercise synthetic positive and null parameter signals, constant-within-arm unidentifiable parameters, shared physical lot/QC leakage, patient overlap, post-index evidence, forbidden outcome/adherence/QC features, allocation probability bounds, insufficient arm propensity/ESS, partial arm ranking, unsupported comparator abstention, no manufacturing/treatment mutation and JSON-reloaded observational multinomial propensity. The positive fixture must recover held-out predictive value; the null fixture must not claim supported value.

The legacy full-regression skip at `test_nso_package.py:673` concerns an element-height threshold not crossed by that fixture. A Starlette/AnyIO deprecation warning remains. Package statement coverage does not measure every API module or prove scientific correctness.

## Reproduce

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

Use only a test PostgreSQL database. See [implementation/rehearsal instructions](MULTIARM_COMPLETION_2026-10-29.md) for a fresh synthetic staging DB and the HTTP smoke script. No credentials are saved in the evidence.

Scientific limits: DR pseudo-outcomes are not individual counterfactual ground truth. Fixed-nuisance intervals, ablation/permutation and positive synthetic metrics do not establish causal design effects or clinical benefit. Three-arm output remains shadow-only. Remote CI, Docker/cloud deployment and real-process/clinical acceptance were not executed.
