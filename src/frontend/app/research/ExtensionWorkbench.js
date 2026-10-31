"use client";
import { useState } from "react";
import RecordFields, { emptyTemplate } from "../components/RecordFields";
import MultiArmResults from "./MultiArmResults";

const ACTIONS = [
  ["Manufacturing plan", "/manufacturing/plans", ["manufacturing_engineer"], "Link a forecast and optical candidate; freeze process and QC requirements before review."],
  ["Manufacturing review", "/manufacturing/reviews", ["design_approver"], "Approve or withdraw an immutable plan as an independent reviewer."],
  ["Record lot", "/manufacturing/lots", ["manufacturing_engineer"], "Create a research lot linked to its protected recipe version."],
  ["Record QC", "/manufacturing/qc", ["manufacturing_engineer"], "The server computes acceptance against every locked metric. A failed lot stays quarantined."],
  ["Record exposure", "/manufacturing/exposures", ["researcher"], "Record an authorized research exposure after passing QC. This does not issue a prescription or shipment."],
  ["Manufacturing follow-up", "/manufacturing/outcomes", ["researcher"], "Link measured follow-up to the same lot and prediction; no model approval is granted."],
  ["Lock adaptive policy", "/adaptive/policies", ["adaptive_researcher"], "Freeze patient-disjoint train/test/external or temporal cohorts, analysis assumptions and thresholds."],
  ["Freeze three-arm cohort", "/adaptive/multiarm/cohorts", ["adaptive_researcher"], "Freeze all three arms with a common SA-only comparator and protected pre-index dispensed-design evidence."],
  ["Lock three-arm policy", "/adaptive/multiarm/policies", ["adaptive_researcher"], "Prespecify three-arm allocation, independent cohorts, per-arm support and design-value diagnostics."],
  ["Train DR prototype", "/adaptive/train", ["adaptive_researcher"], "Train the binary or three-arm model family frozen in the policy. Inspect independent validation before review."],
  ["Adaptive review", "/adaptive/reviews", ["validator"], "Independent scientific review for shadow use only; measured studies require ethics and assignment references."],
  ["Shadow deployment / rollback", "/adaptive/deployments", ["deployer"], "A separate operator enables a reviewed version. Rollback requires a prior deployment and a current approval."],
  ["Log shadow ranking", "/adaptive/shadow", ["adaptive_researcher"], "Supply two plans for binary models or all three arms for a three-arm model. Unsupported arms are withheld; a partial ranking never claims a complete comparison."],
  ["Shadow follow-up", "/adaptive/outcomes", ["researcher"], "Record the actual assigned arm and measured endpoint. One observed outcome cannot verify an individual effect."],
];

