# V3.1 three-arm shadow and design-value evaluation

Updated 29 October 2026. Extends the binary research workflow; preserves the binary API and manufacturing bridge. The implementation is research software, not validated clinical ranking.

## Implemented

1. **One three-arm model:** SA_ONLY, SA_BN and SA_BN_FIBER share SA_ONLY as comparator and measured twelve-month AL change (mm) as estimand. Native immutable cohort snapshots include assigned arm, actual dispensed arm, protocol, dates, measured endpoint and protected design evidence. A single cross-fitted multinomial DR learner estimates both intervention contrasts against the same control. Patient-level averaging precedes learning and evaluation.
2. **Per-arm support and abstention:** independent train/test/external-site or later temporal partitions, allocation probabilities for randomized cohorts, multinomial propensity for observational cohorts, counts, propensity extremes and ESS. At shadow time, global range plus local patients/ESS/propensity are checked separately for each arm. Three approved feasible arm plans are required. An unsupported intervention is omitted and the response explicitly says partial ranking. An unsupported comparator produces no ranking. Shadow responses never assign treatment, manufacture a lens, authorize clinical use or provide an individual causal confidence interval.
3. **Predictive design-value pipeline:** history → history plus actual dispensed arm and history interactions → history plus arm plus protected design parameters. All stages use identical eligible independent patients; preprocessing and fixed-parameter Ridge models fit training patients only. Test/external metrics include MAE/RMSE/bias and paired patient bootstrap MSE changes. Each feature group has refitted leave-group-out ablation and repeated within-arm training permutations. Orientation uses doubled-angle sine/cosine and is zero when fiber is inactive. Only parameters with within-arm variation can support an incremental claim. Constant arm-encoding parameters return unavailable rather than fabricated value.

The common-control DR equations follow the methodology described in [PyWhy's multiple discrete treatment documentation](https://www.pywhy.org/EconML/spec/estimation/dr.html). The diagnostic feature analysis follows the separation of training and held-out inspection discussed in [scikit-learn's importance documentation](https://scikit-learn.org/stable/modules/permutation_importance). This is an independent implementation using existing dependencies, not a reproduction of MPPM or EconML.

## Leakage and provenance controls

- Cohorts and analysis policy are frozen before training; patient partitions include missing/excluded patients when testing disjointness. External sites or later index dates are checked. Validation patients already used by another model cannot be relabeled as unseen holdouts.
- Allowed baseline features are locked by protocol. Client-supplied outcome, adherence, QC-error or future-measurement columns are forbidden. AL/SE endpoints must be measured and accepted. Randomized assignment is retained; incomplete patient endpoints are excluded with bounded missingness, not interpreted as a full missing-data correction.
- Design inputs come only from linked server records: recorded dispense → matching patient/case/eye → lot → recipe version → optical candidate → QC. Physical lot/QC identity cannot cross independent patients/partitions. Design features are frozen in the cohort and are never read from a later optimizer result or uploaded feature table.
- Evidence created on/after the index day is conservatively excluded (UTC midnight cutoff for calendar-date index). Only pre-index QC determines eligibility; post-index QC is ignored and counted, so future QC does not select training patients. This strict policy may require a different scientifically approved timestamp contract for same-day real studies.
- Recipe values and QC/tolerance values stay protected. Reports expose group names and aggregate diagnostics, not raw parameters. Clinical ranking remains disabled; only the separate shadow feature flag is enabled.

## API and UI

New authenticated, role/patient-scoped, audited/idempotent mutations:

- `POST /api/v3/adaptive/multiarm/cohorts`
- `POST /api/v3/adaptive/multiarm/policies`

Existing `/adaptive/train`, reviews, deployments, rollback, shadow, outcomes and monitoring accept the model family stored in the policy/model. New read projections:

- `GET /api/v3/adaptive/models/{model_id}/design-analysis`
- `GET /api/v3/adaptive/shadows/{shadow_id}` (baseline feature vectors withheld)

The workbench adds cohort/policy templates, three-arm support/ranking tables, complete/partial/abstained labels and nested design-value metric tables. Synthetic results carry an explicit synthetic fixture label. Unsupported arm scores are withheld in both service and presentation. Positive predictive increments and per-feature conclusions require held-out uncertainty support; they do not imply causal parameter effects.

## Verification and reproduction

See [MULTIARM_VALIDATION.md](MULTIARM_VALIDATION.md) for exact test counts and artifacts. Synthetic fixtures include positive parameter signal, null parameter signal, local arm support holes, unsupported comparator, patient/physical-entity leakage, post-index evidence, forbidden features and observational propensity JSON roundtrip.

```sh
# Python 3.12.16, isolated local fixture database only:
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v3_local_staging.py \
  --database-url sqlite:////private/tmp/choose-a-fresh-three-arm-test.db --multiarm
# Use the private folder printed by the launcher; do not copy credentials into reports:
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v31_multiarm_smoke.py \
  /absolute/path/to/private-temporary-folder
```

The launcher bulk-loads explicitly invented historical provenance and seeds feasible shadow plans. These are test records, not proof that physical lenses were manufactured. Other manufacturing tests execute the actual recipe/lot/QC/exposure APIs. The HTTP rehearsal freezes new cohorts, trains/reviews/deploys one model, checks all three ranking states and preserves their IDs for inspection in the UI.

## Limits

Held-out pseudo-outcome errors are research diagnostics, not known ground-truth CATE errors. Arm contrast intervals use a fixed-nuisance normal approximation and Bonferroni correction for two common-control contrasts; policy-value intervals are approximate. Predictive parameter analysis uses fixed fitted-model patient bootstraps; feature intervals adjust for the number of groups, but repeated model selection or correlated features still require scientific review. Within-arm permutation and ablation identify predictive reliance, not causal mechanisms.

No measured clinical cohort, optical calibration, clinical benefit percentage, regulatory sign-off, automatic treatment assignment or machine toolpath is produced. No remote CI/container/cloud deployment, push or email was performed. Real study data, prospective external validation and independent scientific/engineering acceptance remain necessary.
