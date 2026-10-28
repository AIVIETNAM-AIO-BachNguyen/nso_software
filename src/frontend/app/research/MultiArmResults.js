"use client";
const NAMES = { SA_ONLY:"SA only", SA_BN:"SA + Blue Noise", SA_BN_FIBER:"SA + Blue Noise + Fiber" };
export default function MultiArmResults({result}) {
  const synthetic = result.synthetic || result.evidence_kind === "synthetic";
  const complete = result.ranking_complete && ["SA_ONLY","SA_BN","SA_BN_FIBER"].every(arm=>result.arm_support?.[arm]?.supported);
  const ranked = result.status === "abstained" ? [] : (result.candidates || []).filter(c=>result.arm_support?.[c.arm]?.supported && result.arm_support?.[result.comparator]?.supported);
  if (result.arm_support) return <div aria-label="Three-arm support and ranking">
    {synthetic && <p className="note"><strong>Synthetic software fixture · research only</strong></p>}
    <p><strong>{result.status === "abstained" ? "Ranking abstained" : complete ? "Complete three-arm shadow ranking" : "Partial shadow ranking"}</strong></p>
    <p className="note">Common comparator: {NAMES[result.comparator] || result.comparator}. Outcome: 12-month AL change (mm). This does not assign treatment or establish individual causal benefit.</p>
    <table><thead><tr><th>Arm</th><th>Local patients / ESS</th><th>Support</th></tr></thead><tbody>{Object.entries(result.arm_support).map(([arm,s])=><tr key={arm}><td>{NAMES[arm] || arm}</td><td>{s.local_patients} / {s.local_effective_sample_size?.toFixed(1)}</td><td>{s.supported ? "Supported" : s.reason || "Abstained"}</td></tr>)}</tbody></table>
    {ranked.length>0 && <ol>{ranked.map(c=><li key={c.plan_id}>{NAMES[c.arm]} · research difference versus SA only: {c.research_difference_vs_comparator_mm?.toFixed(4)} mm</li>)}</ol>}
    {!complete && <p className="note">An unsupported arm is excluded. This result does not rank all three arms.</p>}
  </div>;
  if (result.kind === "predictive_association_only" || (result.status === "unavailable" && result.causal_design_effects_identified === false)) return <div aria-label="Predictive design-value analysis">
    {synthetic && <p className="note"><strong>Synthetic software fixture · research only</strong></p>}
    <h4>Predictive design-value analysis</h4><p className="note">Predictive association only. Ablation and within-arm permutation do not establish causal effects of design parameters.</p>
    {result.status === "unavailable" ? <p role="alert">Analysis unavailable: {result.reason}</p> : Object.entries(result.report || {}).map(([split,r])=><div key={split}><h4>{split} · {r.patients} independent patients</h4><table><thead><tr><th>Model</th><th>MAE (mm)</th><th>RMSE (mm)</th></tr></thead><tbody>{Object.entries(r.stages).map(([stage,m])=><tr key={stage}><td>{{history:"Patient history",arm:"History + dispensed arm",design:"History + arm + design"}[stage]}</td><td>{m.mae_mm.toFixed(4)}</td><td>{m.rmse_mm.toFixed(4)}</td></tr>)}</tbody></table><p className="note">Paired MSE reduction from adding design: {r.design_increment.mse_reduction_mm2.toFixed(6)} mm². Same patients in all comparisons; preprocessing fitted on training patients.</p></div>)}
  </div>;
  return null;
}
