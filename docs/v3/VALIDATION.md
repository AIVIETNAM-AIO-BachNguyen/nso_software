> Historical snapshot from 23 October 2026. Superseded by [the 26 October engineering report](COMPLETION_2026-10-26.md).

# Local software verification

Verified on 23 October 2026. These results establish software behavior on local fixtures, not clinical efficacy, calibrated optical performance or production readiness.

| Check | Result |
|---|---|
| Existing backend baseline before modifications | 473 passed, 1 skipped |
| Final backend suite | **513 passed, 1 skipped** |
| New V3 acceptance coverage | 40 passing tests, included in the total |
| Frontend production build | Passed with `/` and `/research` generated |
| Black-box API/bundle/PDF scan | PASS; 10 API responses, 3 browser bundles, 3 PDF pages |
| Browser-storage scan | No `localStorage`, `sessionStorage` or `indexedDB` calls in app source |
| Browser interaction | Synthetic forecast produced 6/12/24-month results; intervention/optical tabs showed their restrictions |
| SQLite migration/reopen | Existing V2 record preserved; V3 records and request receipts survive reopening |
| Atomicity/concurrency | Observation-batch rollback and concurrent receipt reservations passed |
| Cross-version integration | Synthetic V2 case/design → manufacturing lot/QC plus V3 forecast/outcome joined in one trace |
| OpenAPI | OpenAPI 3.1 exported with bearer authentication and strict request contracts; explicit NPM/optimizer output schemas |
| Git whitespace check | `git diff --check` passed |

Backend command: `.venv/bin/python -m pytest -q -rs src/backend`. Final run reported 513 passing tests in 12.69 seconds. The existing skipped test is `src/backend/test_nso_package.py:673`, reason: “varies only once element height crosses its threshold.” It is not counted as passed.

Frontend command: `npm run build` in `src/frontend`. Next.js could not download the existing Google Fonts stylesheet under the current network restrictions; it completed the production build with fallback typography available. Package versions were not upgraded as part of this integration.

Black-box command: `../../.venv/bin/python verify_black_box.py` in `src/backend`. Machine-readable evidence is saved in `black-box-verification.json`. Its measured latency is local warm-process latency only.

The browser check used the local production frontend at `http://127.0.0.1:3000/research` and a local API at `127.0.0.1:8000`. The result screenshot is `research-preview.png`. All displayed measurements are invented synthetic fixtures. No real medical record was opened or sent through a browser for this check. Patient-backed workflows were tested through isolated FastAPI fixtures, not a live authenticated clinical deployment. A mobile viewport and external assistive-technology audit were not exercised.

`python src/backend/scripts/v3_benchmark.py --synthetic` produces `synthetic-benchmark.json`. The observations are arithmetic fixtures constructed for checking the evaluation code. Their error metrics must not be cited as NSO model performance. The script can also validate a locally supplied approved dataset against the configured store, using `--dataset` and the strict Validation request contract.

Remote CI has been configured but not executed in this task. No live PostgreSQL server, cloud restore drill, calibrated optical simulator, trained population model, external clinical cohort or prospective study was available for verification. No release approval, independent security certification or clinical sign-off is implied.
