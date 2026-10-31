# Frontend redesign — 30 October 2026

Implemented in the existing Next.js application. No deployment or manufacturing release was performed.

## Changed behavior

- Shared workspace navigation and responsive layouts across clinical care and research.
- Clinical patient search, explicit assessment date and read-only recorded measurement history. Historical SE is not silently treated as a sphere/cylinder prescription.
- Clinical measurements start blank, have associated accessible labels, and use native form validation. Missing required numeric values no longer become zero in request construction.
- Review/confirmation before generating a recommendation. Results prioritize recommendation, reasons and next action; detailed indicators are expandable.
- Per-patient drafts remain in memory during the signed-in session. Clinical drafts survive client-side navigation between care and research. Sign-out and inactivity clear them; a full page reload also clears the workspace. These are session drafts, not durable visit records.
- Follow-up baseline comes from the confirmed assessment. New follow-up measurements start blank. Assessment requires explicit submission; edits invalidate old results. Refit uses current measurements, resets approval and starts the next baseline from the follow-up visit.
- Clinical API 401 responses clear the expired clinical session. Slow requests display elapsed/waiting state rather than fabricated processing stages. Non-JSON server errors produce a readable retry message.
- Research areas separate patient forecasts, study records, study analysis, optical design, model governance, manufacturing and shadow research. Existing backend authorization and release gates remain enforced.
- Manufacturing/adaptive workflows have structured forms with nested records and repeatable rows. JSON import remains an advanced alternative. Technical JSON results are collapsed.
- Same-origin `/backend` proxy by default. Configure server-side `NSO_API_BASE` for another backend; existing `NEXT_PUBLIC_API_BASE` remains supported.
- Fixed an integration blocker in the backend: an unrelated historical recipe-version record lacking `recipe_id` previously raised a KeyError during clinical fitting. The reader now skips records that cannot belong to the current recipe; no records are deleted or rewritten.

## Validation

- 19 frontend tests passed, including baseline linkage, explicit follow-up submission, invalidation after edits, refit/approval reset and non-JSON errors.
- 8 targeted backend tests passed: recipe history compatibility, engineering workflow and clinical authentication tests.
- Next.js production build passed; `git diff --check` passed.
- Browser checks before browser control was disabled in Work settings: clinical sign-in, blank required inputs with associated labels, pre-generation review, patient draft isolation/restoration, navigation preserving a clinical draft, separate research tabs and 390px responsive layouts. Both care and research had document width 390px at a viewport width of 390px.
- Reproduced the HTTP 500 against a copied synthetic staging database, traced it to missing recipe identity, added regression coverage, then restarted the same synthetic-only local staging service to load the fix. Real loopback calls to `/api/predict` and `/api/followup` both returned 200. No approval/manufacturing call was made during that HTTP check.
- Final browser interaction was unavailable because browser use was disabled in Work settings. Later small changes were validated through tests/build; no claim is made that every authorized research mutation has been exercised in the final browser build.

## Current limits

Some specialist bulk-data operations (training datasets, optical engineering imports and observation batches) intentionally retain file import. Some research references still require record IDs; this change does not add a new backend-wide record catalog. Patient drafts are not a replacement for durable clinical visit storage, scheduling or a full EHR. Those capabilities need separate API/data-model work.

Preview: http://127.0.0.1:3100. The existing service on port 3000 needs a restart to load the new build.

## User-supplied visual reference

Applied the Notion-style visual language from `DESIGN (3).md`: warm `#f6f5f4` canvas, white surfaces with hairline borders and 12px corners, a light notebook sidebar, Inter headings with tighter tracking, sparse editorial serif introductions, peach/sky heading highlights, blue primary actions and pale-blue secondary actions. Button corners use 8px, following the main component specification rather than the contradictory pill-button example in the reference. Clinical warning colors retain their semantic meaning. The visual theme is isolated in `app/notebook.css`.

