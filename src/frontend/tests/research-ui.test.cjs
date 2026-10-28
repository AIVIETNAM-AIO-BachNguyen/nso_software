const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");
const React = require("react");
const { create, act } = require("react-test-renderer");
const { buildSync } = require("esbuild");

// Component tests, not browser automation. Bundle local JSX in memory; React
// stays external so the renderer and components share the same hooks runtime.
function component(filename) {
  const entry = path.resolve(__dirname, "../app/research/", filename);
  const result = buildSync({ entryPoints: [entry], bundle: true, write: false,
    format: "cjs", platform: "node", jsx: "automatic", loader: { ".js": "jsx" }, external: ["react", "react/jsx-runtime"], logLevel: "silent" });
  const loaded = new Module(entry, module);
  loaded.filename = entry;
  loaded.paths = Module._nodeModulePaths(path.dirname(entry));
  loaded._compile(result.outputFiles[0].text, entry);
  return loaded.exports.default;
}
const Demonstrations = component("Demonstrations.js");
const StudyRecords = component("StudyRecords.js");
const ModelWorkbench = component("ModelWorkbench.js");
const OpticalWorkbench = component("OpticalWorkbench.js");
const flush = () => new Promise(resolve => setImmediate(resolve));
const event = { preventDefault() {} };
const text = renderer => JSON.stringify(renderer.toJSON());
const button = (renderer, title) => renderer.root.findAllByType("button").find(b => b.children.includes(title));
function label(renderer, title, type = "input") {
  return renderer.root.findAllByType("label").find(l => l.children.some(c => typeof c === "string" && c.startsWith(title))).findByType(type);
}

test("study demo renders an invented adjusted result and never sends patient data", async () => {
  const calls = [];
  const original = global.fetch;
  global.fetch = async (url, options) => { calls.push([url, options]); return { ok: true, json: async () => ({ synthetic: true,
    descriptive: { groups: [{ arm: "NONE", patients: 20, eyes: 40, mean_observed_delta_al_mm: .3 }] },
    adjusted: { patients: 40, effect_mm: -.12, interval_95_mm: [-.14, -.1], status: "research_estimate",
      diagnostics: { uncertainty_method: "patient-level test fixture" } } }) }; };
  let renderer;
  try {
    act(() => { renderer = create(React.createElement(Demonstrations, { kind: "cohort" })); });
    await act(async () => { await button(renderer, "Run sample study").props.onClick(); });
    assert.deepEqual(JSON.parse(calls[0][1].body), { assignment: "randomized" });
    assert.equal(calls[0][1].headers.Authorization, undefined);
    assert.match(text(renderer), /SYNTHETIC SOFTWARE EXAMPLE/);
    assert.match(text(renderer), /-0.120/);
  } finally { if (renderer) act(() => renderer.unmount()); global.fetch = original; }
});

test("switching demo module discards a late response and aborts the prior request", async () => {
  let complete;
  const original = global.fetch;
  let signal;
  global.fetch = (url, options) => { signal = options.signal; return new Promise(resolve => { complete = resolve; }); };
  let renderer, pending;
  try {
    act(() => { renderer = create(React.createElement(Demonstrations, { kind: "cohort" })); });
    act(() => { pending = button(renderer, "Run sample study").props.onClick(); });
    act(() => renderer.update(React.createElement(Demonstrations, { kind: "optics" })));
    assert.equal(signal.aborted, true);
    await act(async () => { complete({ ok: true, json: async () => ({ oldResult: true }) }); await pending; });
    assert.doesNotMatch(text(renderer), /oldResult/);
    assert.equal(button(renderer, "Run sample optical search").props.disabled, false);
  } finally { if (renderer) act(() => renderer.unmount()); global.fetch = original; }
});

