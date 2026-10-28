> Superseded for the three-arm scope on 29 October: see [three-arm implementation](MULTIARM_COMPLETION_2026-10-29.md). Historical binary limits below describe the preceding version.

# V3 research manufacturing and V3.1 shadow implementation

Updated 28 October 2026. This extends the 26 October engineering work. Local Python is 3.12.16. No real clinical evidence, measured-lens qualification, manufacturing toolpath or clinical authorization was created.

## Delivered manufacturing chain

The research thread now links **Patient → index Visit → frozen Prediction → optical Candidate → independent plan approval → protected reference Recipe version → Lot → computed QC → recorded Exposure → follow-up Visit → Outcome → endpoint-validation record**.

- Existing V2 `visit`, `recipe`, `recipe_version`, `manufacturing_lot`, `qc_measurement` and `product_exposure` domains are reused. New V3 provenance lives in existing `domain_records`; no new SQL tables are needed.
- A matching index Visit ID is reused. If research observations have no legacy Visit, a metadata-only Visit and explicit source link are created. Observation/outcome values stay in their original source records; imputed data is never relabeled as a legacy objective measurement. Ambiguous same-case/date Visit identities are rejected.
- Plans freeze patient/case/eye, the accepted measured AL index, prediction/candidate/envelope hashes, treatment arm, process reference, material and QC tolerances. Arm labels must match the protected optical layers: SA-only cannot contain noise/fiber relief; the noise/fiber arms require the corresponding layers.
- An author cannot approve their own plan. The manufacturing operator differs from the approver. Measured research requires current optical approval, measured calibration and a separately recorded process-qualification reference. References are recorded attestations, not independently verified credentials or scientific sign-off.
- Synthetic cases require `synthetic_rehearsal`; measured cases cannot borrow that bypass. Shared Lot records explicitly say `SIMULATED` for rehearsal or `RESEARCH_RECORDED` for measured research. They never gain clinical permission.
- A Recipe holds the reference parameters, seed, envelope and locked tolerances in protected storage. It is **not a qualified machine instruction/toolpath**. Its product ID stays outside the V2 vendor-export registry, so the generic vendor path cannot export it as a V2 machine job.
- Every required QC metric must be supplied once with the locked unit. Acceptance is computed from limits; a client cannot submit `passed=true`. Any failed QC report quarantines that lot permanently; rework creates a new lot. Withdrawal and current simulator/envelope checks are repeated before use.
- Exposure and follow-up are bound to the same lot, patient, eye and prediction. Future measured outcomes are rejected. Endpoint validation evaluates the observed follow-up; it never approves a model or a prescription.
- `/manufacturing/cases/{case_id}/trace` and the existing case trace expose opaque links and permitted summaries. Recipe parameters, tolerances and protected QC values are withheld.

## Delivered V3.1 research software

This is a **binary-arm, shrunken linear doubly robust prototype** and a governed shadow workflow. It is an independent implementation, not MPPM or EconML. It does not claim a validated individual causal effect.

1. Freeze three cohorts and a versioned policy before training. Train/test/external patient IDs must be disjoint, including patients subsequently excluded for missing endpoints. External sites are independent; temporal validation requires every development endpoint to precede the later index. Cohort hashes and equivalent locked protocol definitions are checked.
2. Use prespecified pre-index age, AL, SE, prior AL slope and sex. OD/OS are averaged inside each patient. A missing included eye removes the entire patient rather than silently using the other eye. Randomized assignment is retained after switching; the analysis is still restricted to complete eligible endpoints and reports missingness. Allocation references do not independently verify randomization.
3. Generate training DR pseudo-outcomes with three patient-stratified folds; each fold fits its own scaler and outcome/propensity nuisance models. Randomized studies use their locked assignment probability. The final Ridge effect model shrinks heterogeneity. Artifacts contain JSON coefficients, training support summaries, hashes, held-out reports and explicit limitations.
4. Evaluate untouched test/external or later cohorts against a constant-arm-effect baseline. Reports include pseudo-outcome MSE, relative improvement, calibration groups and age/sex summaries, propensity extremes/ESS, and held-out DR policy-score differences. Acceptance requires the locked improvement/calibration thresholds and an approximate policy-score uncertainty bound. These are research diagnostics; pseudo-outcome errors are **not ground-truth CATE errors**, and the fixed-nuisance normal approximation is not an individual effect confidence interval.
5. Author, reviewer and deployment operator are separated. Measured studies require ethics and assignment-review references. Withdrawn/stale approvals stop serving immediately. Rollback only targets a prior deployment with a current matching approval. Retraining is offline, one model per locked policy, with optional prior-model lineage; no automatic promotion occurs.
6. Shadow requests require a **new patient**, matching enrollment/protocol, accepted measured baseline and feasible independently approved plans for both validated arms. Range checks and local support in both training arms cause abstention when unsupported. Candidate ordering uses only the supported conditional **arm** contrast, with optical quality as an independent within-arm tie-break. No clinical benefit percentage is generated.
7. Shadow logs preserve model/feature/policy provenance. They explicitly record `actual_assignment_changed=false`, `manufacturing_authorized=false`, and `clinical_use_allowed=false`. A model has at most one log per patient/case/eye/index. The actual arm and measured twelve-month outcome are recorded separately; future measured endpoints and duplicate outcomes are rejected.
8. Monitoring reports patient-weighted observed outcomes/adherence by arm, age and sex, missing/pending/overdue follow-up, OOD frequency, standardized feature shift, unresolved severe events and QC failures. These observational summaries are not causal comparisons. Alerts require human review and do not silently retrain or promote a model.

