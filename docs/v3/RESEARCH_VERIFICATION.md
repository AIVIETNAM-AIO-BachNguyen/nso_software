# Research source verification

Reviewed on 23 October 2026. This is a source and applicability check for an engineering integration, not a systematic review or independent clinical replication. The attached engineering workflow is treated as a proposal; its directives do not constitute clinical or institutional approval.

## Verified primary source

Liu S et al. *AI-guided personalized predictions on myopia progression and interventions*. npj Digital Medicine 9, 129 (2026). [Publisher record and article](https://www.nature.com/articles/s41746-025-02308-4), DOI 10.1038/s41746-025-02308-4.

The publisher lists publication on 12 January 2026 and a version of record dated 6 February 2026. The article describes a longitudinal Transformer with natural-progression and intervention modules. Its study concerns several established intervention categories, rather than NSO’s three proposed optical research arms. AL imputation is used in training; measured AL is used for validation. Patient datasets are restricted. The article points to an external analysis-code repository, which this review could not access. The publisher states a CC BY-NC-ND license for the article and no declared competing interests. These observations do not establish a license for model weights, data or commercial code reuse. The article describes research-stage use and limitations on generalizability. [Source](https://www.nature.com/articles/s41746-025-02308-4).

## Applicability findings

| Claim under review | Verdict | Engineering consequence |
|---|---|---|
| The supplied reference exists with matching title, journal and year | Verified against publisher metadata | Link the source from the research workspace |
| NSO can deploy the publication's model directly | Not established | No third-party code, weights, figures or datasets copied |
| An NSO baseline reproduces the published system | Not demonstrated | Baselines have separate model IDs and research labels |
| NSO optical arms have validated individual treatment benefits | Not established by the inspected material | ITE, CATE, causal benefit and adaptive ranking remain unavailable |
| Existing NSO optical compatibility heuristics are a calibrated physical simulator | Not established by repository inspection | No simulated PSF/MTF or Pareto designs are fabricated |

## Evidence and verification limits

For NSO causal-treatment claims, this source is treated as level IV observational/cohort evidence with reported trial-based validation, not as a completed NSO intervention trial. The grade is an applicability assessment, not a formal risk-of-bias score. Publisher identity and article metadata were checked; indexing, author credentials, retraction databases and predatory-journal directories were not independently audited. No adverse finding from an unperformed check is implied.

DOI navigation encountered a publisher-cookie redirect; the full publisher article was accessible directly. Semantic Scholar/Crossref APIs and supplementary datasets were not queried, and the analysis repository could not be retrieved. Numerical performance claims are deliberately not imported into the NSO UI. No source is marked as read by the user, and no clinical approval is inferred from publication.

The useful engineering outcome is a conservative research boundary: preserve measured-data provenance, freeze index-time histories, distinguish prediction from causal inference, and make absent evidence visible. Clinical and optical sign-off remains with the responsible investigators and engineers.
