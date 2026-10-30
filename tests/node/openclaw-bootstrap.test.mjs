import {test} from 'node:test';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {guardTestOwner} from './native-capture-fixture.mjs';
import * as guard from '../../scripts/openclaw/mission-guard.mjs';
guard.configureRuntime(['synthetic']);guard.loadedHook('synthetic');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');let serial=0;
function fixture() {
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-bootstrap-')));process.env.WIKI_OPENCLAW_MISSION_DIR=dir;
 const id='wiki-run-'+(++serial).toString(16).padStart(32,'0'),runDir=path.join(dir,id);fs.mkdirSync(runDir);
 const m={schema_version:'wiki_openclaw_mission.v1',run_id:id,session_key:'agent:example:first',session_id:'synthetic-session',native_thread_id:null,native_thread_binding:'first_turn',provider:'openai',model:'example-model',effort:'high',message_sha256:sha('Synthetic task.'),expires_at:new Date(Date.now()+60000).toISOString()};
 const raw=JSON.stringify(m),hash=sha(raw);fs.writeFileSync(path.join(runDir,'mission.json'),raw);fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:id,contract_sha256:hash}));
 const native=guardTestOwner(),client={},route={assertCurrent:()=>{}};
 const binding=guard.registerInferenceBinding(()=>{},client,'openai',native.inferenceOwner,()=>{});guard.registerInferenceRoute(client,binding,route,native.routeOwner);
 const chat={idempotencyKey:id,wikiMission:hash,sessionKey:m.session_key,sessionId:m.session_id,thinking:'high',suppressCommandInterpretation:true,deliver:false,message:'Synthetic task.',expectedLeafEntryId:null};
 const params={runId:id,sessionKey:m.session_key,sessionId:m.session_id,provider:m.provider,modelId:m.model};
 const started={threadId:'synthetic-created-'+serial,model:m.model,modelProvider:m.provider,lifecycle:{action:'started'}};
 const turn={threadId:started.threadId,model:m.model,effort:m.effort};
 const begin=(saved,authority=()=>{})=>guard.beginBootstrapThread(params,client,saved,native.creationOwner,authority);
 const admit=()=>guard.authorizeAdmission(chat,'exact',m.session_id);
 const authorize=(t=turn)=>guard.authorizeTurn(params,t,native.owner,client,route,()=>{});
 return {dir,runDir,m,raw,native,client,route,binding,chat,params,started,turn,begin,admit,authorize,clean:()=>{native.dispose();fs.rmSync(dir,{recursive:true,force:true});}};
}
test('first thread is created once, then exact turn/inference/terminal use its claim',()=>{
 const f=fixture();try{
  f.admit();let lease=true;const c=f.begin(null,()=>assert.ok(lease));guard.completeBootstrapThread(c,f.started);lease=false;
  const current=f.authorize();current();guard.bindTurn(f.m.run_id,f.turn.threadId,'synthetic-turn');
  guard.authorizeInference({binding:f.binding,path:'/responses',provider:'openai',body:{model:f.m.model,reasoning:{effort:'high'}},metadata:{threadId:f.turn.threadId,turnId:'synthetic-turn'}})();
  guard.recordTerminal(f.turn.threadId,{id:'synthetic-turn',status:'completed'});
  assert.equal(fs.readFileSync(path.join(f.runDir,'mission.json'),'utf8'),f.raw);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.runDir,'guard-turn.json'))).thread_id,f.started.threadId);
  assert.throws(()=>f.authorize());assert.throws(()=>f.begin(null));assert.throws(f.admit);
 }finally{f.clean();}
});
for(const relation of ['ancestor','off-path'])test('concurrent activity cannot use null ancestor admission: '+relation,()=>{
 const f=fixture();let forwarded=0;try{assert.throws(()=>{guard.authorizeAdmission(f.chat,relation,f.m.session_id);forwarded++;},/bootstrap_not_empty/);assert.equal(forwarded,0);assert.equal(fs.existsSync(path.join(f.runDir,'guard-bootstrap-admission.json')),false);}finally{f.clean();}
});
for(const saved of [{threadId:'old-thread'},{}])test('existing native binding rejected before lifecycle work',()=>{
 const f=fixture();try{f.admit();assert.throws(()=>f.begin(saved),/bootstrap_existing_binding/);assert.equal(fs.existsSync(path.join(f.runDir,'guard-bootstrap-start.json')),false);}finally{f.clean();}
});
for(const mutate of [s=>({...s,lifecycle:{action:'resumed'}}),s=>({...s,lifecycle:{action:'started',preserveExistingBinding:true}}),s=>({...s,lifecycle:{action:'started',rotatedContextEngineBinding:true}}),s=>({...s,model:'other'}),s=>({...s,modelProvider:'other'})])test('bootstrap refuses resume, rotation and conflicting selection',()=>{
 const f=fixture();try{f.admit();const c=f.begin(null);assert.throws(()=>guard.completeBootstrapThread(c,mutate(f.started)),/bootstrap_thread_mismatch/);assert.throws(()=>f.authorize(),/bootstrap_creation_required/);}finally{f.clean();}
});
test('bootstrap has no inference before exact created thread, or after owner revocation',()=>{
 const f=fixture();try{
  assert.throws(()=>f.begin(null));f.admit();const c=f.begin(null);assert.throws(()=>f.authorize(),/bootstrap_creation_required/);
  guard.completeBootstrapThread(c,f.started);assert.throws(()=>f.authorize({...f.turn,threadId:'different-thread'}),/bootstrap_creation_required/);
  const current=f.authorize();f.native.instance.accepting=false;assert.throws(current,/capture_owner_retired/);
  assert.equal(fs.existsSync(path.join(f.runDir,'guard-inference.jsonl')),false);
 }finally{f.clean();}
});
test('creation callback authority is checked before completion and second completion refused',()=>{
 const f=fixture();try{f.admit();let current=true;const c=f.begin(null,()=>assert.ok(current));current=false;assert.throws(()=>guard.completeBootstrapThread(c,f.started));current=true;guard.completeBootstrapThread(c,f.started);assert.throws(()=>guard.completeBootstrapThread(c,f.started),/bootstrap_thread_mismatch/);}finally{f.clean();}
});

test('fresh process cannot repeat a durable bootstrap creation claim',()=>{
 const f=fixture();try{
  f.admit();f.begin(null);
  const script=`import fs from 'node:fs';import path from 'node:path';import {guardTestOwner} from './tests/node/native-capture-fixture.mjs';import * as g from './scripts/openclaw/mission-guard.mjs';const m=JSON.parse(fs.readFileSync(process.env.BOOTSTRAP_CONTRACT));const n=guardTestOwner();let refused=false;try{g.beginBootstrapThread({runId:m.run_id,sessionKey:m.session_key,sessionId:m.session_id,provider:m.provider,modelId:m.model},{},null,n.creationOwner,()=>{});}catch(e){refused=e.code==='EEXIST';}if(!refused)process.exitCode=1;n.dispose();`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script],{cwd:new URL('../..',import.meta.url),env:{...process.env,BOOTSTRAP_CONTRACT:path.join(f.runDir,'mission.json')},encoding:'utf8'});
  assert.equal(child.status,0,child.stdout+child.stderr);assert.equal(fs.existsSync(path.join(f.runDir,'guard-turn.json')),false);
 }finally{f.clean();}
});
