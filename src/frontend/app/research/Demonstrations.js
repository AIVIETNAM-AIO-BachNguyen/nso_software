"use client";

import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "/backend";
const number = value => value == null ? "Not estimated" : Number(value).toFixed(3);

export default function Demonstrations({ kind }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assignment, setAssignment] = useState("randomized");
  const [seed, setSeed] = useState("17");
  const request = useRef(0);
  const abort = useRef(null);
  useEffect(() => {
    request.current += 1; abort.current?.abort(); setResult(null); setError(""); setBusy(false);
    return () => { request.current += 1; abort.current?.abort(); };
  }, [kind]);

  async function run() {
    const revision = ++request.current;
    abort.current?.abort(); abort.current = new AbortController();
    setBusy(true); setError(""); setResult(null);
    try {
      const path = kind === "cohort" ? "/demo/study" : kind === "optics" ? "/demo/optics" : "/demo/training";
      const response = await fetch(API+"/api/v3"+path, { method: kind === "training" ? "GET" : "POST", cache: "no-store",
        signal: abort.current.signal, headers: { "Content-Type": "application/json" },
        ...(kind === "training" ? {} : { body: JSON.stringify(kind === "cohort" ? { assignment } : { seed: Number(seed) }) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || "The demonstration could not run. Check the local API.");
      if (revision === request.current) setResult(data);
    } catch (e) { if (revision === request.current && e.name !== "AbortError") setError(e.message); }
    finally { if (revision === request.current) setBusy(false); }
  }

  return <section className="research-demo" aria-label="Synthetic demonstration">
    <h3>{kind === "cohort" ? "Try a study with invented patients" : kind === "optics" ? "Try the reference optical search" : "Compare trained model examples"}</h3>
    <p className="research-copy">{kind === "cohort" ? "This example builds a locked cohort, summarizes both arms, and runs a patient-level adjusted analysis. It uses invented observations throughout."
      : kind === "optics" ? "Run a seeded search with a scalar diffraction simulator and an invented manufacturing envelope. Results are reference calculations awaiting measured-lens calibration."
      : "Inspect a precomputed training run for mixed effects, gradient boosting and a small temporal Transformer. Training, calibration, test and external-site patients were separated."}</p>
    <div className="research-actions">
      {kind === "cohort" && <label className="field">Example study<select value={assignment} disabled={busy} onChange={e => { setAssignment(e.target.value); setResult(null); }}><option value="randomized">Randomized fixture · adjusted arm comparison</option><option value="observational">Observational fixture · cross-fitted analysis</option></select></label>}
      {kind === "optics" && <label className="field">Reproducible example<select value={seed} disabled={busy} onChange={e => { setSeed(e.target.value); setResult(null); }}>{[1,17,42].map(n => <option key={n} value={n}>Example {n}</option>)}</select></label>}
      <button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? "Running…" : kind === "cohort" ? "Run sample study" : kind === "optics" ? "Run sample optical search" : "Show synthetic training results"}</button>
    </div>
    {error && <p className="err" role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <p className="research-synthetic-label">SYNTHETIC SOFTWARE EXAMPLE · NOT CLINICAL OR CALIBRATION EVIDENCE</p>
      {kind === "cohort" && <>
        <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Arm</th><th>Patients</th><th>Eyes</th><th>Mean observed Δ AL (mm)</th></tr></thead><tbody>{result.descriptive.groups.map(g => <tr key={g.arm}><td>{g.arm === "NONE" ? "Comparator" : "Intervention"}</td><td>{g.patients}</td><td>{g.eyes}</td><td>{number(g.mean_observed_delta_al_mm)}</td></tr>)}</tbody></table></div>
        <h3>Adjusted comparison in the invented dataset</h3><p className="research-copy">Intervention minus comparator: <strong>{number(result.adjusted.effect_mm)} mm</strong>. 95% interval: {result.adjusted.interval_95_mm?.map(number).join(" to ") || "Not estimated"}.</p>
        <p className="note">{result.adjusted.patients} patients · {result.adjusted.diagnostics.uncertainty_method}. Negative values mean less axial elongation in this invented example. No individual benefit is calculated.</p>
        {result.adjusted.status === "overlap_failed" && <p className="err">The example failed the overlap gate; the effect has been withheld.</p>}
      </>}
      {kind === "optics" && <>
        <p className="research-copy">Evaluated {result.evaluated} candidate designs; rejected {result.rejected}. The {result.candidates.length} non-dominated candidates trade optical quality, glare, robustness and relief constraints.</p>
        <OpticalResults candidates={result.candidates} />
        <p className="note">Reference scalar phase-screen simulation, not a calibrated ophthalmic lens model. These optical scores do not estimate myopia-control efficacy.</p>
      </>}
      {kind === "training" && <>
        <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Algorithm</th><th>Held-out patients</th><th>AL MAE (mm)</th><th>SE MAE (D)</th><th>Calibration patients</th></tr></thead><tbody>{result.models.map(m => <tr key={m.algorithm}><td>{m.algorithm.replaceAll("_", " ")}</td><td>{m.report["split:test"].patients}</td><td>{number(m.report["split:test"].mae_al_se[0])}</td><td>{number(m.report["split:test"].mae_al_se[1])}</td><td>{m.calibration_patients}</td></tr>)}</tbody></table></div>
        <p className="note">Errors describe invented arithmetic fixtures only. The Transformer must outperform simpler comparators under a locked policy before research promotion.</p>
      </>}
    </div>}
  </section>;
}

export function OpticalResults({ candidates }) {
  return <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Research candidate</th><th>Strehl</th><th>MTF at 0.2 cutoff</th><th>Glare energy fraction</th><th>Worst optical quality</th></tr></thead><tbody>{candidates.map(c => <tr key={c.design_id}><td>{c.design_id}</td><td>{number(c.metrics.strehl)}</td><td>{number(c.metrics.mtf_20)}</td><td>{number(c.metrics.glare_fraction)}</td><td>{number(c.worst_quality)}</td></tr>)}</tbody></table></div>;
}
