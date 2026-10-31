"use client";
const OPTIONS={
  decision:["approve","reject"], mode:["synthetic_rehearsal","measured_research"],
  arm:["SA_ONLY","SA_BN","SA_BN_FIBER"], observed_arm:["SA_ONLY","SA_BN","SA_BN_FIBER"],
  evidence_kind:["synthetic","measured"], assignment:["observational","randomized"],
  eye:["OD","OS"], al_status:["measured","imputed","missing"], se_status:["measured","imputed","missing"],
};
const title = key => key.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
export function emptyTemplate(value) {
  if(Array.isArray(value)) return value.map(emptyTemplate);
  if(value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k,v])=>[k, k.endsWith("_at") || k.endsWith("_date") ? "" : emptyTemplate(v)]));
  if(value === "synthetic_rehearsal") return value;
  if(typeof value === "string" && (/REPLACE|SYNTHETIC|Synthetic|synthetic/i.test(value))) return "";
  return value;
}
export default function RecordFields({ value, onChange, path="", locked=[], schema=value }) {
  return <div className="record-fields">{Object.entries(value).map(([key,item])=>{
    const numberField=typeof schema[key] === "number";
    const label=title(key), id=`record-${path}-${key}`;
    if(!path && locked.includes(key)) return <p className="note" key={key}>{label}: {String(item)}</p>;
    const change=v=>onChange({...value,[key]:v});
    const update=e=>change(numberField ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value || (item===null?null:""));
    if(item && typeof item === "object") return <fieldset key={key}><legend>{label}</legend>{Array.isArray(item) ? <>{item.map((row,i)=><div className="record-array" key={i}>{typeof row === "object" ? <RecordFields value={row} onChange={v=>change(item.map((r,j)=>j===i?v:r))} path={`${path}-${key}-${i}`} locked={locked} schema={schema[key]?.[0] || row}/> : <label className="field">{label} {i+1}<input required value={row} onChange={e=>change(item.map((r,j)=>j===i?e.target.value:r))}/></label>}<button type="button" className="crumb" onClick={()=>change(item.filter((_,j)=>j!==i))}>Remove row</button></div>)}<button type="button" className="btn btn-ghost" onClick={()=>change([...item,schema[key]?.[0] !== undefined ? emptyTemplate(schema[key][0]) : ""])}>Add row</button></> : <RecordFields value={item} onChange={change} path={`${path}-${key}`} locked={locked} schema={schema[key] || item}/>}</fieldset>;
    if(OPTIONS[key]) return <label key={key} className="field" htmlFor={id}>{label}<select id={id} required value={item ?? ""} onChange={e=>change(e.target.value)}><option value="">Choose {label.toLowerCase()}</option>{OPTIONS[key].map(v=><option key={v} value={v}>{title(v)}</option>)}</select></label>;
    return <label key={key} className="field" htmlFor={id}>{label}{typeof item === "boolean" ? <input id={id} type="checkbox" checked={item} onChange={e=>change(e.target.checked)}/> : <input id={id} required={item !== null} type={numberField ? "number" : key.endsWith("_at") || key.endsWith("_date") ? "date" : "text"} step="any" value={item ?? ""} placeholder={item===null ? "Optional" : undefined} onInput={update} onChange={update}/>}</label>;
  })}</div>;
}
