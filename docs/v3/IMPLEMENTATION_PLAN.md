> Cập nhật 28/10/2026: phần manufacturing và V3.1 được mở rộng sau báo cáo này; xem [báo cáo mới](V3_MANUFACTURING_V31_COMPLETION_2026-10-28.md).

# Engineering completion plan

Started 26 October 2026. Runtime: isolated Python 3.12.16 environment.

The requested scope is items 1–7 from the implementation discussion. Clinical certification and V3.1 are outside this engineering completion. Tests will use explicitly synthetic fixtures and an isolated PostgreSQL instance; they cannot substitute for calibration on measured lenses or validation on approved clinical data.

1. Study data: immutable correction history, protocol and eligibility metadata, adverse events, missingness/censoring, transactional imports and overlapping-exposure protection.
2. NPM: reproducible population training, age-adjusted mixed effects, boosting and Transformer prototype; patient-level partitions; held-out uncertainty and subgroup/OOD reporting; artifact persistence and controlled serving.
3. IPM: frozen analysis protocol, covariate-adjusted arm effects, balance/overlap/weight diagnostics, patient-level uncertainty and sensitivity reporting; no unvalidated ITE.
4. Optics: executable scalar-diffraction reference simulator, protected design envelopes, constrained multiobjective search, Pareto and perturbation evaluation; separate calibration gates and no inferred clinical benefit.
5. Governance: immutable review/approval/deployment/rollback history with independent reviewer roles and evidence requirements.
6. UI: usable synthetic studies and optimizer demonstrations, data-management forms, clear status/error states, session handling and report views.
7. Operations: protect legacy production APIs, exact CORS, PostgreSQL integration, atomic requests/audit, backup restore drill, monitoring/readiness, CI and staging packaging.

Evidence, remaining external dependencies and final test commands will be recorded in a completion report after implementation.