Method reference: [PyWhy DRLearner estimating equations](https://www.pywhy.org/EconML/_autosummary/econml.dr.DRLearner.html) and [DR cross-fitting documentation](https://www.pywhy.org/EconML/spec/estimation/dr.html). The implementation uses existing NumPy/scikit-learn dependencies and does not copy library source or add EconML.

## API and UI

All mutations use the existing server-owned bearer roles, patient scope, audit and transactional idempotency receipts. No wildcard patient authorization is introduced.

| API suffix under `/api/v3` | Required permission |
|---|---|
| `POST /manufacturing/plans`, `/lots`, `/qc` | `manufacturing_engineer` |
| `POST /manufacturing/reviews` | `design_approver` |
| `POST /manufacturing/exposures`, `/outcomes` | `researcher` |
| `GET /manufacturing/cases/{id}/trace` | Read plus patient scope |
| `POST /adaptive/policies`, `/train`, `/shadow` | `adaptive_researcher` |
| `POST /adaptive/reviews` | `validator` |
| `POST /adaptive/deployments` | `deployer` |
| `POST /adaptive/outcomes` | `researcher` |
| `GET /adaptive/models/{id}`, `/monitor` | Read plus training-population scope; monitor also checks shadow-patient scope |

Roles may be combined for a synthetic operator session, but actor independence is always enforced in the service. `admin` still has explicit patient IDs and cannot self-approve.

`NSO_V3_MANUFACTURING_ENABLED` and `NSO_V3_ADAPTIVE_RANKING_ENABLED` default false. The latter enables **shadow software only**: health reports it separately as `adaptive_shadow_enabled`; the original `adaptive_ranking_enabled` remains **false**. The optimizer/IPM standalone surfaces include their respective extensions.

The existing research page now includes role-filtered workflow selection, downloadable synthetic JSON templates, file validation, scope binding, errors, manufacturing trace, held-out validation and shadow monitoring. Switching patient/eye unmounts the old workbench and clears its results. Session credentials remain in memory.

## Reproduce the synthetic HTTP rehearsal

From the repository root:

```sh
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v3_local_staging.py \
  --database-url sqlite:////private/tmp/choose-a-fresh-synthetic-v31.db --extensions
```

The launcher refuses databases containing non-synthetic patients and binds only loopback. It prints a private temporary folder; access codes are 0600, inside a 0700 folder, and never printed or committed. In another terminal:

```sh
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v31_staging_smoke.py \
  /absolute/path/to/the-private-temporary-folder
```

Use a fresh database for a full rerun: enrollment and outcome records are intentionally immutable. The rehearsal creates a passing synthetic model, logs a shadow ranking, records a complete manufacturing chain, rehearses rollback, then intentionally withdraws the model and plan and verifies both are blocked. Withdrawal at the end is expected evidence of the gate, not an unexpected failure.

## Verification evidence

Final backend counts/coverage are recorded in [V31_VALIDATION.md](V31_VALIDATION.md), with the complete regression log. Additional evidence:

- [Real HTTP manufacturing + V3.1 rehearsal](v31-staging-http-verification.json): 32 checks, including expected 401/409 denials, passing QC, explicit Visit IDs, controlled rollback and withdrawal.
- [Frontend component test log](v31-frontend-test-results.txt): 11 tests, including role/flag gates, scope binding and hidden protected fields.
- [Production build](v31-frontend-build-results.txt), [dependency audit](v31-frontend-dependency-audit.json), [black-box verification](v31-black-box-verification.json).
- [Browser QA record](v31-browser-verification.json), [monitor screenshot](v31-browser-monitor.png). Browser use became available on 28 October; the earlier 26 October browser limitation does not describe this later check.

## Remaining qualifications and software scope

The full research linkage and shadow workflow are executable. This does **not** finish every requirement in the teacher's V3.0/V3.1 document:

- The optical simulator and recipes remain reference implementations. An optical/manufacturing engineer must supply and qualify a physical process/machine adapter before real manufacturing; the workflow currently produces no toolpath or machine command.
- CATE supports a prespecified pair of arms per model. It does not combine three arms in one model or estimate continuous design-parameter treatment effects. Incremental clinical value of proprietary design parameters is not evaluated without linked dispensed-design outcome data; optical tie-breaks are not evidence of that value.
- No study has established exchangeability, prospective causal validity, clinical benefit, safe adaptive assignment or external NSO performance. Scientific/ethics/QA sign-off cannot be replaced by reference strings or synthetic tests.
- CI configuration exists; remote CI, container build/run, cloud hosting/TLS/identity integration and cloud rollback/restore acceptance remain unexecuted. Browser checks here are focused functional checks, not a comprehensive accessibility/device certification.
- No push, PR publication, production deployment or email to the teacher was performed.