test("demo API errors are visible and the run button becomes usable again", async () => {
  const original = global.fetch;
  global.fetch = async () => ({ ok: false, json: async () => ({ detail: { message: "Fixture service unavailable" } }) });
  let renderer;
  try {
    act(() => { renderer = create(React.createElement(Demonstrations, { kind: "optics" })); });
    await act(async () => { await button(renderer, "Run sample optical search").props.onClick(); });
    assert.match(text(renderer), /Fixture service unavailable/);
    assert.equal(button(renderer, "Run sample optical search").props.disabled, false);
    assert.equal(renderer.root.findByProps({ role: "alert" }).children[0], "Fixture service unavailable");
  } finally { if (renderer) act(() => renderer.unmount()); global.fetch = original; }
});

test("observation import binds the selected case/eye, ignoring identity in uploaded JSON", async () => {
  const calls = [];
  let refreshed = 0, renderer;
  const api = async (route, body) => { calls.push([route, body]); return {}; };
  try {
    act(() => { renderer = create(React.createElement(StudyRecords, { scope: { patient_id: "P", case_id: "C", eye: "OS" },
      history: [], api, refresh: async () => { refreshed++; }, onProtocol() {} })); });
    const rows = [{ visit_at: "2026-01-01", al_mm: 24, al_status: "measured" }];
    const file = { text: async () => JSON.stringify({ patient_id: "WRONG", case_id: "WRONG", eye: "OD", observations: rows }) };
    act(() => { renderer.root.findByProps({ "aria-label": "Observation JSON file" }).props.onChange({ target: { files: [file] } }); });
    await act(async () => { renderer.root.findAllByType("form")[0].props.onSubmit(event); await flush(); });
    assert.equal(calls[0][0], "/observations");
    assert.deepEqual(calls[0][1], { patient_id: "P", case_id: "C", eye: "OS", observations: rows });
    assert.equal(refreshed, 1);
    assert.match(text(renderer), /Every row passed validation/);
  } finally { if (renderer) act(() => renderer.unmount()); }
});

test("correction sends the expected revision and preserves measured/imputed provenance", async () => {
  let request, renderer;
  const history = [{ record_id: "OBS", revision: 2, visit_at: "2026-01-01", al_mm: 24, se_d: -2,
    al_status: "imputed", se_status: "measured", measurement_method: "fixture", source: "fixture", quality_flag: "ACCEPTED" }];
  try {
    act(() => { renderer = create(React.createElement(StudyRecords, { scope: { patient_id: "P", case_id: "C", eye: "OD" }, history,
      api: async (route, body) => { request = [route, body]; return {}; }, refresh: async () => {}, onProtocol() {} })); });
    act(() => label(renderer, "Observation", "select").props.onChange({ target: { value: "OBS" } }));
    act(() => label(renderer, "Reason for correction", "textarea").props.onChange({ target: { value: "Correct a synthetic transcription" } }));
    await act(async () => { renderer.root.findAllByType("form")[1].props.onSubmit(event); await flush(); });
    assert.equal(request[0], "/observations/correct");
    assert.equal(request[1].expected_revision, 2);
    assert.equal(request[1].replacement.al_status, "imputed");
    assert.equal(request[1].replacement.se_status, "measured");
  } finally { if (renderer) act(() => renderer.unmount()); }
});

test("workbenches hide review/deployment controls from researcher-only sessions", () => {
  let model, optical;
  try {
    act(() => { model = create(React.createElement(ModelWorkbench, { roles: ["researcher"], api() {} }));
      optical = create(React.createElement(OpticalWorkbench, { roles: ["researcher"], api() {} })); });
    assert.equal(model.toJSON(), null);
    assert.equal(optical.toJSON(), null);
  } finally { act(() => { model?.unmount(); optical?.unmount(); }); }
});

