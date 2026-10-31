"use client";

import { checkedJson, clinicalError } from "../lib/clinical";
import { useEffect, useRef, useState } from "react";
import Demonstrations, { OpticalResults } from "./Demonstrations";
import StudyRecords from "./StudyRecords";
import ModelWorkbench from "./ModelWorkbench";
import ExtensionWorkbench from "./ExtensionWorkbench";
import OpticalWorkbench from "./OpticalWorkbench";

const API = process.env.NEXT_PUBLIC_API_BASE || "/backend";
const ARMS = [["NONE", "No intervention"], ["SA_ONLY", "SA only"], ["SA_BN", "SA + Blue Noise"], ["SA_BN_FIBER", "SA + Blue Noise + Fiber"], ["OTHER", "Other intervention"]];
const numberOrNull = (v) => v === "" ? null : Number(v);
const format = (v, digits = 3) => v == null ? "Unavailable" : Number(v).toFixed(digits);
const emptyObservation = { visit_at: "", se_d: "", al_mm: "", se_status: "measured", al_status: "measured", measurement_method: "", source: "" };

function observationPayload(form) {
  const se = numberOrNull(form.se_d), al = numberOrNull(form.al_mm);
  return { ...form, se_d: se, al_mm: al, se_status: se == null ? "missing" : form.se_status,
    al_status: al == null ? "missing" : form.al_status, quality_flag: "ACCEPTED" };
}

