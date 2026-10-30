/** Opt-in: actual pinned capture, async proxy and factory; synthetic mission only. */
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';import assert from 'node:assert/strict';
const core=process.env.WIKI_TEST_OPENCLAW_CORE_ROOT,plugin=process.env.WIKI_TEST_OPENCLAW_PLUGIN_ROOT;
assert(core&&plugin,'Provide both pinned packages');
const scratch=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-native-route-')));
process.env.OPENCLAW_STATE_DIR=path.join(scratch,'state');process.env.OPENCLAW_CONFIG_PATH=path.join(scratch,'config.json');fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH,'{}');
process.env.WIKI_OPENCLAW_CORE_ROOT=core;process.env.WIKI_OPENCLAW_PLUGIN_ROOT=plugin;
assert(!process.env.WIKI_OPENCLAW_GUARD_BOOTSTRAP);
const loader=await import('../../scripts/openclaw/mission-loader.mjs');
const guard=await import('../../scripts/openclaw/mission-guard.mjs');
const {assertOwner}=await import('../../scripts/openclaw/mission-runtime.mjs');
let route,turnInstance,inferenceInstance;
try {
 await loader.install();
 const {n:PluginInstance,r:bind}=await import(pathToFileURL(path.join(core,'dist/plugin-setup-module-inWd3Rne.mjs')).href);
 const {t:createRegistry}=await import(pathToFileURL(path.join(core,'dist/registry-empty-mS6HujHb.mjs')).href);
 const {M:captureScope}=await import(pathToFileURL(path.join(core,'dist/plugin-generation-source-lookup-BCzbJZNI.mjs')).href);
 const captures=path.join(scratch,'captures');fs.mkdirSync(captures);
 const source=path.join(plugin,'dist/harness.js');
 const make=()=>{const registry=createRegistry(),record={id:'codex',origin:'global',source,trustedOfficialInstall:true};registry.plugins.push(record);return new PluginInstance('codex',{record,registry});};
 const files=(dir,name)=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name),name):e.name===name?[path.join(dir,e.name)]:[]);
 await captureScope(captures,async()=>{
  inferenceInstance=make();bind({instance:inferenceInstance,origin:'global',source,rootDir:plugin,pluginSdkResolution:'auto'});
  const sharedName='shared-client-C0gEybHs.mjs',inferName='inference-dispatch-CO6tTs4q.mjs',turnName='run-attempt-CGHsrfPB.mjs';
  const raw=name=>inferenceInstance.run(()=>inferenceInstance.moduleLoader(path.join(plugin,'dist/.setup',name)));
  raw(sharedName);const infer=raw(inferName),proxy=raw('inference-proxy-BZgN5W8m.mjs');
  const sharedFiles=files(captures,sharedName);assert.equal(sharedFiles.length,1);const sharedUrl=pathToFileURL(sharedFiles[0]).href;
  const manifest=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
  const sharedSpec=manifest.files.find(f=>f.name===sharedName);
  const original=fs.readFileSync(path.join(plugin,sharedSpec.relative),'utf8');const transformed=loader.transform(sharedName,original);
  // Execute the exact transformed native async callback body using the actual
  // proxy and inference factory. Only surrounding client/account data is synthetic.
  const fragment=sharedSpec.edits[1][1];assert(transformed.includes(fragment));
  const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
  const build=new AsyncFunction('createCodexInferenceProxy','createCodexInferenceModelBinding','client','provider','modelPolicyEnforced','assertClient','owner','native','target','preserveAzureUrlFeatures','preserveCodexBackendRoutes','wikiMissionGuard','moduleUrl',fragment.replaceAll('import.meta.url','moduleUrl'));
  let binding;const client={};let closed=false;
  const assertClient=()=>assert(!closed,'native client closed');
  route=await inferenceInstance.run(()=>build(proxy.createCodexInferenceProxy,(params)=>{binding=infer.createCodexInferenceModelBinding(params);return binding;},client,'openai',true,assertClient,{memoryConfigured:false}, {codexNativeSubagentMonitorRuntime:{captureModelSource:()=>{throw Error('No model calls in offline proof');},resolveModelThreadId:()=>{throw Error('No model calls in offline proof');}}},new URL('https://api.openai.com/v1'),false,false,guard,sharedUrl));
  assert.equal(typeof route.assertCurrent,'function');assert.equal(typeof route.close,'function');
  turnInstance=make();bind({instance:turnInstance,origin:'global',source,rootDir:plugin,pluginSdkResolution:'auto'});
  turnInstance.loadModule(path.join(plugin,'dist/.setup',turnName));
  const turnFiles=files(captures,turnName);assert.equal(turnFiles.length,2); // artifacts include all pinned files, even before evaluation
  const turnFile=turnFiles.find(p=>path.dirname(p)!==path.dirname(sharedFiles[0]));assert(turnFile);
  const turnOwner=turnInstance.run(()=>guard.captureOwner(pathToFileURL(turnFile).href));
  assert.throws(()=>assertOwner(turnOwner),/capture_hooks_incomplete/); // same-capture readiness was too strong
  assertOwner(turnOwner,turnName);
  const dir=path.join(scratch,'missions');fs.mkdirSync(dir);process.env.WIKI_OPENCLAW_MISSION_DIR=dir;
  const id='wiki-run-'+ 'a'.repeat(32),runDir=path.join(dir,id);fs.mkdirSync(runDir);
  const m={schema_version:'wiki_openclaw_mission.v1',run_id:id,session_key:'synthetic:route',session_id:'synthetic-session',native_thread_id:'synthetic-thread-route',provider:'openai',model:'synthetic-model',effort:'high',message_sha256:crypto.createHash('sha256').update('synthetic').digest('hex'),expires_at:new Date(Date.now()+60000).toISOString()};
  const rawMission=JSON.stringify(m);fs.writeFileSync(path.join(runDir,'mission.json'),rawMission);fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:id,contract_sha256:crypto.createHash('sha256').update(rawMission).digest('hex')}));
  let selected=route;const assertRoute=()=>assert.equal(selected,route);
  const params={runId:id,sessionKey:m.session_key,sessionId:m.session_id,provider:m.provider,modelId:m.model},turn={threadId:m.native_thread_id,model:m.model,effort:m.effort};
  assert.throws(()=>guard.authorizeTurn(params,turn,turnOwner,{},route,assertRoute),/turn_route_mismatch/);
  const beforeWrite=guard.authorizeTurn(params,turn,turnOwner,client,route,assertRoute);beforeWrite();
  selected={};assert.throws(beforeWrite);selected=route;
  guard.bindTurn(id,m.native_thread_id,'synthetic-turn');
  const check=guard.authorizeInference({binding,path:'/responses',provider:'openai',body:{model:m.model,reasoning:{effort:'high'}},metadata:{threadId:m.native_thread_id,turnId:'synthetic-turn'}});check();
  closed=true;assert.throws(check);closed=false;
  await inferenceInstance.dispose(undefined,{waitForSettlement:true});assert.throws(check,/capture_owner_retired/);
  console.log(JSON.stringify({distinct_native_captures:true,exact_transformed_async_route_body:true,actual_native_proxy_and_factory:true,wrong_client_refused:true,native_route_change_refused:true,client_close_refused:true,inference_owner_revocation_refused:true,synthetic_admission_only:true}));
 });
} finally {
 if(route)await route.close();
 for(const instance of [turnInstance,inferenceInstance])if(instance&&!instance.lifecycle.signal.aborted)await instance.dispose(undefined,{waitForSettlement:true});
 fs.rmSync(scratch,{recursive:true,force:true});
}
