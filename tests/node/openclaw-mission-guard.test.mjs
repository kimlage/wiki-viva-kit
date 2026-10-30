import {test} from 'node:test';
import {guardTestOwner} from './native-capture-fixture.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {authorizeChat,authorizeTurn,authorizeInference,bindTurn,recordTerminal,configureRuntime,loadedHook,registerInferenceBinding,registerInferenceRoute} from '../../scripts/openclaw/mission-guard.mjs';
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
configureRuntime(['synthetic-hook']);loadedHook('synthetic-hook');
let count=0;
function fixture(){
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-mission-test-')));
 process.env.WIKI_OPENCLAW_MISSION_DIR=dir;
 const id='wiki-run-'+(++count).toString(16).padStart(32,'0'), runDir=path.join(dir,id);fs.mkdirSync(runDir);
 const m={schema_version:'wiki_openclaw_mission.v1',run_id:id,session_key:'agent:example:mission',session_id:'synthetic-session',native_thread_id:`synthetic-thread-${count}`,provider:'openai',model:'example-model',effort:'high',message_sha256:sha('Read synthetic status.'),expires_at:new Date(Date.now()+60000).toISOString()};
 const raw=JSON.stringify(m);fs.writeFileSync(path.join(runDir,'mission.json'),raw);
 fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:id,contract_sha256:sha(raw)}));
 const chat={idempotencyKey:id,wikiMission:sha(raw),sessionKey:m.session_key,sessionId:m.session_id,thinking:m.effort,suppressCommandInterpretation:true,deliver:false,message:'Read synthetic status.'};
 const params={runId:id,sessionId:m.session_id,sessionKey:m.session_key,provider:m.provider,modelId:m.model};
 const turn={threadId:m.native_thread_id,model:m.model,effort:m.effort};
 const native=guardTestOwner(), inferenceNative=guardTestOwner();
 const client={},route={assertCurrent:()=>{}};
 const binding=registerInferenceBinding(()=>{},client,'openai',inferenceNative.inferenceOwner,()=>{});
 registerInferenceRoute(client,binding,route,inferenceNative.routeOwner);
 let selectedRoute=route;
 const assertRouteCurrent=()=>assert.equal(selectedRoute,route);
 const selectRoute=value=>{selectedRoute=value;};
 const inference={binding,path:'/responses',provider:'openai',body:{model:m.model,reasoning:{effort:m.effort}},metadata:{threadId:m.native_thread_id,turnId:'synthetic-turn'}};
 return {dir,runDir,m,chat,params,turn,inference,owner:native.owner,native,inferenceNative,client,route,binding,assertRouteCurrent,selectRoute};
}
function clean(f){f.native.dispose();f.inferenceNative.dispose();fs.rmSync(f.dir,{recursive:true,force:true});}
test('exact admission, inference, and revocation recheck',{concurrency:false},()=>{
 const f=fixture();try{authorizeChat(f.chat);authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');const current=authorizeInference(f.inference);current();
 assert.equal(JSON.parse(fs.readFileSync(path.join(f.runDir,'guard-inference.jsonl'),'utf8')).model,'example-model');
 fs.unlinkSync(path.join(f.dir,'mission-active.json'));assert.throws(current);
 }finally{clean(f);}
});
for(const [field,value] of [['sessionId','other-session'],['sessionKey','other-key'],['wikiMission','a'.repeat(64)],['message','Different prompt.'],['thinking','ultra'],['suppressCommandInterpretation',false]]){
 test(`send rejects changed ${field} before forwarding`,()=>{const f=fixture();let forwarded=0;try{assert.throws(()=>{authorizeChat({...f.chat,[field]:value});forwarded++;});assert.equal(forwarded,0);}finally{clean(f);}});
}
for(const mutate of [t=>({...t,model:'other-model'}),t=>({...t,effort:'ultra'}),t=>({...t,effort:undefined}),t=>({...t,threadId:'other-thread'}),t=>({...t,collaborationMode:{settings:{model:'other-model',reasoning_effort:'high'}}})]){
 test('turn rejects conflicting, missing, or inherited selection',()=>{const f=fixture();let forwarded=0;try{assert.throws(()=>{authorizeTurn(f.params,mutate(f.turn),f.owner,f.client,f.route,f.assertRouteCurrent);forwarded++;});assert.equal(forwarded,0);assert.equal(fs.existsSync(path.join(f.runDir,'guard-turn.json')),false);}finally{clean(f);}});
}
for(const mutate of [x=>({...x,body:{model:'other-model',reasoning:{effort:'high'}}}),x=>({...x,body:{model:'example-model',reasoning:{effort:'ultra'}}}),x=>({...x,body:{model:'example-model'}}),x=>({...x,path:'/guardian'}),x=>({...x,path:'/responses/compact',body:{model:'other-model'}}),x=>({...x,metadata:{...x.metadata,threadId:'another-thread'}}),x=>({...x,metadata:{...x.metadata,subagent:'review'}}),x=>({...x,metadata:{...x.metadata,turnId:'wrong-turn'}})]){
 test('inference mismatch has zero forwarding, including auxiliary paths',()=>{const f=fixture();let forwarded=0;try{authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');assert.throws(()=>{authorizeInference(mutate(f.inference));forwarded++;});assert.equal(forwarded,0);assert.equal(fs.existsSync(path.join(f.runDir,'guard-inference.jsonl')),false);}finally{clean(f);}});
}
test('durable turn claim rejects retries and restarted process without inference',()=>{
 const f=fixture();try{authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');assert.throws(()=>authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent));
 const code=`import {authorizeTurn} from ${JSON.stringify(new URL('../../scripts/openclaw/mission-guard.mjs',import.meta.url).href)}; import {guardTestOwner} from ${JSON.stringify(new URL("./native-capture-fixture.mjs",import.meta.url).href)}; const g=await import(${JSON.stringify(new URL("../../scripts/openclaw/mission-guard.mjs",import.meta.url).href)});const n=guardTestOwner(),c={},r={assertCurrent:()=>{}},b=g.registerInferenceBinding(()=>{},c,"openai",n.inferenceOwner,()=>{});g.registerInferenceRoute(c,b,r,n.routeOwner);authorizeTurn(${JSON.stringify(f.params)},${JSON.stringify(f.turn)},n.owner,c,r,()=>{});`;
 const child=spawnSync(process.execPath,['--input-type=module','-e',code],{env:{...process.env},encoding:'utf8'});assert.notEqual(child.status,0);assert.match(child.stderr,/EEXIST/);assert.equal(fs.existsSync(path.join(f.runDir,'guard-inference.jsonl')),false);
 }finally{clean(f);}
});
test('contract replacement and symlinks fail closed',()=>{const f=fixture();try{
 authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);fs.writeFileSync(path.join(f.runDir,'mission.json'),JSON.stringify({...f.m,effort:'max'}));assert.throws(()=>authorizeInference(f.inference));
 fs.unlinkSync(path.join(f.runDir,'mission.json'));fs.symlinkSync(path.join(f.dir,'mission-active.json'),path.join(f.runDir,'mission.json'));assert.throws(()=>authorizeChat(f.chat));
 }finally{clean(f);}});

test('inference before native binding refuses; only exact accepted turn and terminal admit',()=>{
 const f=fixture();try{authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);assert.throws(()=>authorizeInference(f.inference),/turn_identity/);
 bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');authorizeInference(f.inference);
 assert.throws(()=>recordTerminal(f.m.native_thread_id,{id:'wrong-turn',status:'completed'}));
 recordTerminal(f.m.native_thread_id,{id:'synthetic-turn',status:'completed'});
 assert.equal(JSON.parse(fs.readFileSync(path.join(f.runDir,'guard-terminal.json'))).turn_id,'synthetic-turn');
 }finally{clean(f);}
});
test('partial runtime refuses chat before forwarding',()=>{
 const f=fixture();try{
 const code=`import {configureRuntime,loadedHook,authorizeChat} from ${JSON.stringify(new URL('../../scripts/openclaw/mission-guard.mjs',import.meta.url).href)}; configureRuntime(['send','turn','inference']);loadedHook('send');authorizeChat(${JSON.stringify(f.chat)});console.log('FORWARDED');`;
 const child=spawnSync(process.execPath,['--input-type=module','-e',code],{env:{...process.env},encoding:'utf8'});assert.notEqual(child.status,0);assert.match(child.stderr,/incomplete_overlay/);assert.equal(child.stdout.includes('FORWARDED'),false);
 }finally{clean(f);}
});
for(const missing of ['schema','send','turn','inference']) test(`missing ${missing} hook refuses admission`,()=>{
 const f=fixture();try{
 const names=['schema','send','turn','inference'];
 const code=`import {configureRuntime,loadedHook,authorizeChat} from ${JSON.stringify(new URL('../../scripts/openclaw/mission-guard.mjs',import.meta.url).href)};configureRuntime(${JSON.stringify(names)});${names.filter(n=>n!==missing).map(n=>`loadedHook('${n}');`).join('')}authorizeChat(${JSON.stringify(f.chat)});console.log('FORWARDED');`;
 const child=spawnSync(process.execPath,['--input-type=module','-e',code],{env:{...process.env},encoding:'utf8'});assert.notEqual(child.status,0);assert.match(child.stderr,/incomplete_overlay/);assert.equal(child.stdout.includes('FORWARDED'),false);
 }finally{clean(f);}
});
test('runtime package tree refuses replaced, missing and renamed modules',async()=>{
 const {treeHash,validatePackage,transform}=await import('../../scripts/openclaw/mission-loader.mjs');
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-package-test-')));
 try{
 fs.writeFileSync(path.join(dir,'package.json'),JSON.stringify({name:'synthetic',version:'1'}));
 fs.writeFileSync(path.join(dir,'hook.mjs'),'export const value=1;');
 const spec={name:'synthetic',version:'1',tree_sha256:treeHash(dir)};validatePackage(dir,spec);
 fs.renameSync(path.join(dir,'hook.mjs'),path.join(dir,'renamed.mjs'));assert.throws(()=>validatePackage(dir,spec));
 fs.renameSync(path.join(dir,'renamed.mjs'),path.join(dir,'hook.mjs'));fs.writeFileSync(path.join(dir,'hook.mjs'),'export const value=2;');assert.throws(()=>validatePackage(dir,spec));
 fs.unlinkSync(path.join(dir,'hook.mjs'));assert.throws(()=>validatePackage(dir,spec));
 assert.throws(()=>transform('inference-dispatch-CO6tTs4q.mjs','incompatible source'));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});


test('inference rejects a different native owner and rechecks logical revocation',()=>{
 const f=fixture(),other=guardTestOwner();try{
 authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');
 assert.throws(()=>authorizeInference({...f.inference,binding:()=>{}}),/inference_binding_required/);
 const current=authorizeInference(f.inference);f.native.instance.owner.revoked=true;
 assert.throws(current,/capture_owner_retired/);
 }finally{other.dispose();clean(f);}
});

// The SDK facade must expose only the exact frozen host functions.
test('SDK facade refuses missing, mutable, copied, replaced or extra authority',async()=>{
 const {assertSharedSdkBridge}=await import('../../scripts/openclaw/mission-loader.mjs');
 const host=await import('../../scripts/openclaw/mission-guard.mjs');
 const keys=['authorizeTurn','bindTurn','captureOwner','recordTerminal','authorizeInference','checkInferenceSelection','loadedHook','registerInferenceBinding','registerInferenceRoute'];
 const bridge=Object.fromEntries(keys.map(key=>[key,host[key]]));
 assertSharedSdkBridge({wikiMissionBridge:Object.freeze({...bridge})});
 for(const value of [undefined,bridge,Object.freeze({...bridge,loadedHook:()=>{}}),Object.freeze({...bridge,configureRuntime:host.configureRuntime}),Object.freeze(Object.fromEntries(Object.entries(bridge).slice(1)))]){
  assert.throws(()=>assertSharedSdkBridge({wikiMissionBridge:value}),/sdk_overlay_missing/);
 }
});

for(const change of ['client','route','infer-owner','turn-owner','native-route','route-owner'])test(`route custody refuses ${change} before forwarding`,()=>{
 const f=fixture();try{
  if(change==='client'||change==='route') {
   assert.throws(()=>authorizeTurn(f.params,f.turn,f.owner,change==='client'?{}:f.client,change==='route'?{}:f.route,f.assertRouteCurrent));
   assert.equal(fs.existsSync(path.join(f.runDir,'guard-turn.json')),false);return;
  }
  const beforeWrite=authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);
  if(change==='infer-owner'||change==='route-owner')f.inferenceNative.instance.owner.revoked=true;
  if(change==='turn-owner')f.native.instance.owner.revoked=true;
  if(change==='native-route')f.selectRoute({});
  let forwards=0;assert.throws(()=>{beforeWrite();forwards++;});assert.equal(forwards,0);
  assert.throws(()=>bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn'));
 }finally{clean(f);}
});
test('same client and provider with another binding/route cannot cross missions',()=>{
 const f=fixture(),n=guardTestOwner();try{
  const other=registerInferenceBinding(()=>{},f.client,'openai',n.inferenceOwner,()=>{});
  registerInferenceRoute(f.client,other,{assertCurrent:()=>{}},n.routeOwner);
  authorizeTurn(f.params,f.turn,f.owner,f.client,f.route,f.assertRouteCurrent);bindTurn(f.m.run_id,f.m.native_thread_id,'synthetic-turn');
  assert.throws(()=>authorizeInference({...f.inference,binding:other}),/inference_route_mismatch/);
  assert.throws(()=>registerInferenceRoute(f.client,f.binding,{assertCurrent:()=>{}},f.inferenceNative.routeOwner),/inference_route_invalid/);
  const check=authorizeInference(f.inference);f.selectRoute({});assert.throws(check);
 }finally{n.dispose();clean(f);}
});
test('route registration rejects promises and wrong native client/owner',()=>{
 const f=fixture(),n=guardTestOwner();try{
  const binding=registerInferenceBinding(()=>{},f.client,'openai',n.inferenceOwner,()=>{});
  for(const [client,route,owner] of [[{}, {assertCurrent:()=>{}},n.routeOwner],[f.client,Promise.resolve({}),n.routeOwner],[f.client,{assertCurrent:()=>{}},f.inferenceNative.routeOwner]])
   assert.throws(()=>registerInferenceRoute(client,binding,route,owner),/inference_route_invalid/);
 }finally{n.dispose();clean(f);}
});