export default function ResearchPage() {
  const [tab, setTab] = useState("forecast");
  const [mode, setMode] = useState("demo");
  const [token, setToken] = useState("");
  const [session, setSession] = useState("");
  const [sessionInfo, setSessionInfo] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [indexAge,setIndexAge] = useState("");
  const [cases, setCases] = useState([]);
  const [caseId, setCaseId] = useState("");
  const [eye, setEye] = useState("OD");
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [model, setModel] = useState("npm-history-linear-v1");
  const [indexDate, setIndexDate] = useState("2026-01-01");
  const [untreated, setUntreated] = useState(false);
  const [forecast, setForecast] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [obs, setObs] = useState(emptyObservation);
  const [follow, setFollow] = useState(emptyObservation);
  const [outcome, setOutcome] = useState(null);
  const [exposure, setExposure] = useState({ arm: "NONE", start_at: "", end_at: "", adherence: "" });
  const [cohort, setCohort] = useState({ protocol_id: "", cohort_name: "", eligibility_version: "", assignment: "observational", comparator: "NONE", intervention: "SA_ONLY", index_date: "", analysis_plan: "" });
  const [members, setMembers] = useState([]);
  const [armReport, setArmReport] = useState(null);
  const [adjustedReport, setAdjustedReport] = useState(null);
  const [envelope, setEnvelope] = useState("");
  const [job, setJob] = useState(null);
  const revision = useRef(0);
  const historyRequest = useRef(0);
  const selected = cases.find(c => c.case_id === caseId);
  const scope = selected ? { patient_id: selected.patient_id, case_id: caseId, eye } : null;
  const currentScope = useRef("");
  currentScope.current = caseId+"|"+eye;
  const connected = mode === "live" && !!session;

  async function api(path, body, credential = session, signal) {
    const response = await fetch(`${API}/api/v3${path}`, {
      method: body === undefined ? "GET" : "POST", cache: "no-store", signal,
      headers: { "Content-Type": "application/json", ...(credential ? { Authorization: `Bearer ${credential}` } : {}),
        ...(body === undefined ? {} : { "Idempotency-Key": crypto.randomUUID() }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if(response.status === 401) disconnect();
    const data = await checkedJson(response);
    return data;
  }

  useEffect(() => {
    const controller = new AbortController();
    api("/health", undefined, "", controller.signal).then(setHealth).catch(e => { if (e.name !== "AbortError") setError("Research API is unavailable. Start or configure the backend to run this workspace."); });
    return () => controller.abort();
    // The public service state does not depend on a research credential.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    revision.current += 1;
    setForecast(null); setOutcome(null); setHistory([]); setJob(null); setUntreated(false);setIndexAge("");setObs(emptyObservation);setFollow(emptyObservation);
    const id = ++historyRequest.current;
    const controller = new AbortController();
    if (!connected || !caseId) { setHistoryLoading(false); return () => controller.abort(); }
    setHistoryLoading(true);
    api(`/cases/${encodeURIComponent(caseId)}/observations?eye=${eye}`, undefined, session, controller.signal)
      .then(data => { if (id === historyRequest.current) { setHistory(data.observations); setIndexDate(data.observations.at(-1)?.visit_at || ""); } })
      .catch(e => { if (e.name !== "AbortError" && id === historyRequest.current) setError(clinicalError(e)); })
      .finally(() => { if (id === historyRequest.current) setHistoryLoading(false); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, caseId, eye, session]);

  function invalidate() { revision.current += 1; setForecast(null); setOutcome(null); }

  useEffect(() => {
    if (!session) return;
    let timeout;
    const renew = () => { clearTimeout(timeout); timeout = setTimeout(disconnect, 15 * 60 * 1000); };
    renew();
    window.addEventListener("pointerdown", renew); window.addEventListener("keydown", renew);
    return () => { clearTimeout(timeout); window.removeEventListener("pointerdown", renew); window.removeEventListener("keydown", renew); };
    // Session credentials stay in memory and clear after 15 minutes of inactivity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function action(fn) {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(clinicalError(e)); } finally { setBusy(false); }
  }

  function connect(e) {
    e.preventDefault();
    action(async () => {
      const data = await api("/cases", undefined, token);
      const info = await api("/session",undefined,token);
      const deployed = await api("/models/available",undefined,token);
      setSessionInfo(info);setAvailableModels(deployed.models.filter(m=>m.active));
      setCases(data.cases); setSession(token); setToken(""); setCaseId(data.cases[0]?.case_id || "");
    });
  }

  function disconnect() {
    revision.current += 1; historyRequest.current += 1;
    setSession(""); setSessionInfo(null);setAvailableModels([]);setModel("npm-history-linear-v1");setToken(""); setCases([]); setCaseId(""); setHistory([]);
    setForecast(null); setOutcome(null); setArmReport(null); setAdjustedReport(null); setJob(null); setMembers([]);
    setObs(emptyObservation); setFollow(emptyObservation); setError("");
  }

  async function runForecast() {
    const id = revision.current;
    const result = mode === "demo" ? await api("/demo/npm", { eye, model_id: model }, "")
      : await api("/npm/predict", { ...scope, index_date: indexDate, index_age:indexAge===""?null:Number(indexAge),model_id: model, horizons_months: [6, 12, 24], untreated_history_confirmed: untreated });
    if (id !== revision.current) return;
    setForecast(result); setOutcome(null);
    if (result.synthetic) setHistory(result.observations);
  }

  async function saveObservation(e) {
    e.preventDefault();
    action(async () => {
      await api("/observations", { ...scope, observations: [observationPayload(obs)] });
      const data = await api(`/cases/${encodeURIComponent(caseId)}/observations?eye=${eye}`);
      invalidate(); setHistory(data.observations); setObs(emptyObservation);
    });
  }

  async function runCohort(e) {
    e.preventDefault();
    action(async () => {
      const frozen = await api("/ipm/cohorts", { ...cohort, protocol_id: cohort.protocol_id || null, horizon_months: 12, visit_window_days: 30,
        members: cases.filter(c => members.includes(c.case_id)).map(c => ({ patient_id: c.patient_id, case_id: c.case_id, eye })) });
      const report = await api("/ipm/estimate", { cohort_id: frozen.cohort_id });
      setArmReport({ ...report, protocol_id: cohort.protocol_id, assignment: cohort.assignment }); setAdjustedReport(null);
    });
  }

  function downloadResult(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
  }

  return <main className="wrap research-wrap">
    <header className="topbar research-local-header">
      <div className="brand"><span className="brand-mark" /><span className="brand-name">NSO AI-PC</span><span className="brand-ver">V3 research workspace</span></div>
      <a className="crumb" href="/">← Clinical fitting</a>
    </header>
    <div className="research-heading"><h1 className="title">Research workspace</h1>
      <p className="sub">Records, analysis and controlled research workflows.</p>
    </div>
    <div className="research-toolbar"><div className="research-mode" aria-label="Data source">
      <button className={`btn ${mode === "demo" ? "btn-primary" : "btn-ghost"}`} disabled={busy} onClick={() => { disconnect(); setMode("demo"); setIndexDate("2026-01-01"); }}>Synthetic demonstration</button>
      <button className={`btn ${mode === "live" ? "btn-primary" : "btn-ghost"}`} disabled={busy} onClick={() => { disconnect(); setMode("live"); }}>Authorized research data</button>
      <span className="note">{mode === "demo" ? "Synthetic data · unsaved results" : "Assigned patients only."}</span>
    </div>
    <div className="research-controls">
      <label className="field">Eye<select aria-label="Eye" value={eye} disabled={busy} onChange={e => { invalidate(); setEye(e.target.value); }}><option>OD</option><option>OS</option></select></label>
    </div>
    </div>
    {mode === "live" && !session && <form className="card research-session" onSubmit={connect}>
      <label className="field">Research session credential<input aria-label="Research session credential" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required /></label>
      <button className="btn btn-primary" disabled={busy || !token}>Connect</button>
      <span className="note">Use the access code provided for your study.</span>
    </form>}
    {connected && <section className="research-session card">
      <label className="field">Case<select aria-label="Research case" value={caseId} disabled={busy} onChange={e => setCaseId(e.target.value)}>{cases.length === 0 && <option value="">No assigned cases</option>}{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.patient_id} · {c.case_id}</option>)}</select></label>
      <button className="btn btn-ghost" disabled={busy} onClick={disconnect}>Disconnect</button>
    </section>}
    {error && <p className="err" role="alert">{error}</p>}
    <nav className="research-tabs" aria-label="Research modules">{[["forecast", "Patient forecasts"], ["records", "Study records"], ["cohort", "Study analysis"], ["optics", "Optical design"], ["models", "Model governance"], ["manufacturing", "Manufacturing"], ["adaptive", "Shadow research"]].map(([key, label]) =>
      <button key={key} aria-current={tab === key ? "page" : undefined} className={tab === key ? "active" : ""} disabled={busy} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {!["forecast","cohort","optics"].includes(tab) && !connected && <section className="card empty-state"><p className="eyebrow">AUTHORIZED WORKSPACE</p><h2>Connect to continue</h2><p>Choose authorized research data above and connect with your study access code. This area uses assigned records and role-based permissions.</p></section>}


    {tab === "forecast" && <>
      <section className="card research-section"><div className="research-section-head"><h2>Natural progression research forecasts</h2><span className="research-state">{health?.features?.npm_enabled ? "Research enabled" : "Demo available · patient forecasts disabled"}</span></div>
        <p className="research-copy">Choose a baseline or an approved model to forecast SE and axial length.</p>
        <div className="grid2">
          <label className="field">Forecast model<select aria-label="Baseline model" value={model} disabled={busy} onChange={e => { invalidate(); setModel(e.target.value); }}><option value="npm-history-linear-v1">Historical linear trend · 2+ measured visits</option><option value="npm-carry-forward-v1">Last measured value · 1+ measured visit</option>{availableModels.map(m=><option key={m.model_id} value={m.model_id}>Approved research model · {m.model_id}</option>)}</select></label>
          <label className="field">Frozen index date<input type="date" aria-label="Frozen index date" required value={indexDate} disabled={mode === "demo" || busy} onChange={e => { invalidate(); setIndexDate(e.target.value); }} /></label>
        </div>
        {connected && <label className="field">Age at index · required for trained population models<input type="number" min="3" max="100" step=".1" value={indexAge} onChange={e=>{invalidate();setIndexAge(e.target.value);}} /></label>}
        {connected && <button className="btn btn-ghost" disabled={busy} onClick={()=>action(async()=>{const data=await api("/models/available");setAvailableModels(data.models.filter(m=>m.active));})}>Refresh approved research models</button>}
        {connected && <label className="research-check"><input type="checkbox" checked={untreated} disabled={busy} onChange={e => { invalidate(); setUntreated(e.target.checked); }} />I have confirmed that the input history is untreated. Recorded treatment exposures are checked separately.</label>}
        <div className="research-actions"><button className="btn btn-primary" disabled={busy || historyLoading || (mode === "live" && (!scope || !untreated || !indexDate || !health?.features?.npm_enabled))} onClick={() => action(runForecast)}>{busy ? "Working…" : mode === "demo" ? "Run synthetic forecast" : "Run research forecast"}</button>{forecast && <button className="btn btn-ghost" onClick={() => downloadResult(forecast, "nso-research-forecast.json")}>Export result</button>}</div>
      </section>

      <section className="card research-section"><h2>{mode === "demo" ? "Synthetic visit history" : "Recorded visit history"}</h2>
        {historyLoading ? <p role="status">Loading eye history…</p> : history.length ? <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Visit date</th><th>SE (D)</th><th>AL (mm)</th><th>Provenance</th><th>Quality</th></tr></thead><tbody>{history.map(r => <tr key={r.visit_at}><td>{r.visit_at}</td><td>{format(r.se_d, 2)}</td><td>{format(r.al_mm)}</td><td>SE: {r.se_status} · AL: {r.al_status}</td><td>{r.quality_flag}</td></tr>)}</tbody></table></div>
          : <p className="note">{mode === "demo" ? "Run the demonstration to inspect its invented longitudinal records." : "Connect and select a case to read existing V2 measurements or add explicit research observations."}</p>}
        {connected && scope && <details className="research-details"><summary>Add a dated observation</summary><form onSubmit={saveObservation}><ObservationFields value={obs} setValue={setObs} />
          <button className="btn btn-primary" disabled={busy || historyLoading}>Save observation</button><p className="note">Missing values stay missing. Imputed values are retained with their label and excluded from primary baseline calculations.</p></form></details>}
      </section>

      {forecast && <section className="card research-section" aria-live="polite"><div className="research-section-head"><h2>{forecast.synthetic ? "Synthetic baseline results" : "Research baseline results"}</h2><span className="research-state">Unvalidated · {eye}</span></div>
      <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Horizon</th><th>Target date</th><th>SE (D)</th><th>AL (mm)</th><th>Δ AL (mm)</th><th>AL prediction interval</th></tr></thead><tbody>{forecast.forecasts.map(r => <tr key={r.horizon_months}><td>{r.horizon_months} months</td><td>{r.target_at}</td><td>{format(r.se_d, 2)}</td><td>{format(r.al_mm)}</td><td>{format(r.delta_al_mm)}</td><td>{r.al_interval?.map(v=>format(v)).join(" to ") || "Unavailable"}</td></tr>)}</tbody></table></div>
        {forecast.forecasts.some(r => r.applicability_flags.length) && <p className="research-copy">Applicability: {[...new Set(forecast.forecasts.flatMap(r => r.applicability_flags))].join(", ")}</p>}
        <p className="note">Changes refer to the last accepted measured value for each endpoint. Calendar target dates use actual elapsed days. This extrapolation is a research comparator, not a calibrated patient prognosis.</p>
        <dl className="research-metadata"><dt>Model</dt><dd>{forecast.model_id}</dd><dt>Prediction</dt><dd>{forecast.prediction_id}</dd><dt>Data hash</dt><dd>{forecast.dataset_hash}</dd></dl>
        {!forecast.synthetic && <details className="research-details"><summary>Evaluate a measured follow-up</summary><form onSubmit={e => { e.preventDefault(); action(async () => setOutcome(await api("/outcomes/evaluate", { prediction_id: forecast.prediction_id, observation: observationPayload(follow) }))); }}><ObservationFields value={follow} setValue={setFollow} />
          <button className="btn btn-primary" disabled={busy}>Evaluate follow-up</button></form></details>}
        {outcome && <div aria-live="polite"><h3>Observed follow-up · {outcome.elapsed_days} days after index</h3><p className="research-copy">AL change: {format(outcome.metrics.al.observed_change)} mm · residual: {format(outcome.metrics.al.residual_observed_minus_predicted)} mm. Only accepted measured endpoints contribute. Predictions are recalculated at the actual follow-up date.</p></div>}
      </section>}
      {connected && scope && <section className="card research-section"><h2>Time-indexed treatment exposure</h2><p className="research-copy">Record the actual dispensed arm before freezing an intervention cohort. Overlapping intervals are rejected.</p>
        <form onSubmit={e => { e.preventDefault(); action(async () => { await api("/exposures", { ...scope, ...exposure, end_at: exposure.end_at || null, adherence: numberOrNull(exposure.adherence) }); invalidate(); setExposure({ arm: "NONE", start_at: "", end_at: "", adherence: "" }); }); }}>
          <div className="grid2"><ArmField label="Actual treatment arm" value={exposure.arm} onChange={v => setExposure({ ...exposure, arm: v })} />
            <label className="field">Start date<input type="date" required value={exposure.start_at} onChange={e => setExposure({ ...exposure, start_at: e.target.value })} /></label>
            <label className="field">End date · optional<input type="date" value={exposure.end_at} onChange={e => setExposure({ ...exposure, end_at: e.target.value })} /></label>
            <label className="field">Adherence · fraction 0–1, optional<input type="number" min="0" max="1" step="0.01" value={exposure.adherence} onChange={e => setExposure({ ...exposure, adherence: e.target.value })} /></label></div>
          <button className="btn btn-primary" disabled={busy}>Save exposure</button></form>
      </section>}
    </>}

    {tab === "cohort" && <section className="card research-section"><div className="research-section-head"><h2>Compare study groups</h2><span className="research-state">Research analysis · locked protocol required</span></div>
      <p className="research-copy">Compare measured axial-length change at 12 months using a frozen cohort and analysis plan.</p>
      {mode === "demo" && <Demonstrations kind="cohort" />}
      {connected && <form onSubmit={runCohort}><div className="grid2">
        <label className="field">Registered protocol ID · needed for adjusted analysis<input type="text" value={cohort.protocol_id} onChange={e=>setCohort({...cohort,protocol_id:e.target.value})} /></label>
        {[['cohort_name', 'Cohort name'], ['eligibility_version', 'Eligibility protocol version']].map(([k, label]) => <label className="field" key={k}>{label}<input type="text" required value={cohort[k]} onChange={e => setCohort({ ...cohort, [k]: e.target.value })} /></label>)}
        <ArmField label="Comparator" value={cohort.comparator} onChange={v => setCohort({ ...cohort, comparator: v })} /><ArmField label="Intervention" value={cohort.intervention} onChange={v => setCohort({ ...cohort, intervention: v })} />
        <label className="field">Baseline index date<input type="date" required value={cohort.index_date} onChange={e => setCohort({ ...cohort, index_date: e.target.value })} /></label>
        <label className="field">Assignment recorded in protocol<select value={cohort.assignment} onChange={e => setCohort({ ...cohort, assignment: e.target.value })}><option value="observational">Observational</option><option value="randomized">Randomized · requires independent verification</option></select></label>
      </div><label className="field research-plan">Locked analysis plan<textarea required minLength={10} maxLength={4000} rows={4} value={cohort.analysis_plan} onChange={e => setCohort({ ...cohort, analysis_plan: e.target.value })} /></label>
        <fieldset className="research-members"><legend>Include cases · selected eye {eye}</legend>{cases.map(c => <label className="research-check" key={c.case_id}><input type="checkbox" checked={members.includes(c.case_id)} onChange={e => setMembers(e.target.checked ? [...members, c.case_id] : members.filter(id => id !== c.case_id))} />{c.patient_id} · {c.case_id}</label>)}</fieldset>
        <p className="note">Follow-up window: 12 calendar months ±30 days. Missing measurements, switching and discontinuation are counted as exclusions; these summaries do not resolve their bias.</p>
        <button className="btn btn-primary" disabled={busy || members.length < 2 || cohort.comparator === cohort.intervention || !health?.features?.ipm_research_enabled}>Freeze cohort & generate report</button>
      </form>}
      {armReport && <div aria-live="polite"><h3>Frozen cohort report</h3><div className="research-table-scroll"><table className="research-table"><thead><tr><th>Arm</th><th>Patients</th><th>Eyes</th><th>Mean observed Δ AL (mm)</th></tr></thead><tbody>{armReport.groups.map(g => <tr key={g.arm}><td>{ARMS.find(a => a[0] === g.arm)?.[1]}</td><td>{g.patients}</td><td>{g.eyes}</td><td>{format(g.mean_observed_delta_al_mm)}</td></tr>)}</tbody></table></div><p className="note">Excluded eyes: {armReport.excluded_eyes}. These unadjusted summaries do not identify individual benefit.</p><div className="research-actions"><button className="btn btn-ghost" onClick={() => downloadResult(armReport, "nso-arm-report.json")}>Export report</button><button className="btn btn-primary" disabled={busy || !armReport.protocol_id} onClick={()=>action(async()=>setAdjustedReport(await api("/ipm/analyze", {cohort_id:armReport.cohort_id,method:armReport.assignment==="randomized"?"randomized_ancova":"observational_aipw",bootstrap_reps:200,seed:17,unmeasured_bias_bound_mm:.1}))) }>Run protocol-based adjusted comparison</button></div></div>}
      {adjustedReport && <div aria-live="polite"><h3>Adjusted research comparison</h3><p className="research-copy">Intervention minus comparator: {format(adjustedReport.effect_mm)} mm. 95% interval: {adjustedReport.interval_95_mm?.map(v=>format(v)).join(" to ") || "Withheld: insufficient overlap"}.</p><p className="note">{adjustedReport.patients} patients · {adjustedReport.method} · {adjustedReport.missing_endpoint_eyes} missing endpoint eyes. Interpretation depends on the locked protocol and its assumptions; assignment has not been independently verified by the software.</p><button className="btn btn-ghost" onClick={()=>downloadResult(adjustedReport,"nso-adjusted-study-report.json")}>Export adjusted report</button></div>}
    </section>}

    {tab === "optics" && <section className="card research-section"><div className="research-section-head"><h2>Optical optimization</h2><span className="research-state">Reference simulator · lens calibration required</span></div>
      <p className="research-copy">Search designs within an engineering envelope and inspect optical performance.</p>
      {mode === "demo" && <Demonstrations kind="optics" />}
      {connected && scope ? <form onSubmit={e => { e.preventDefault(); action(async () => { const submitted = await api("/optimizer/run", { ...scope, envelope_id: envelope, objective_version: "optical-quality-v1", seed: 1, candidate_budget: 32 }); setJob(await api(`/optimizer/${submitted.run_id}`)); }); }}>
        <label className="field">Engineering envelope reference<input type="text" required value={envelope} onChange={e => setEnvelope(e.target.value)} /></label>
        <button className="btn btn-ghost" disabled={busy || !health?.features?.optimizer_enabled}>Run reference optical search</button>
      </form> : <p className="research-empty">An authorized engineering session is required to submit and inspect optimization jobs.</p>}
      {job && <div aria-live="polite"><h3>Job {job.status}</h3><p className="research-copy">{job.message || job.calibration_status || "The asynchronous job is queued."}</p><p className="note">{job.run_id}</p>{job.pareto_candidates?.length > 0 && <OpticalResults candidates={job.pareto_candidates} />}{job.status === "queued" && <button className="btn btn-ghost" disabled={busy} onClick={() => action(async () => setJob(await api(`/optimizer/${job.run_id}`)))}>Refresh job status</button>}</div>}
    </section>}
    {tab === "records" && connected && scope && <StudyRecords key={caseId+"|"+eye} scope={scope} history={history} api={api} onProtocol={id=>setCohort({...cohort,protocol_id:id})} refresh={async()=>{const captured=caseId+"|"+eye;if(currentScope.current!==captured)return;const data=await api(`/cases/${encodeURIComponent(caseId)}/observations?eye=${eye}`);if(currentScope.current===captured){invalidate();setHistory(data.observations);}}} />}
    {tab === "models" && connected && sessionInfo && <ModelWorkbench key={sessionInfo.actor} api={api} roles={sessionInfo.roles} />}
    {tab === "models" && connected && sessionInfo && !sessionInfo.roles.some(r=>["admin","validator","deployer"].includes(r)) && <p className="card research-empty">Your role can use approved models. Model review and deployment require a validator or deployment role.</p>}
    {connected && sessionInfo && tab === "optics" && <OpticalWorkbench key={sessionInfo.actor} api={api} roles={sessionInfo.roles} onEnvelope={setEnvelope} />}
    {mode === "demo" && tab === "forecast" && <section className="card research-section"><Demonstrations kind="training" /></section>}
    {["manufacturing","adaptive"].includes(tab) && connected && scope && sessionInfo && <ExtensionWorkbench workflowGroup={tab} key={tab+"|"+sessionInfo.actor+"|"+caseId+"|"+eye} api={api} roles={sessionInfo.roles} scope={scope} manufacturingEnabled={health?.features?.manufacturing_enabled} adaptiveEnabled={health?.features?.adaptive_shadow_enabled} />}
    <footer className="medical-disclaimer">Research use only · not for clinical or manufacturing decisions.</footer>
  </main>;
}

function ArmField({ label, value, onChange }) {
  return <label className="field">{label}<select value={value} onChange={e => onChange(e.target.value)}>{ARMS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>;
}

function ObservationFields({ value, setValue }) {
  const set = key => e => setValue({ ...value, [key]: e.target.value });
  return <div className="grid2 research-observation-fields">
    <label className="field">Visit date<input type="date" required value={value.visit_at} onChange={set("visit_at")} /></label>
    <label className="field">Measurement method<input type="text" required maxLength={120} placeholder="e.g. optical biometry / subjective refraction" value={value.measurement_method} onChange={set("measurement_method")} /></label>
    <label className="field">SE (D) · optional<input type="number" min="-20" max="15" step="0.01" value={value.se_d} onChange={set("se_d")} /></label>
    <label className="field">AL (mm) · optional<input type="number" min="18" max="35" step="0.001" value={value.al_mm} onChange={set("al_mm")} /></label>
    <label className="field">SE provenance<select value={value.se_status} onChange={set("se_status")}><option value="measured">Measured</option><option value="imputed">Imputed</option></select></label>
    <label className="field">AL provenance<select value={value.al_status} onChange={set("al_status")}><option value="measured">Measured</option><option value="imputed">Imputed</option></select></label>
    <label className="field">Source reference<input type="text" required maxLength={120} value={value.source} onChange={set("source")} /></label>
  </div>;
}