const OBSERVATION = { visit_at: "2027-01-01", al_mm: 24.2, se_d: -2.2, al_status: "measured", se_status: "measured", measurement_method: "SYNTHETIC fixture", source: "SYNTHETIC_NOT_CLINICAL_EVIDENCE", quality_flag: "ACCEPTED" };
function template(path, scope) {
  const templates = {
    "/manufacturing/plans": { ...scope, prediction_id: "REPLACE_PREDICTION_ID", candidate_id: "REPLACE_CANDIDATE_ID", mode: "synthetic_rehearsal", arm: "SA_ONLY", process_reference: "SYNTHETIC_PROCESS", material_code: "SYNTHETIC", qc_requirements: [{ name: "surface_error", unit: "um", lower: 0, upper: 0.2 }] },
    "/manufacturing/reviews": { plan_id: "REPLACE_PLAN_ID", decision: "approve", reason: "Independent synthetic rehearsal review only.", process_qualification_reference: "SYNTHETIC_QUALIFICATION" },
    "/manufacturing/lots": { plan_id: "REPLACE_PLAN_ID", lot_code: "REPLACE_UNIQUE_SYNTHETIC_LOT", manufacturer_id: "SYN_OEM", facility_id: "SYN_FACILITY" },
    "/manufacturing/qc": { lot_id: "REPLACE_LOT_ID", measurements: [{ name: "surface_error", actual: 0.1, unit: "um" }], evidence_reference: "SYNTHETIC_QC" },
    "/manufacturing/exposures": { lot_id: "REPLACE_LOT_ID", start_at: "2026-01-02", adherence: 0.9, authorization_reference: "SYNTHETIC_AUTHORIZATION" },
    "/manufacturing/outcomes": { lot_id: "REPLACE_LOT_ID", prediction_id: "REPLACE_PREDICTION_ID", observation: OBSERVATION },
    "/adaptive/policies": { name: "Synthetic locked DR policy", train_cohort_id: "REPLACE_TRAIN_COHORT", test_cohort_id: "REPLACE_TEST_COHORT", external_cohort_id: "REPLACE_EXTERNAL_COHORT", holdout: "external_site", evidence_kind: "synthetic", minimum_patients_per_arm: 30, analysis_plan: "Prespecified synthetic held-out research evaluation.", identification_assumptions: "Synthetic assignment, consistency, positivity and no interference." },
    "/adaptive/multiarm/cohorts": { protocol_id: "REPLACE_PROTOCOL_ID", cohort_name: "Three-arm study partition", eligibility_version: "REPLACE_VERSION", assignment: "randomized", comparator: "SA_ONLY", study_arms: ["SA_ONLY", "SA_BN", "SA_BN_FIBER"], index_date: "2030-01-01", estimand: "12_month_delta_al_mm", analysis_plan: "Prespecified twelve-month AL changes, common SA-only comparator.", members: [{ ...scope }] },
    "/adaptive/multiarm/policies": { name: "Synthetic three-arm policy", train_cohort_id: "REPLACE_TRAIN_COHORT", test_cohort_id: "REPLACE_TEST_COHORT", external_cohort_id: "REPLACE_EXTERNAL_COHORT", evidence_kind: "synthetic", arm_names: ["SA_ONLY", "SA_BN", "SA_BN_FIBER"], assignment_probabilities: { SA_ONLY: 1/3, SA_BN: 1/3, SA_BN_FIBER: 1/3 }, require_design_analysis: true, minimum_patients_per_arm: 30, minimum_local_patients_per_arm: 5, minimum_local_ess_per_arm: 4, analysis_plan: "Prespecified three-arm and nested design-value study.", identification_assumptions: "Consistency, positivity and exchangeability need independent scientific review." },
    "/adaptive/train": { policy_id: "REPLACE_POLICY_ID" },
    "/adaptive/reviews": { model_id: "REPLACE_MODEL_ID", decision: "approve", reason: "Independent synthetic shadow validation only.", scientific_review_reference: "SYNTHETIC_REVIEW", ethics_reference: null, assignment_review_reference: null },
    "/adaptive/deployments": { model_id: "REPLACE_MODEL_ID", review_id: "REPLACE_REVIEW_ID", reason: "Deploy approved synthetic shadow version only.", rollback_to_deployment_id: null },
    "/adaptive/shadow": { ...scope, enrollment_id: "REPLACE_ENROLLMENT_ID", plan_ids: ["REPLACE_SA_ONLY_PLAN", "REPLACE_SA_BN_PLAN", "REPLACE_SA_BN_FIBER_PLAN"] },
    "/adaptive/outcomes": { shadow_id: "REPLACE_SHADOW_ID", observed_arm: "SA_ONLY", observation: OBSERVATION, adherence: 0.9, source_reference: "SYNTHETIC_FOLLOWUP" },
  };
  return templates[path];
}

