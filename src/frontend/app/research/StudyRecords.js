"use client";

import { useEffect, useRef, useState } from "react";

const arms = ["NONE", "SA_ONLY", "SA_BN", "SA_BN_FIBER", "OTHER"];

export default function StudyRecords({ scope, history, api, refresh, onProtocol }) {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [protocolId, setProtocolId] = useState("");
  const [file, setFile] = useState(null);
  const [correction, setCorrection] = useState({ id: "", al: "", se: "", al_status: "measured", se_status: "measured", reason: "" });
  const [protocol, setProtocol] = useState({ name: "", version: "1", assignment: "observational", inclusion: "", exclusion: "", estimand: "", analysis_plan: "",
    missingness_plan: "Report missing endpoints and assess sensitivity before interpreting results.",
    switching_plan: "Record treatment switching and distinguish intention-to-treat from per-protocol analyses.",
    safety_plan: "Record adverse events, review unresolved serious events and require human safety review." });
  const [enrollment, setEnrollment] = useState({ index_date: "", age: "", baseline_al: "", baseline_se: "", prior_al_slope: "", sex_code: "0", assigned_arm: "NONE", allocation_reference: "", eligible: true, eligibility_reasons: "" });
  const [event, setEvent] = useState({ event_at: "", kind: "adverse_event", severity: "mild", description: "" });
  const generation = useRef(0);
  useEffect(() => { generation.current++; setMessage(""); setError(""); setCorrection({ id: "", al: "", se: "", al_status: "measured", se_status: "measured", reason: "" }); }, [scope.case_id, scope.eye]);
  async function act(fn) {
    const id = generation.current; setBusy(true); setError(""); setMessage("");
    try { const text = await fn(); if (id === generation.current) setMessage(text); }
    catch (e) { if (id === generation.current) setError(e.message); }
    finally { setBusy(false); }
  }
  const input = (record, setter, key, type="text", attributes={}) => <input type={type} required value={record[key]} onChange={e => setter({ ...record, [key]: e.target.value })} {...attributes} />;
  const original = history.find(r => r.record_id === correction.id);
  return <section className="card research-section"><h2>Study records & measurement quality</h2><p className="research-copy">Add protocol and enrollment records, import dated observations or correct a transcription without deleting its original value. All changes are recorded in the case history.</p>
    {error && <p className="err" role="alert">{error}</p>}{message && <p role="status" className="research-copy">{message}</p>}
    <details className="research-details"><summary>Import observations for the selected eye</summary><form onSubmit={e => { e.preventDefault(); act(async () => { const parsed = JSON.parse(await file.text()); await api("/observations", { ...scope, observations: Array.isArray(parsed) ? parsed : parsed.observations }); await refresh(); return "Observation batch saved. Every row passed validation before the batch was committed."; }); }}>
      <p className="note">JSON file containing an observation array with date, AL/SE, provenance, measurement method and source. Only this selected case and eye will be imported.</p>
      <input aria-label="Observation JSON file" type="file" accept=".json,application/json" required onChange={e => setFile(e.target.files[0])} /><button className="btn btn-primary" disabled={busy || !file}>Validate & import</button>
    </form></details>
    <details className="research-details"><summary>Correct an imported observation</summary><form onSubmit={e => { e.preventDefault(); act(async () => { const al = correction.al === "" ? null : Number(correction.al), se = correction.se === "" ? null : Number(correction.se); const replacement = { visit_at: original.visit_at, al_mm: al, se_d: se,
      al_status: al === null ? "missing" : correction.al_status, se_status: se === null ? "missing" : correction.se_status, measurement_method: original.measurement_method, source: original.source, quality_flag: original.quality_flag };
      await api("/observations/correct", { ...scope, observation_id: original.record_id, expected_revision: original.revision || 0, reason: correction.reason, replacement }); await refresh(); return "Correction saved as a new revision. The original measurement was preserved."; }); }}>
      <div className="grid2"><label className="field">Observation<select required value={correction.id} onChange={e => { const row=history.find(r => r.record_id === e.target.value); setCorrection({ id: e.target.value, al: row?.al_mm ?? "", se: row?.se_d ?? "", al_status: row?.al_status === "imputed" ? "imputed" : "measured", se_status: row?.se_status === "imputed" ? "imputed" : "measured", reason: "" }); }}><option value="">Select an imported row</option>{history.filter(r=>r.record_id).map(r => <option key={r.record_id} value={r.record_id}>{r.visit_at} · revision {r.revision || 0}</option>)}</select></label>
      <label className="field">Corrected AL (mm)<input type="number" step=".001" min="18" max="35" value={correction.al} onChange={e=>setCorrection({...correction,al:e.target.value})} /></label>
      <label className="field">Corrected SE (D)<input type="number" step=".01" min="-20" max="15" value={correction.se} onChange={e=>setCorrection({...correction,se:e.target.value})} /></label>
      {["al_status","se_status"].map(key=><label className="field" key={key}>{key.startsWith("al") ? "AL" : "SE"} provenance<select value={correction[key]} onChange={e=>setCorrection({...correction,[key]:e.target.value})}><option value="measured">Measured</option><option value="imputed">Imputed</option></select></label>)}</div>
      <label className="field">Reason for correction<textarea required minLength={10} value={correction.reason} onChange={e=>setCorrection({...correction,reason:e.target.value})} /></label><button className="btn btn-primary" disabled={busy || !original}>Save new revision</button>
    </form></details>
    <details className="research-details"><summary>Register a locked study protocol</summary><form onSubmit={e=>{ e.preventDefault(); act(async()=>{ const {inclusion,exclusion,...fields}=protocol; const result=await api("/studies/protocols", {...fields, inclusion_criteria:inclusion.split("\n").filter(Boolean), exclusion_criteria:exclusion.split("\n").filter(Boolean), covariates:["age","baseline_al","baseline_se"], analysis_population:protocol.assignment==="randomized"?"intention_to_treat":"per_protocol"}); setProtocolId(result.record_id); onProtocol(result.record_id); return "Protocol registered: "+result.record_id; }); }}>
      <div className="grid2"><label className="field">Study name{input(protocol,setProtocol,"name")}</label><label className="field">Protocol version{input(protocol,setProtocol,"version")}</label><label className="field">Assignment<select value={protocol.assignment} onChange={e=>setProtocol({...protocol,assignment:e.target.value})}><option value="observational">Observational</option><option value="randomized">Randomized · allocation references required</option></select></label></div>
      {[["inclusion","Inclusion criteria · one per line"],["exclusion","Exclusion criteria · one per line"],["estimand","Effect to estimate"],["analysis_plan","Analysis plan"],["missingness_plan","Missing follow-up plan"],["switching_plan","Treatment switching plan"],["safety_plan","Safety review plan"]].map(([key,label])=><label key={key} className="field research-plan">{label}<textarea required minLength={["inclusion","exclusion"].includes(key)?1:20} rows={3} value={protocol[key]} onChange={e=>setProtocol({...protocol,[key]:e.target.value})} /></label>)}
      <p className="note">This form freezes age, baseline AL and baseline SE as adjustment covariates. Use a new protocol version to change the study definition.</p><button className="btn btn-primary" disabled={busy}>Register protocol</button>
    </form></details>
    <details className="research-details"><summary>Enroll the selected patient and eye</summary><form onSubmit={e=>{e.preventDefault();act(async()=>{const body={...scope,...enrollment,protocol_id:protocolId, age:Number(enrollment.age),baseline_al:Number(enrollment.baseline_al),baseline_se:Number(enrollment.baseline_se),prior_al_slope:Number(enrollment.prior_al_slope),sex_code:Number(enrollment.sex_code),allocation_reference:enrollment.allocation_reference||null,eligibility_reasons:enrollment.eligibility_reasons.split("\n").filter(Boolean)};await api("/studies/enrollments",body);return "Enrollment saved for this eye and protocol.";});}}>
      <label className="field">Registered protocol ID<input required value={protocolId} onChange={e=>{setProtocolId(e.target.value);onProtocol(e.target.value);}} /></label><div className="grid2">
      {[["index_date","Baseline date","date"],["age","Age at baseline","number"],["baseline_al","Measured baseline AL (mm)","number"],["baseline_se","Measured baseline SE (D)","number"],["prior_al_slope","Prior AL change (mm/year)","number"]].map(([key,label,type])=><label className="field" key={key}>{label}{input(enrollment,setEnrollment,key,type,type==="number"?{step:"any"}:{})}</label>)}
      <label className="field">Assigned arm<select value={enrollment.assigned_arm} onChange={e=>setEnrollment({...enrollment,assigned_arm:e.target.value})}>{arms.map(a=><option key={a}>{a}</option>)}</select></label>
      <label className="field">Recorded sex code<select value={enrollment.sex_code} onChange={e=>setEnrollment({...enrollment,sex_code:e.target.value})}><option value="0">0 · protocol-defined</option><option value="1">1 · protocol-defined</option></select></label>
      <label className="field">Allocation reference · randomized studies<input value={enrollment.allocation_reference} onChange={e=>setEnrollment({...enrollment,allocation_reference:e.target.value})} /></label></div>
      <label className="research-check"><input type="checkbox" checked={enrollment.eligible} onChange={e=>setEnrollment({...enrollment,eligible:e.target.checked})} />Meets protocol eligibility</label><label className="field">Eligibility reasons<textarea required value={enrollment.eligibility_reasons} onChange={e=>setEnrollment({...enrollment,eligibility_reasons:e.target.value})} /></label><button className="btn btn-primary" disabled={busy}>Save enrollment</button>
    </form></details>
    <details className="research-details"><summary>Record a safety or follow-up event</summary><form onSubmit={e=>{e.preventDefault();act(async()=>{await api("/studies/events",{...scope,...event,protocol_id:protocolId});return "Study event saved in the audit history.";});}}><label className="field">Registered protocol ID<input required value={protocolId} onChange={e=>setProtocolId(e.target.value)} /></label><div className="grid2"><label className="field">Event date{input(event,setEvent,"event_at","date")}</label><label className="field">Event type<select value={event.kind} onChange={e=>setEvent({...event,kind:e.target.value,severity:e.target.value==="adverse_event"?"mild":"not_applicable"})}>{["adverse_event","lost_followup","withdrawal","protocol_deviation","followup_completed"].map(k=><option key={k} value={k}>{k.replaceAll("_"," ")}</option>)}</select></label><label className="field">Severity<select value={event.severity} onChange={e=>setEvent({...event,severity:e.target.value})}>{["mild","moderate","severe","not_applicable"].map(k=><option key={k}>{k}</option>)}</select></label></div><label className="field">Description<textarea required minLength={10} value={event.description} onChange={e=>setEvent({...event,description:e.target.value})} /></label><button className="btn btn-primary" disabled={busy}>Record event</button></form></details>
  </section>;
}