Validation for this visual pass: 19 frontend tests passed and production build passed. Browser use was disabled in Work settings, so this specific visual pass has not been screenshot-verified; earlier screenshots represent the previous theme.

## Superseding visual reference: Steep

Replaced the Notion theme with the user's `DESIGN (4).md` Steep reference. Active stylesheet: `app/clinical-theme.css`; the superseded `notebook.css` was removed. White canvas, mist-gray content surfaces, 24px card corners, 16px inputs, black/outlined pill actions and regular-weight Source Serif 4/Georgia headings replace the warm notebook/blue-button treatment. UI/body typography remains Inter. Peach is reserved for the patient-context panel; clinical severity indicators retain their existing semantics. Display sizes are scaled for working clinical screens, with responsive reductions on mobile. Helper text uses darker neutral grays for legibility.

Validation: 19 frontend tests and production build passed; diff whitespace checks passed. Browser verification remains unavailable because local browser use is disabled in Work settings. Previous screenshots do not represent this new theme.

### Clinical blue accent

Per the subsequent user request, primary actions, active navigation, focus outlines, connected indicators and READY/STABLE status surfaces now use clinical blue (`#1764c0`, pale `#edf5ff`) rather than green. Amber/red warnings remain distinct. The Steep layout, serif headings and white/mist surfaces remain.

The blue palette now also covers all secondary/text buttons, research mode selectors, module tabs and disclosure controls. Sidebar uses navy `#12447f`, pale readable navigation text, white selected-item surfaces and blue active text; primary controls use `#1764c0`. Hover/focus states follow the same palette on desktop and mobile.

### Cascade correction

The generated Next.js bundle placed the old global stylesheet after the clinical theme, overriding theme rules despite source import order. Explicit CSS cascade layers (`workspace-base`, then `clinical-theme`) now guarantee theme precedence independent of bundle ordering. Verified the production CSS layer order and navy sidebar rule after a successful build. Browser use remained disabled, so this verification is against the generated stylesheet rather than a new screenshot.

Pastel refinement: sidebar uses pale blue `#e6eef6` with dark blue-gray text; primary buttons and selected tabs use `#d6e4f1` with `#304e6e` text. Saturated navy/royal-blue fills were removed. Calculated contrast is 6.00:1 for sidebar text and 6.65:1 for primary-button text. Production build and diff checks passed.

Adjusted the pastel palette to a medium dusty blue at the user's request: sidebar `#bbcee1`, primary buttons/active tabs `#51769f` with white text, hover `#466b96`. This sits between the saturated navy and the earlier very pale blue. White text on the primary fill has a calculated 4.73:1 contrast.

## Desktop density update — 1 November 2026

Sidebar uses the dominant sampled blue from the supplied button image: RGB(74,105,146), `#4a6992`. Removed the boxed “n” logo; the wordmark is now NSO only. Reduced sidebar width, heading sizes, content padding and section gaps. Replaced decorative page titles, grouped research source/eye controls into one toolbar and combined patient search, patient selector, assessment date and session actions into one clinical bar. Removed the redundant patient-context panel while retaining manual-entry/session guidance and recorded history.

19 frontend tests, production build and diff checks passed. Desktop browser verification confirmed the sidebar's computed RGB matches the sample. At the same desktop viewport, the first research card moved from y=592px to y=269px. A desktop screenshot was saved as `compact-desktop-2026-11-01.jpg`. Mobile verification was skipped at the user's explicit request.

### NSO Clinical and hover sidebar

Wordmark changed to “NSO Clinical” on one line in one font size. Desktop sidebar defaults to a 64px icon rail, expands to 244px on hover or keyboard focus-visible, and closes on pointer exit. It overlays the page during expansion so content stays at x=64px without shifting. Browser verification confirmed 64 → 244 → 64px and full wordmark visibility. Build and diff checks passed; screenshot: `sidebar-hover-2026-11-01.jpg`.