test("training upload uses the locked policy and chosen algorithm rather than file overrides", async () => {
  let renderer;
  const calls = [];
  const api = async (route, body) => { calls.push([route, body]); return route.endsWith("policies") ? { record_id: "LOCKED-POLICY" } : { run_id: "JOB", status: "queued" }; };
  try {
    act(() => { renderer = create(React.createElement(ModelWorkbench, { roles: ["validator"], api })); });
    act(() => label(renderer, "Policy name").props.onChange({ target: { value: "Fixture validation policy" } }));
    await act(async () => { renderer.root.findAllByType("form")[0].props.onSubmit(event); await flush(); });
    const file = { text: async () => JSON.stringify({ samples: [], dataset_version: "fixture", algorithm: "WRONG", validation_policy_id: "WRONG" }) };
    act(() => label(renderer, "Approved dataset JSON").props.onChange({ target: { files: [file] } }));
    await act(async () => { renderer.root.findAllByType("form")[1].props.onSubmit(event); await flush(); });
    assert.equal(calls[1][0], "/models/train");
    assert.equal(calls[1][1].algorithm, "gradient_boosting");
    assert.equal(calls[1][1].validation_policy_id, "LOCKED-POLICY");
    assert.match(text(renderer), /Refresh training status/);
  } finally { if (renderer) act(() => renderer.unmount()); }
});

test("engineering result view projects permitted fields and does not display returned parameters", async () => {
  let renderer, selected;
  const body = { name: "Synthetic envelope", bounds: { private_parameter: [.1, .2] } };
  try {
    act(() => { renderer = create(React.createElement(OpticalWorkbench, { roles: ["optical_engineer"],
      api: async () => ({ envelope_id: "ENV", status: "uncalibrated_reference", parameters: "DO_NOT_RENDER_THIS" }),
      onEnvelope: id => { selected = id; } })); });
    act(() => label(renderer, "JSON file").props.onChange({ target: { files: [{ text: async () => JSON.stringify(body) }] } }));
    await act(async () => { renderer.root.findByType("form").props.onSubmit(event); await flush(); });
    assert.equal(selected, "ENV");
    assert.match(text(renderer), /Engineering record saved/);
    assert.doesNotMatch(text(renderer), /DO_NOT_RENDER_THIS/);
  } finally { if (renderer) act(() => renderer.unmount()); }
});

const ExtensionWorkbench = component("ExtensionWorkbench.js");
test("extension workbench gates actions by roles and feature flags", () => {
  let renderer;
  act(() => { renderer = create(React.createElement(ExtensionWorkbench, { api: async () => ({}), roles: ["researcher"], scope: {patient_id:"P",case_id:"C",eye:"OD"}, manufacturingEnabled:false, adaptiveEnabled:false })); });
  assert.match(text(renderer), /disabled by server feature flags/);
  assert.equal(renderer.root.findAllByType("select").length, 0);
  act(() => { renderer.update(React.createElement(ExtensionWorkbench, { api: async () => ({}), roles:["researcher"], scope:{patient_id:"P",case_id:"C",eye:"OD"}, manufacturingEnabled:true, adaptiveEnabled:true })); });
  const options=renderer.root.findAllByType("option").map(o=>o.props.value);
  assert.ok(options.includes("/manufacturing/exposures"));
  assert.ok(!options.includes("/adaptive/deployments"));
  assert.ok(!options.includes("/manufacturing/lots"));
  act(()=>renderer.unmount());
});

test("manufacturing import binds scope and suppresses protected result fields", async () => {
  const calls=[]; let renderer;
  act(() => { renderer=create(React.createElement(ExtensionWorkbench,{api:async(path,body)=>{calls.push([path,body]);return {record_id:"MPL",parameters:{secret:"hidden"},qc_requirements:[{lower:123}]};},roles:["manufacturing_engineer"],scope:{patient_id:"P",case_id:"C",eye:"OD"},manufacturingEnabled:true,adaptiveEnabled:false})); });
  act(()=>{renderer.root.findByProps({type:"file"}).props.onChange({target:{files:[{size:100,text:async()=>JSON.stringify({patient_id:"FOREIGN",case_id:"OTHER",eye:"OS",candidate_id:"CAN"})}]}});});
  await act(async()=>{await renderer.root.findAllByType("form")[0].props.onSubmit(event);});
  assert.deepEqual(calls[0],["/manufacturing/plans",{patient_id:"P",case_id:"C",eye:"OD",candidate_id:"CAN"}]);
  assert.ok(!text(renderer).includes("hidden"));assert.ok(!text(renderer).includes("123"));
  act(()=>renderer.unmount());
});

