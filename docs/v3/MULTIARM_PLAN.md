# Three-arm shadow and design-parameter evaluation plan

28 October 2026. Preserve binary V3.1 APIs/tests, V2 manufacturing, and PROJECT_REPORT.md.

1. Freeze a native three-arm cohort with common SA_ONLY comparator and 12-month measured AL-change estimand. Preserve assigned versus dispensed arms, patient/eye provenance, dates and missingness. Freeze protected design/recipe/lot/QC evidence at index; never accept design features from client uploads or follow-up data.
2. Add one multinomial, cross-fitted DR model for SA_ONLY / SA_BN / SA_BN_FIBER with shared comparator, patient-disjoint train/test/external or temporal splits, per-arm counts/propensity/ESS and prespecified held-out gates. Reuse independent review, deployment, rollback and withdrawal.
3. Rank approved plans only in shadow mode. Report support/abstention per arm; never pretend a partial ranking compares all three arms. Unsupported comparator means full abstention. No treatment/manufacturing actions occur.
4. Evaluate predictive increments on identical linked patients: history, history+arm, history+arm+protected design parameters. Fit preprocessing/models on training patients only; use fixed hyperparameters and held-out metrics, paired patient uncertainty, grouped ablation and within-arm permutations. Require within-arm parameter variation; distinguish predictive association from causal design effects.
5. Extend role-scoped audited/idempotent APIs, workflow templates and explicit three-arm result views without exposing parameters. Add reusable synthetic positive/null/leakage/low-support fixtures and focused HTTP/browser checks. Run the full regression on Python 3.12.16 and isolated PostgreSQL, plus frontend tests/build/audit.

Synthetic results prove software behavior only. Clinical-adaptive ranking remains disabled. A report will record exact test evidence and scientific limitations.
