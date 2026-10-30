/** Opt-in: actual pinned capture, async proxy and factory; synthetic mission only. */
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';import {spawnSync} from 'node:child_process';import assert from 'node:assert/strict';
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
 const allHooks=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
 for(const f of allHooks.files.filter(f=>f.package==='core'))await import(pathToFileURL(path.join(core,f.relative)).href);
 const {n:resolveOptions}=await import(pathToFileURL(path.join(plugin,'dist/.setup/config-runtime-BUH-IDVE.mjs')).href);
 const {r:resolveManaged}=await import(pathToFileURL(path.join(plugin,'dist/.setup/managed-binary-Boj8_lWV.mjs')).href);
 const external=resolveOptions({pluginConfig:{appServer:{command:'/synthetic/external-codex',homeScope:'agent'}},env:{}}).start;
 assert.equal(external.commandSource,'config');assert.throws(()=>guard.authorizeClientStart(external),/client_selection_changed/);
 const requested=resolveOptions({pluginConfig:{appServer:{homeScope:'agent'},computerUse:{enabled:false}},env:{}}).start;
 assert.equal(requested.commandSource,'managed');
 const managed=await resolveManaged(requested,{pluginRoot:plugin});guard.authorizeClientStart(managed);
 const {a:ephemeral}=await import(pathToFileURL(path.join(plugin,'dist/.setup/auth-start-options-BPIPeEX8.mjs')).href);
 const prepared=ephemeral({startOptions:managed,authProfileId:'synthetic-profile'});
 assert.notDeepEqual(prepared.args,managed.args);guard.authorizeClientStart(prepared);
 for(const command of managed.managedFallbackCommandPaths??[])assert.throws(()=>guard.authorizeClientStart({...managed,command}),/client_selection_changed/);

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
  const firstId='wiki-run-'+'b'.repeat(32),firstDir=path.join(dir,firstId);fs.mkdirSync(firstDir);
  const first={...m,run_id:firstId,native_thread_id:null,native_thread_binding:'first_turn'};
  const firstRaw=JSON.stringify(first),firstHash=crypto.createHash('sha256').update(firstRaw).digest('hex');
  fs.writeFileSync(path.join(firstDir,'mission.json'),firstRaw);fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:firstId,contract_sha256:firstHash}));
  const chat={idempotencyKey:firstId,wikiMission:firstHash,sessionKey:first.session_key,sessionId:first.session_id,thinking:'high',suppressCommandInterpretation:true,deliver:false,message:'synthetic',expectedLeafEntryId:null};
  const chatName='chat-send-handler-B0jivtwJ.mjs';
  const nativeChat=loader.transform(chatName,fs.readFileSync(path.join(core,'dist',chatName),'utf8'));
  const start=nativeChat.indexOf('function assertExpectedLeafActive('),end=nativeChat.indexOf('//#endregion',start);assert(start>0&&end>start);
  let relation='ancestor';
  const admission=new Function('readSessionTranscriptActivePathEntryRelation','wikiMissionGuard','ACTIVE_LEAF_CHANGED_ERROR_REASON','return ('+nativeChat.slice(start,end)+')')(()=>relation,guard,'active-leaf-changed');
  const session={entry:{sessionId:first.session_id},canonicalKey:first.session_key};
  let forwarded=0;
  assert.throws(()=>{admission(session,'synthetic-agent',null,first.session_id,{allowEmptyAncestor:true,wikiMissionParams:chat});forwarded++;},/bootstrap_not_empty/);assert.equal(forwarded,0);
  relation='exact';admission(session,'synthetic-agent',null,first.session_id,{allowEmptyAncestor:true,wikiMissionParams:chat});
  const lifecycleName='thread-lifecycle-run-BHM-L-56.mjs';
  const lifecycleFile=path.join(path.dirname(turnFile),lifecycleName);
  const lifecycleOwner=turnInstance.run(()=>guard.captureOwner(pathToFileURL(lifecycleFile).href));
  const firstParams={...params,runId:firstId};
  assert.throws(()=>guard.beginBootstrapThread(firstParams,client,{threadId:'prior-thread'},lifecycleOwner,()=>{}),/bootstrap_existing_binding/);
  const creation=guard.beginBootstrapThread(firstParams,client,null,lifecycleOwner,()=>{});
  const created={threadId:'synthetic-bootstrap-thread',model:first.model,modelProvider:first.provider,lifecycle:{action:'started'}};
  guard.completeBootstrapThread(creation,created);
  const firstTurn={...turn,threadId:created.threadId};
  guard.authorizeTurn(firstParams,firstTurn,turnOwner,client,route,assertRoute)();
  guard.bindTurn(firstId,created.threadId,'synthetic-first-turn');
  guard.authorizeInference({binding,path:'/responses',provider:'openai',body:{model:first.model,reasoning:{effort:'high'}},metadata:{threadId:created.threadId,turnId:'synthetic-first-turn'}})();
  assert.throws(()=>guard.beginBootstrapThread(firstParams,client,null,lifecycleOwner,()=>{}));
  // Exercise the actual transformed native lifecycle admission with a saved
  // binding and the core-created continuation alias, before the native turn.
  const recoveryRepo=path.join(scratch,'recovery-repo');fs.mkdirSync(recoveryRepo);
  fs.writeFileSync(path.join(recoveryRepo,'action.md'),'Synthetic maintenance.\n');
  fs.writeFileSync(path.join(recoveryRepo,'wiki.config.yaml'),'repo_id: synthetic\n');
  for(const args of [['init','-b','main'],['config','user.name','Synthetic'],['config','user.email','synthetic@example.test'],['add','.'],['commit','-qm','fixture']])assert.equal(spawnSync('git',args,{cwd:recoveryRepo}).status,0);
  const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
  const recoveryId='wiki-run-'+'c'.repeat(32),recoveryDir=path.join(dir,recoveryId);fs.mkdirSync(recoveryDir);
  const recoveryMission={...m,run_id:recoveryId,native_thread_id:'synthetic-recovery-thread',recovery:{mode:'read_only',max_continuations:1,repo_root:recoveryRepo,approved_head:spawnSync('git',['rev-parse','HEAD'],{cwd:recoveryRepo,encoding:'utf8'}).stdout.trim(),action_path:'action.md',action_sha256:hash(fs.readFileSync(path.join(recoveryRepo,'action.md'))),config_sha256:hash(fs.readFileSync(path.join(recoveryRepo,'wiki.config.yaml')))}};
  const recoveryRaw=JSON.stringify(recoveryMission),recoveryHash=hash(recoveryRaw);
  fs.writeFileSync(path.join(recoveryDir,'mission.json'),recoveryRaw);fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:recoveryId,contract_sha256:recoveryHash}));
  const rp={...params,runId:recoveryId},rt={...turn,threadId:recoveryMission.native_thread_id};
  guard.authorizeTurn(rp,rt,turnOwner,client,route,assertRoute);guard.bindTurn(recoveryId,rt.threadId,'source-turn');
  const agent={agentId:'worker',sessionKey:m.session_key,expectedExistingSessionId:m.session_id,idempotencyKey:crypto.randomUUID(),internalRuntimeHandoffId:'native-handoff',internalExecutionIdentityRecoveryAttempt:1,inputProvenance:{kind:'internal_system'},deliver:false};
  const cfg={agents:{entries:{worker:{sandbox:{mode:'all',workspaceAccess:'ro',backend:'docker',docker:{readOnlyRoot:true,network:'none'}}}}},tools:{allow:['read','ls','session_status'],fs:{workspaceOnly:true}}};
  guard.authorizeNativeRecovery(agent,recoveryId,cfg,()=>{})();
  const lcSpec=allHooks.files.find(f=>f.name===lifecycleName);
  const nativeLifecycle=loader.transform(lifecycleName,fs.readFileSync(path.join(plugin,lcSpec.relative),'utf8'));
  assert(nativeLifecycle.includes(lcSpec.edits[0][1]));
  const lifecycleAdmission=new Function('wikiMissionGuard','input','saved','authority',lcSpec.edits[0][1].replaceAll('import.meta.url','input.moduleUrl')+'\nreturn wikiBootstrap;');
  const resumed={...rp,runId:agent.idempotencyKey};
  assert.equal(turnInstance.run(()=>lifecycleAdmission(guard,{params:resumed,client,moduleUrl:pathToFileURL(lifecycleFile).href},{threadId:rt.threadId},{assertCurrent:()=>{}})),null);
  guard.authorizeTurn(resumed,rt,turnOwner,client,route,assertRoute)();guard.bindTurn(agent.idempotencyKey,rt.threadId,'recovery-turn');
  guard.authorizeInference({binding,path:'/responses',provider:'openai',body:{model:m.model,reasoning:{effort:'high'}},metadata:{threadId:rt.threadId,turnId:'recovery-turn'}})();
  // Restore the earlier contract solely for the existing route-revocation regression.
  fs.writeFileSync(path.join(dir,'mission-active.json'),JSON.stringify({run_id:id,contract_sha256:crypto.createHash('sha256').update(rawMission).digest('hex')}));
  closed=true;assert.throws(check);closed=false;
  await inferenceInstance.dispose(undefined,{waitForSettlement:true});assert.throws(check,/capture_owner_retired/);
  console.log(JSON.stringify({native_recovery_lifecycle_and_turn_verified:true,native_final_admission_race_refused:true,captured_bootstrap_custody_verified:true,native_managed_selection_verified:true,external_and_desktop_fallback_refused:true,distinct_native_captures:true,exact_transformed_async_route_body:true,actual_native_proxy_and_factory:true,wrong_client_refused:true,native_route_change_refused:true,client_close_refused:true,inference_owner_revocation_refused:true,synthetic_admission_only:true}));
 });
} finally {
 if(route)await route.close();
 for(const instance of [turnInstance,inferenceInstance])if(instance&&!instance.lifecycle.signal.aborted)await instance.dispose(undefined,{waitForSettlement:true});
 fs.rmSync(scratch,{recursive:true,force:true});
}
