const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const Module=require('node:module');
const React=require('react');
const {create,act}=require('react-test-renderer');
const {buildSync}=require('esbuild');
function load(file){const entry=path.resolve(__dirname,'../app',file);const bundle=buildSync({entryPoints:[entry],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',loader:{'.js':'jsx'},external:['react','react/jsx-runtime'],logLevel:'silent'});const m=new Module(entry,module);m.filename=entry;m.paths=Module._nodeModulePaths(path.dirname(entry));m._compile(bundle.outputFiles[0].text,entry);return m.exports;}
const Page=load('page.js').default;
const {baselineFrom,blankProfile,checkedJson}=load('lib/clinical.js');
const fixture=require('./fixtures/clinical-result.json');
const flush=()=>new Promise(r=>setImmediate(r));
const button=(r,name)=>r.root.findAllByType('button').find(b=>b.children.join('')===name);
function field(r,name){const label=r.root.findAllByType('label').find(l=>l.children.some(c=>typeof c==='string' && c===name));return r.root.findAllByType('input').find(i=>i.props.id===label.props.htmlFor);}
const event={preventDefault(){}};
test('baseline uses the confirmed visit and never invents follow-up measurements',()=>{const baseline=baselineFrom({odAl:26.2,osAl:26,odSphere:-5,osSphere:-4.5},'2026-10-30');assert.equal(baseline.baselineOd,26.2);assert.equal(baseline.baselineDate,'2026-10-30');assert.equal(baseline.followupOd,'');assert.equal(baseline.followupDate,'');assert.equal(blankProfile({age:11,npc:9}).age,'');});
test('non-JSON server failures are presented as a recoverable service error',async()=>{await assert.rejects(checkedJson({status:500,ok:false,json:async()=>{throw new SyntaxError('Internal Server Error')}}),/entries are preserved/);});
test('clinical workflow confirms entries, derives follow-up baseline, and never auto-submits edits',async()=>{
 const originalFetch=global.fetch,originalWindow=global.window;const calls=[];let r;
 global.window={addEventListener(){},removeEventListener(){},scrollTo(){},setInterval,clearInterval,setTimeout,clearTimeout};
 global.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>url.endsWith('/health')?{authentication_required:false}:fixture};};
 try{
  await act(async()=>{r=create(React.createElement(Page));await flush();});
  assert.equal(field(r,'Age').props.value,'');
  const values=[11,5.2,-3.25,-.5,180,26.2,-3,-.25,175,26,4,9,1.1,6,7,5,1];
  for(let i=0;i<values.length;i++)act(()=>r.root.findAllByType('input').filter(x=>x.props.type==='number')[i].props.onChange({target:{value:String(values[i])}}));
  act(()=>r.root.findByProps({'aria-label':'Assessment date'}).props.onInput({currentTarget:{value:'2026-01-01'}}));
  act(()=>field(r,'Age').props.onChange({target:{value:'12'}}));
  assert.equal(r.root.findByProps({'aria-label':'Assessment date'}).props.value,'2026-01-01');
  const form=r.root.findAllByType('form').find(f=>f.findAllByType('input').some(i=>i.props.type==='number'));
  act(()=>form.props.onSubmit(event));
  assert.ok(button(r,'Confirm & generate recommendation'));
  assert.equal(calls.filter(([url])=>url.endsWith('/predict')).length,0);
  await act(async()=>{await button(r,'Confirm & generate recommendation').props.onClick();});
  act(()=>button(r,'Track follow-up →').props.onClick());
  assert.equal(field(r,'Baseline date').props.value,'2026-01-01');
  assert.equal(field(r,'OD baseline AL').props.value,'26.2');
  assert.equal(field(r,'OD follow-up AL').props.value,'');
  act(()=>field(r,'OD follow-up AL').props.onChange({target:{value:'26.3'}}));
  assert.equal(calls.filter(([url])=>url.endsWith('/followup')).length,0);
  assert.equal(button(r,'Generate Next Recommendation →').props.disabled,true);
 }finally{if(r)act(()=>r.unmount());global.fetch=originalFetch;global.window=originalWindow;}
});
test('changing a confirmed clinical measurement discards the previous recommendation',async()=>{
 const originalFetch=global.fetch,originalWindow=global.window;let r;
 global.window={addEventListener(){},removeEventListener(){},scrollTo(){},setInterval,clearInterval,setTimeout,clearTimeout};
 global.fetch=async url=>({ok:true,json:async()=>url.endsWith('/health')?{authentication_required:false}:fixture});
 try{
  await act(async()=>{r=create(React.createElement(Page));await flush();});
  const form=r.root.findAllByType('form').find(f=>f.findAllByType('input').some(i=>i.props.type==='number'));
  const values=[11,5.2,-3.25,-.5,180,25.1,-3,-.25,175,24.9,4,9,1.1,6,7,5,1];
  for(let i=0;i<values.length;i++)act(()=>r.root.findAllByType('input').filter(x=>x.props.type==='number')[i].props.onChange({target:{value:String(values[i])}}));
  act(()=>form.props.onSubmit(event));await act(async()=>{await button(r,'Confirm & generate recommendation').props.onClick();});
  act(()=>button(r,'Clinical input').props.onClick());
  act(()=>field(r,'Age').props.onChange({target:{value:'12'}}));
  act(()=>button(r,'Review recommendation').props.onClick());
  assert.ok(button(r,'Review clinical profile'));
  assert.equal(button(r,'Approve Design'),undefined);
 }finally{if(r)act(()=>r.unmount());global.fetch=originalFetch;global.window=originalWindow;}
});
test('refit resets approval and uses the new measured visit as its next baseline',async()=>{
 const originalFetch=global.fetch,originalWindow=global.window;let r;
 global.window={addEventListener(){},removeEventListener(){},scrollTo(){},setInterval,clearInterval,setTimeout,clearTimeout};
 global.fetch=async(url,options)=>({ok:true,json:async()=>url.endsWith('/health')?{authentication_required:false}:url.endsWith('/followup')?require('./fixtures/followup-result.json'):url.endsWith('/approve')?{approved:true}:url.endsWith('/refit')?{...fixture,design_id:'NSO-NEW-VERSION'}:fixture});
 try{
  await act(async()=>{r=create(React.createElement(Page));await flush();});
  const values=[11,5.2,-3.25,-.5,180,25.1,-3,-.25,175,24.9,4,9,1.1,6,7,5,1];
  for(let i=0;i<values.length;i++)act(()=>r.root.findAllByType('input').filter(x=>x.props.type==='number')[i].props.onChange({target:{value:String(values[i])}}));
  act(()=>r.root.findAllByType('form').find(f=>f.findAllByType('input').some(i=>i.props.type==='number')).props.onSubmit(event));
  await act(async()=>{await button(r,'Confirm & generate recommendation').props.onClick();});
  await act(async()=>{await button(r,'Approve Design').props.onClick();});
  assert.ok(button(r,'Approved ✓'));
  act(()=>button(r,'Track follow-up →').props.onClick());
  for(const [name,value] of Object.entries({'OD follow-up AL':'25.2','OS follow-up AL':'25','OD current sphere':'-3.5','OS current sphere':'-3.25','Baseline comfort':'7','Current comfort':'7','Visual stress':'3','Average wear':'10','Follow-up date':'2027-04-30'}))act(()=>field(r,name).props.onChange({target:{value}}));
  await act(async()=>{r.root.findAllByType('form').find(f=>f.findAllByType('input').some(i=>i.props.type==='number')).props.onSubmit(event);await flush();});
  assert.equal(button(r,'Generate Next Recommendation →').props.disabled,false);
  await act(async()=>{await button(r,'Generate Next Recommendation →').props.onClick();});
  assert.ok(button(r,'Approve Design'));
  assert.equal(button(r,'Send Approved Design').props.disabled,true);
  act(()=>button(r,'Track follow-up →').props.onClick());
  assert.equal(field(r,'OD baseline AL').props.value,'25.2');
  assert.equal(field(r,'OD follow-up AL').props.value,'');
 }finally{if(r)act(()=>r.unmount());global.fetch=originalFetch;global.window=originalWindow;}
});

test('nested workflow dates survive sibling numeric edits before form submission',()=>{
 const RecordFields=load('components/RecordFields.js').default;
 const initial={observation:{visit_at:'',al_mm:24.2,source:''}};
 let current,renderer;
 function Harness(){const [value,setValue]=React.useState(initial);current=value;return React.createElement(RecordFields,{value,schema:initial,onChange:setValue});}
 try{
  act(()=>{renderer=create(React.createElement(Harness));});
  act(()=>field(renderer,'Visit at').props.onInput({target:{value:'2026-07-01'}}));
  act(()=>field(renderer,'Al mm').props.onChange({target:{value:'24.35'}}));
  act(()=>field(renderer,'Source').props.onInput({target:{value:'Synthetic UAT'}}));
  assert.deepEqual(current.observation,{visit_at:'2026-07-01',al_mm:24.35,source:'Synthetic UAT'});
 }finally{if(renderer)act(()=>renderer.unmount());}
});