export default function ExtensionWorkbench({ api, roles, scope, manufacturingEnabled, adaptiveEnabled, workflowGroup }) {
  const allowed = ACTIONS.filter(([, path, needed]) => (!workflowGroup || (workflowGroup === "adaptive" ? path.startsWith("/adaptive/") : path.startsWith("/manufacturing/"))) && (path.startsWith("/adaptive/") ? adaptiveEnabled : manufacturingEnabled) && (roles.includes("admin") || needed.some(r => roles.includes(r))));
  const [kind, setKind] = useState(allowed[0]?.[1] || "");
  const [draft, setDraft] = useState(null);
  const [file, setFile] = useState(null), [result, setResult] = useState(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [modelId, setModelId] = useState("");
  const [shadowId, setShadowId] = useState("");
  const selected = allowed.find(a => a[1] === kind) || allowed[0];
  async function run(fn) { setBusy(true); setError(""); setResult(null); try { setResult(await fn()); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(template(selected[1], scope), null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "synthetic-workflow-template.json"; link.click(); URL.revokeObjectURL(url);
  }
  return <section className="card research-section extension-workbench" aria-label="Manufacturing and adaptive research">
    <h2>{workflowGroup === "adaptive" ? "Shadow research workflow" : "Manufacturing workflow"}</h2>
    <p className="note">Reference recipes preserve reproducibility and require engineering qualification before machine use. Shadow rankings never authorize treatment or manufacturing. Templates contain invented values.</p>
    {!manufacturingEnabled && !adaptiveEnabled && <p role="status">These workflows are disabled by server feature flags.</p>}
    {allowed.length === 0 && (manufacturingEnabled || adaptiveEnabled) && <p className="research-empty">Your session has no submission permission for this workflow. Inspection remains subject to your assigned role.</p>}
    {allowed.length > 0 && <form onSubmit={e => { e.preventDefault(); run(async () => {
      if (file && file.size > 8_000_000) throw new Error("The maximum upload is 8 MB.");
      const data = file ? JSON.parse(await file.text()) : (draft || emptyTemplate(template(selected[1], scope)));
      if (["/manufacturing/plans", "/adaptive/shadow"].includes(selected[1])) Object.assign(data, scope);
      return api(selected[1], data);
    }); }}>
      <label className="field">Workflow<select aria-label="Workflow" disabled={busy} value={selected[1]} onChange={e => { setKind(e.target.value); setDraft(null); setFile(null); setResult(null); setError(""); }}>{allowed.map(([label, path]) => <option key={path} value={path}>{label}</option>)}</select></label>
      <p className="note">{selected[3]}</p>
      <fieldset disabled={!!file} className="workflow-form-fields"><legend>Workflow record</legend><RecordFields schema={template(selected[1],scope)} value={draft || emptyTemplate(template(selected[1],scope))} onChange={setDraft} locked={["patient_id","case_id","eye"]} /></fieldset>
      <details className="research-details"><summary>Advanced · import a prepared JSON record</summary><button type="button" className="btn btn-ghost" onClick={download}>Download synthetic template</button>
      <label className="field">Workflow JSON<input key={selected[1]} type="file" accept=".json,application/json" disabled={busy} onChange={e => setFile(e.target.files?.[0] || null)} /></label>
      </details><button className="btn btn-primary" disabled={busy}>Submit research workflow</button>
    </form>}
    <div className="row">
      {workflowGroup !== "adaptive" && manufacturingEnabled && <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => run(() => api(`/manufacturing/cases/${encodeURIComponent(scope.case_id)}/trace`))}>Inspect manufacturing trace</button>}
      {workflowGroup !== "manufacturing" && adaptiveEnabled && <form onSubmit={e => { e.preventDefault(); run(() => api(`/adaptive/models/${encodeURIComponent(modelId)}/monitor`)); }}><label className="field">Adaptive model ID<input type="text" required value={modelId} onChange={e => setModelId(e.target.value)} /></label><button className="btn btn-ghost" disabled={busy}>Inspect shadow monitoring</button><button type="button" className="btn btn-ghost" disabled={busy || !modelId} onClick={() => run(() => api(`/adaptive/models/${encodeURIComponent(modelId)}`))}>Inspect held-out validation</button><button type="button" className="btn btn-ghost" disabled={busy || !modelId} onClick={() => run(() => api(`/adaptive/models/${encodeURIComponent(modelId)}/design-analysis`))}>Inspect design parameter value</button></form>}
    </div>
    {workflowGroup !== "manufacturing" && adaptiveEnabled && <form onSubmit={e=>{e.preventDefault();run(()=>api(`/adaptive/shadows/${encodeURIComponent(shadowId)}`));}}><label className="field">Shadow record ID<input type="text" required value={shadowId} onChange={e=>setShadowId(e.target.value)} /></label><button className="btn btn-ghost" disabled={busy || !shadowId}>Inspect shadow record</button></form>}
    {error && <p role="alert" className="research-error">{error}</p>}
    {result && <div role="status"><h3>Research workflow result</h3><MultiArmResults result={result} /><p className="note">Clinical use and automatic manufacturing remain disabled.</p><details><summary>Technical record details</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "32rem", overflowY: "auto" }}>{JSON.stringify(result, (key, value) => ["parameters", "tolerances", "qc_requirements", "support_z", "support_arms", "features"].includes(key) ? undefined : value, 2)}</pre></details></div>}
  </section>;
}