test("shadow workflow error is visible and can be retried without authorizing manufacturing", async () => {
 let renderer;
 act(()=>{renderer=create(React.createElement(ExtensionWorkbench,{api:async()=>{throw new Error("VALIDATION_GATE_FAILED");},roles:["adaptive_researcher"],scope:{patient_id:"P",case_id:"C",eye:"OD"},manufacturingEnabled:false,adaptiveEnabled:true}));});
 act(()=>{renderer.root.findByProps({type:"file"}).props.onChange({target:{files:[{size:2,text:async()=>"{}"}]}});});
 await act(async()=>{await renderer.root.findAllByType("form")[0].props.onSubmit(event);});
 assert.match(text(renderer),/VALIDATION_GATE_FAILED/);
 assert.equal(button(renderer,"Submit research workflow").props.disabled,false);
 assert.match(text(renderer),/Shadow rankings never authorize treatment or manufacturing/);
 act(()=>renderer.unmount());
});

const MultiArmResults = component("MultiArmResults.js");
test("three-arm view labels partial support and withholds unsupported arm scores", () => {
 const support={SA_ONLY:{supported:true,local_patients:10,local_effective_sample_size:9},SA_BN:{supported:true,local_patients:9,local_effective_sample_size:8},SA_BN_FIBER:{supported:false,local_patients:2,local_effective_sample_size:1.5,reason:"INSUFFICIENT_ARM_SUPPORT"}};
 let renderer;
 act(()=>{renderer=create(React.createElement(MultiArmResults,{result:{status:"partial_shadow_logged",ranking_complete:true,comparator:"SA_ONLY",arm_support:support,candidates:[{plan_id:"A",arm:"SA_BN",research_difference_vs_comparator_mm:-.1},{plan_id:"B",arm:"SA_BN_FIBER",research_difference_vs_comparator_mm:999}]}}));});
 assert.match(text(renderer),/Partial shadow ranking/);assert.ok(!text(renderer).includes("999"));
 assert.match(text(renderer),/INSUFFICIENT_ARM_SUPPORT/);assert.ok(!text(renderer).includes("Complete three-arm"));act(()=>renderer.unmount());
});

test("design-value view shows nested held-out metrics with noncausal interpretation", () => {
 const stages={history:{mae_mm:.2,rmse_mm:.3},arm:{mae_mm:.1,rmse_mm:.2},design:{mae_mm:.05,rmse_mm:.1}};
 let renderer;
 act(()=>{renderer=create(React.createElement(MultiArmResults,{result:{evidence_kind:"synthetic",kind:"predictive_association_only",status:"completed",report:{external:{patients:60,stages,design_increment:{mse_reduction_mm2:.03}}}}}));});
 assert.match(text(renderer),/History \+ dispensed arm/);assert.match(text(renderer),/History \+ arm \+ design/);
 assert.match(text(renderer),/Synthetic software fixture/);assert.match(text(renderer),/do not establish causal effects/);assert.match(text(renderer),/60/);act(()=>renderer.unmount());
});

test("unavailable design evidence does not render fabricated metric tables", () => {
 let renderer;act(()=>{renderer=create(React.createElement(MultiArmResults,{result:{status:"unavailable",causal_design_effects_identified:false,reason:"NO_WITHIN_ARM_PARAMETER_VARIATION"}}));});
 assert.match(text(renderer),/NO_WITHIN_ARM_PARAMETER_VARIATION/);assert.equal(renderer.root.findAllByType("table").length,0);act(()=>renderer.unmount());
});
