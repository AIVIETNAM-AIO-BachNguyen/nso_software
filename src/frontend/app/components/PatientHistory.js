"use client";
import {useEffect,useState} from "react";
import {checkedJson,clinicalError} from "../lib/clinical";
const API=process.env.NEXT_PUBLIC_API_BASE || "/backend";
export default function PatientHistory({patient,session}) {
  const [state,setState]=useState({loading:true,rows:[],error:""});
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    const get=path=>fetch(`${API}/api/v3${path}`,{headers:{Authorization:`Bearer ${session}`},cache:"no-store",signal:controller.signal}).then(checkedJson);
    setState({loading:true,rows:[],error:""});
    (async()=>{
      const data=await get('/cases');
      const cases=data.cases.filter(c=>c.patient_id===patient);
      const records=await Promise.all(cases.map(async c=>{
        const eyes=await Promise.all(['OD','OS'].map(async eye=>{
          const measurements=await get(`/cases/${encodeURIComponent(c.case_id)}/observations?eye=${eye}`);
          return {eye,...measurements};
        }));
        return {caseId:c.case_id,eyes};
      }));
      if(!controller.signal.aborted)setState({loading:false,error:"",rows:records.flatMap(c=>c.eyes.flatMap(e=>e.observations.map(o=>({...o,eye:e.eye,caseId:c.caseId}))))});
    })().catch(e=>{if(!controller.signal.aborted)setState({loading:false,rows:[],error:clinicalError(e)});});
    return ()=>controller.abort();
  },[patient,session,attempt]);
  return <details className="card patient-history"><summary>Patient history <span className="note">· recorded measurements</span></summary>{state.loading ? <p role="status">Loading recorded visits…</p> : state.error ? <div role="alert"><p>{state.error}</p><button className="btn btn-ghost" onClick={()=>setAttempt(n=>n+1)}>Retry history</button></div> : state.rows.length ? <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Visit</th><th>Eye</th><th>AL (mm)</th><th>SE (D)</th><th>Provenance</th></tr></thead><tbody>{state.rows.sort((a,b)=>b.visit_at.localeCompare(a.visit_at)).map((r,i)=><tr key={i}><td>{r.visit_at}</td><td>{r.eye}</td><td>{r.al_mm ?? "Not recorded"}</td><td>{r.se_d ?? "Not recorded"}</td><td>{r.al_status} / {r.se_status}</td></tr>)}</tbody></table></div> : <p className="research-copy">No recorded visits for this patient. Enter the measurements for this assessment below.</p>}<p className="note">Historical SE is not a sphere/cylinder prescription. New assessment fields require verification.</p></details>;
}
