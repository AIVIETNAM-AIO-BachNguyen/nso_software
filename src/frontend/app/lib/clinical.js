export const today = () => new Intl.DateTimeFormat("en-CA", {year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
export const EMPTY_FOLLOWUP = {baselineOd:"",followupOd:"",baselineOs:"",followupOs:"",baselineOdSphere:"",currentOdSphere:"",baselineOsSphere:"",currentOsSphere:"",interval:6,baselineComfort:"",currentComfort:"",stress:"",wear:"",compliance:"Unknown",baselineDate:"",followupDate:"",baselineCsf:"",currentCsf:"",adverseEvent:"",intolerance:""};
export function blankProfile(example) { return Object.fromEntries(Object.entries(example).map(([k,v])=>[k, typeof v === "number" ? "" : v])); }
export function baselineFrom(profile, date) { return {...EMPTY_FOLLOWUP, baselineOd:profile.odAl, baselineOs:profile.osAl, baselineOdSphere:profile.odSphere, baselineOsSphere:profile.osSphere,baselineDate:date}; }
export function clinicalError(error) { return error instanceof TypeError ? "Connection interrupted. Your entries are still here. Check the connection and try again." : error.message; }
export async function checkedJson(response) {
  let data;
  try { data = await response.json(); } catch { throw new Error(response.status >= 500 ? "The assessment service could not complete this request. Your entries are preserved. Please try again or contact your administrator." : "The service returned an unreadable response. Please try again."); }
  if (!response.ok) { const d=data.detail; throw new Error(Array.isArray(d) ? d.map(x=>`${x.loc.slice(1).join(" · ")}: ${x.msg}`).join("; ") : d?.message || (typeof d === "string" ? d : `Request could not be completed (${response.status}). Please review your entries and try again.`)); }
  return data;
}
