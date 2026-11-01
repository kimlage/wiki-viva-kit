import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {readResidentNativeActivity,RESIDENT_OBSERVATION_CAPABILITY as cap,validateResidentObservation,
  residentObservationClientGuard,checkResidentObservationClientChallenge,assertResidentObservationCall,
  assertResidentObservationConnect,assertResidentObservationRequest,assertResidentObservationMethod,
  authorizeResidentObservation,respondResidentObservation} from '../../scripts/openclaw/mission-runtime.mjs';

const target={agentId:'example',sessionKey:'agent:example:observation-fixture',sessionId:'fixture-session'};
const generation=Symbol('fixture-generation');
const scope={scope:'resident_gateway_owners',complete:false,persisted_queue_count:null};
const observationParams=()=>({key:target.sessionKey,agentId:target.agentId,wikiObservation:{version:1,sessionId:target.sessionId}});
function authorizedFixture() {
  const f=fixture(), events=[];
  const cfg={}, row={canonicalKey:target.sessionKey,agentId:target.agentId,generation,
    entry:{sessionId:target.sessionId,lifecycleRevision:1}};
  const source={agentId:target.agentId,path:'/synthetic/session.sqlite',databaseIdentity:Symbol(),databaseBirthtime:1};
  const membership=new Set(['synthetic-member']);
  const projection={sharingRevision:1,getPolicyConfig:()=>cfg,sharingTargetState:()=>({status:'ready',target:row}),
    readSource:()=>({...source}),readMembership:()=>new Set(membership)};
  for(const key of ['state','describe','capture','prepareMembership','observeGeneration'])Object.defineProperty(projection,key,{get(){throw new Error('forbidden_domain_preparation');}});
  const client={connect:{client:{id:'cli',mode:'cli'},role:'operator',scopes:['operator.read'],caps:[cap]},
    usesSharedGatewayAuth:true,internal:{operatorRoleActor:{kind:'system'},authenticatedOperator:true,isLocalClient:true},
    authPolicy:{generation:'native-auth'},connectionSignal:new AbortController().signal};
  Object.assign(f.context,{getRuntimeConfig:()=>cfg,getCommittedRuntimeConfig:()=>cfg,
    ensureSessionRowProjection:()=>{throw new Error('forbidden_domain_preparation');}});
  const params={method:'sessions.describe',requestParams:observationParams(),client,context:f.context,
    hasCurrentClientAuthority:()=>true,assertInvocationCurrent:()=>events.push('native-authority')};
  const native={authorizeMethod:()=>{events.push('native-method');return {error:null};},uploadPolicy:()=>null,
    resolveAgent:()=>({ok:true,agentId:target.agentId}),
    authorizeProfile:async()=>{events.push('native-profile');return null;},getProjection:()=>projection,
    isIncognito:()=>false,permissionPending:()=>false,authorizeSession:request=>{
      events.push('native-session');assert.equal(request.sessionRowRead.describe({key:target.sessionKey,agentId:target.agentId}).entry,row.entry);
      return {error:null};},authorizeIncognito:()=>null,prepareSharing:()=>({entryFilter:()=>true}),hasBoundary:()=>false};
  return {...f,events,cfg,row,source,membership,projection,client,params,native,
    authorize:()=>authorizeResidentObservation(params,native),
    respond:authorization=>respondResidentObservation(params.requestParams,authorization,f.context,
      {...f.native,processInstanceId:()=> 'synthetic-process'})};
}

test('qualified router authority reaches exact resident response through native policy callbacks',async()=>{
  const f=authorizedFixture(), req={method:'sessions.describe',params:f.params.requestParams};
  assertResidentObservationRequest(req,f.client,{isWebchatConnect:p=>p.client.mode==='webchat'});
  const auth=await f.authorize();assert.equal(auth.error,null);
  const result=f.respond(auth.wikiObservationAuthorization);
  assert.equal(result.status,'observed');assert.equal(result.sessionId,target.sessionId);
  assert.equal(result.process_instance_id,'synthetic-process');assert.equal(result.complete,false);
  for(const effect of ['native-method','native-profile','native-session','native-authority'])assert.ok(f.events.includes(effect));
});
test('presence of a malformed option never falls through to native preparing describe',async()=>{
  for(const value of [null,false,{}, {version:2,sessionId:target.sessionId}]) {
    const f=authorizedFixture();f.params.requestParams.wikiObservation=value;
    assert.throws(()=>validateResidentObservation('sessions.describe',f.params.requestParams));
    assert.equal((await f.authorize()).error.code,'UNAVAILABLE');assert.deepEqual(f.events,[]);
  }
  for(const key of ['includeLastMessage','includeDerivedTitles','unknown']) {
    const f=authorizedFixture();f.params.requestParams[key]=false;
    assert.equal((await f.authorize()).error.code,'UNAVAILABLE');
  }
});
test('connection scope cannot call another method, bind a profile or use synthetic/run authority',()=>{
  for(const mutate of [f=>f.req.method='chat.send',f=>delete f.req.params.wikiObservation,
    f=>f.req.expectedProfileId='human',f=>f.client.preparedSessionProfile={},
    f=>f.client.authenticatedGitHubIdentitySync=()=>{throw new Error('must not sync');},
    f=>f.client.internal.operatorRoleActor={kind:'operator',profileId:'human'},
    f=>f.client.internal.syntheticClient=true,f=>f.client.internal.operatorRunAuthority={},
    f=>f.client.invalidated=true,f=>f.options.prepareDispatchCurrent=()=>{},
    f=>f.options.isWebchatConnect=()=>true]) {
    const f=authorizedFixture();f.req={method:'sessions.describe',params:f.params.requestParams};f.options={};mutate(f);
    assert.throws(()=>assertResidentObservationRequest(f.req,f.client,f.options));
  }
});
test('cold, pending, aliased or rebound native owners remain unavailable',async()=>{
  for(const mutate of [f=>f.native.getProjection=()=>null,f=>f.projection.sharingRevision=undefined,
    f=>f.projection.sharingTargetState=()=>({status:'pending'}),f=>f.row.canonicalKey='agent:example:alias',
    f=>f.row.entry.sessionId='replacement',f=>f.native.permissionPending=()=>true,
    f=>f.context.agentDatabaseStartup={hasPendingAgents:true},f=>f.context.unavailableGatewayMethods=new Set(['sessions.describe']),
    f=>f.projection.readMembership=()=>undefined]) {
    const f=authorizedFixture();mutate(f);assert.equal((await f.authorize()).error.code,'UNAVAILABLE');
  }
});
test('native permission refusals and visibility are retained',async()=>{
  for(const point of ['authorizeMethod','authorizeProfile','authorizeSession','authorizeIncognito','uploadPolicy']) {
    const f=authorizedFixture(), error={code:'FORBIDDEN',message:'native-denial'};
    f.native[point]=()=>['authorizeMethod','authorizeSession'].includes(point)?{error}:error;
    assert.deepEqual((await f.authorize()).error,error);
  }
  const f=authorizedFixture();f.native.hasBoundary=()=>true;f.native.prepareSharing=()=>({entryFilter:()=>false});
  assert.equal((await f.authorize()).error.code,'UNAVAILABLE');
});
test('authorization is rechecked after native profile await and before response delivery',async()=>{
  for(const mutate of [f=>f.client.invalidated=true,f=>f.client.connect.scopes=[],f=>f.client.authPolicy={},
    f=>f.client.preparedSessionProfile={},f=>f.params.hasCurrentClientAuthority=()=>false,
    f=>f.row.entry.sessionId='replacement',f=>f.row.entry.lifecycleRevision++,f=>f.row.generation=Symbol(),
    f=>f.projection.sharingRevision++,f=>f.source.databaseIdentity=Symbol(),f=>f.membership.clear()]) {
    const f=authorizedFixture(),auth=await f.authorize();assert.equal(auth.error,null);mutate(f);
    assert.throws(()=>f.respond(auth.wikiObservationAuthorization));
  }
  const f=authorizedFixture();f.native.authorizeProfile=async()=>{await Promise.resolve();f.client.preparedSessionProfile={};return null;};
  assert.equal((await f.authorize()).error.code,'UNAVAILABLE');assert.equal(f.events.includes('native-session'),false);
});
test('core handler, observation lifetime and no read-sharing are mandatory',()=>{
  const f=authorizedFixture(),handler=()=>{},req={method:'sessions.describe',params:f.params.requestParams};
  const registry={getHandler:()=>handler,getScope:()=> 'operator.read',isObservation:()=>true,getReadSharing:()=>undefined};
  assertResidentObservationMethod(req,f.client,registry,handler);
  for(const change of [{getHandler:()=>()=>{}},{getScope:()=> 'operator.admin'},{isObservation:()=>false},{getReadSharing:()=>({})}])
    assert.throws(()=>assertResidentObservationMethod(req,f.client,{...registry,...change},handler));
});
test('native client normalization retains original read-only proof and rejects legacy challenge before connect',()=>{
  const options={caps:[cap],deviceIdentity:null,sharedStateMode:'read-only',mode:'cli',clientName:'cli'};
  const inner={caps:options.caps,deviceIdentity:undefined,wikiObservationChallengeGuard:residentObservationClientGuard(options)};
  assert.throws(()=>checkResidentObservationClientChallenge(inner,[]));
  checkResidentObservationClientChallenge(inner,[cap]);
  options.sharedStateMode='read-write';assert.throws(()=>checkResidentObservationClientChallenge(inner,[cap]));
  for(const change of [{deviceIdentity:undefined},{deviceIdentity:{}},{mode:'backend'},{sharedStateMode:undefined}])
    assert.throws(()=>residentObservationClientGuard({...options,sharedStateMode:'read-only',...change}));
});
test('client preflight refuses cold credentials, remote, shell fallback and scope/identity shortcuts',()=>{
  const input={caps:[cap],method:'sessions.describe',params:observationParams(),config:{gateway:{auth:{mode:'token'}}},
    clientName:'cli',mode:'cli',deviceIdentity:null,sharedStateMode:'read-only',expectUrl:'ws://127.0.0.1:19880'};
  let reads=0;const facts={authMode:'token',secretRefCanWin:false,readCredentials:()=>{reads++;return {token:'synthetic-local-auth'};}};
  assertResidentObservationCall(input,facts);assert.equal(reads,1);
  for(const change of [{secretRefCanWin:true},{authMode:'none'},{urlOverrideSource:'env'}]) {
    assert.throws(()=>assertResidentObservationCall(input,{...facts,...change}));assert.equal(reads,1);
  }
  for(const change of [{config:undefined},{url:'ws://127.0.0.1:19880'},{deviceIdentity:undefined},
    {config:{gateway:{mode:'remote'}}},{config:{gateway:{remote:{url:'ws://example.test'}}}},{useStoredDeviceAuth:true}])
    assert.throws(()=>assertResidentObservationCall({...input,...change}));
});
test('restricted connect admits existing local shared authentication only',()=>{
  const context={connectParams:{client:{id:'cli',mode:'cli'},role:'operator',caps:['ultrafast',cap],auth:{token:'synthetic-local-auth'}},
    isLocalClient:true,pendingNodePairingCleanup:{},handler:{remoteAddr:'127.0.0.1',getResolvedAuth:()=>({mode:'token'}),
      isClosed:()=>false,connectionWork:{signal:new AbortController().signal}}};
  const state={role:'operator',authMethod:'token',authResult:{},sessionUsesSharedGatewayAuth:true};
  assertResidentObservationConnect(context,state);
  for(const change of [{device:{}},{authResult:{user:'human'}},{authMethod:'none'},{sessionUsesSharedGatewayAuth:false},{deviceToken:{}}])
    assert.throws(()=>assertResidentObservationConnect(context,{...state,...change}));
  for(const change of [{hasProxyHeaders:true},{hasBrowserOriginHeader:true},{isLocalClient:false},
    {connectParams:{...context.connectParams,modelCatalog:{}}}])assert.throws(()=>assertResidentObservationConnect({...context,...change},state));
});
function fixture() {
  const context={chatAbortControllers:new Map(),chatQueuedTurns:new Map(),dedupe:new Map()};
  const native={assertCurrent:()=>{},isGenerationCurrent:value=>value===generation,
    isTerminalSettled:entry=>entry.projectSessionTerminalPending!==true && entry.projectSessionTerminalPersistence===undefined};
  const entry=extra=>({...target,controller:new AbortController(),lifecycleGeneration:generation,executionStarted:true,...extra});
  return {context,native,entry,read:()=>readResidentNativeActivity(context,target,native)};
}
function expectUnknown(result) {
  assert.equal(result.status,'unavailable');
  for(const key of ['has_active_run','active_run_ids','active_count','terminal_persistence_count','terminal_cleanup_count','queued_turn_count','pending_admission_count','persisted_queue_count']) assert.equal(result[key],null,key);
  assert.equal(result.complete,false);
  assert.equal(result.resident_complete,false);
}

test('zero only describes resident owners, with global and persisted queue state unproven',()=>{
  const f=fixture();assert.deepEqual(f.read(),{...scope,status:'observed',has_active_run:false,active_run_ids:[],active_count:0,
    terminal_persistence_count:0,terminal_cleanup_count:0,queued_turn_count:0,pending_admission_count:0,resident_complete:true,ids_truncated:false,error_code:null});
  for(const key of Object.keys(f.context)) expectUnknown(readResidentNativeActivity({...f.context,[key]:undefined},target,f.native));
});
test('active, queued, terminal and pending owners stay distinct and deduplicated',()=>{
  const f=fixture();
  f.context.chatAbortControllers.set('active',f.entry());
  f.context.chatAbortControllers.set('terminal',f.entry({terminalOutcomeObserved:true,projectSessionTerminalPending:true}));
  f.context.chatAbortControllers.set('admitting',f.entry({executionStarted:false}));
  f.context.chatQueuedTurns.set('queued',f.entry());
  f.context.chatQueuedTurns.set('active',f.context.chatAbortControllers.get('active'));
  for(const id of ['active','terminal','admitting','queued','pending']) f.context.dedupe.set('agent:'+id,{ok:true,payload:{...target,runId:id,status:'accepted'}});
  f.context.dedupe.set('pending-chat:pending',{ok:true,payload:{...target,runId:'pending',status:'accepted'}});
  assert.deepEqual(f.read(),{...scope,status:'observed',has_active_run:true,active_run_ids:['active'],active_count:1,
    terminal_persistence_count:1,terminal_cleanup_count:0,queued_turn_count:1,pending_admission_count:2,resident_complete:true,ids_truncated:false,error_code:null});
});
test('queued cancellation transfer remains visible even after the old signal aborts',()=>{
  const f=fixture(),entry=f.entry({abortable:false});entry.controller.abort();
  f.context.chatQueuedTurns.set('collect-owner',entry);
  assert.equal(f.read().queued_turn_count,1);assert.equal(f.read().active_count,0);
});
test('terminal persistence is separate from settled registrations awaiting cleanup',()=>{
  for(const extra of [{projectSessionTerminalPending:true},{projectSessionTerminalPersistence:Promise.resolve()}]) {
    const f=fixture();f.context.chatAbortControllers.set('terminal',f.entry(extra));
    assert.equal(f.read().terminal_persistence_count,1);assert.equal(f.read().active_count,0);
    assert.equal(f.read().terminal_cleanup_count,0);
  }
  for(const extra of [{registrationCleanupRequested:true},{projectSessionTerminalObservedAt:123},{terminalOutcomeObserved:true}]) {
    const f=fixture();f.context.chatAbortControllers.set('terminal',f.entry(extra));
    assert.equal(f.read().terminal_cleanup_count,1);assert.equal(f.read().active_count,0);
    assert.equal(f.read().terminal_persistence_count,0);
  }
});
test('overlapping terminal or cleanup and queued owners cannot imply an empty queue',()=>{
  for(const extra of [{terminalOutcomeObserved:true},{registrationCleanupRequested:true},
    {projectSessionTerminalPending:true},{projectSessionTerminalObservedAt:123}]) {
    const f=fixture(),entry=f.entry(extra);
    f.context.chatAbortControllers.set('run',entry);
    f.context.chatQueuedTurns.set('run',{...target,controller:entry.controller});
    expectUnknown(f.read());
  }
});
test('identity mismatch, stale generation and ambiguous admission never report idle',()=>{
  for(const extra of [{sessionId:'rebound-session'},{agentId:'other'},{lifecycleGeneration:Symbol('old')},{executionStarted:undefined}]) {
    const f=fixture();f.context.chatAbortControllers.set('run',f.entry(extra));expectUnknown(f.read());
  }
  const f=fixture();f.context.dedupe.set('pending-chat:pending',{ok:true,payload:{status:'accepted',runId:'pending',sessionKey:target.sessionKey}});expectUnknown(f.read());
  f.context.dedupe.clear();f.context.chatAbortControllers.set('run',f.entry());f.context.chatQueuedTurns.set('run',f.entry());expectUnknown(f.read());
});
test('unaddressable resident owners cannot prove zero',()=>{
  for(const key of ['chatAbortControllers','chatQueuedTurns']) {
    const f=fixture();f.context[key].set('unbound',f.entry({sessionKey:undefined,sessionId:undefined}));expectUnknown(f.read());
  }
  const f=fixture();f.context.dedupe.set('agent:unbound',{ok:true,payload:{status:'accepted',runId:'unbound'}});expectUnknown(f.read());
  for(const aliases of [[null],['agent:other:alias'],[target.sessionKey]]) {
    f.context.dedupe.get('agent:unbound').payload.sessionKeyAliases=aliases;expectUnknown(f.read());
  }
});
test('an exact native owner covers incomplete accepted dedupe, while contradictions remain unknown',()=>{
  for(const map of ['chatAbortControllers','chatQueuedTurns']) {
    const f=fixture();f.context[map].set('run',f.entry());
    f.context.dedupe.set('agent:run',{ok:true,payload:{runId:'run',status:'accepted',sessionKey:target.sessionKey}});
    assert.equal(f.read().resident_complete,true);assert.equal(f.read().pending_admission_count,0);
    assert.equal(f.read().active_count+f.read().queued_turn_count,1);
    f.context.dedupe.get('agent:run').payload.sessionId='other-physical-session';expectUnknown(f.read());
  }
});
test('revocation or rebind during the synchronous read discards all counts',()=>{
  const f=fixture();f.context.chatAbortControllers.set('run',f.entry());
  let current=true,checks=0;
  f.native.assertCurrent=()=>{checks++;if(!current)throw new Error('resident authority changed');};
  f.native.isTerminalSettled=()=>{current=false;return true;};
  expectUnknown(f.read());assert.equal(checks,2);
  const g=fixture();g.native.assertCurrent=()=>{throw new Error('cold or retired capture');};
  expectUnknown(g.read());
  const h=fixture();h.context.chatAbortControllers.set('run',h.entry());
  h.native.isTerminalSettled=()=>{h.context.chatQueuedTurns=new Map();return true;};expectUnknown(h.read());
});
test('absent or non-synchronous native evidence cannot qualify a read',()=>{
  const f=fixture();delete f.native.assertCurrent;expectUnknown(f.read());
  for(const key of ['assertCurrent','isGenerationCurrent','isTerminalSettled']) {
    const g=fixture();g.context.chatAbortControllers.set('run',g.entry());
    g.native[key]=()=>Promise.resolve(true);expectUnknown(g.read());
  }
  const h=fixture(),entry=h.entry();entry.controller.abort();
  h.context.chatAbortControllers.set('cancelled-unsettled',entry);expectUnknown(h.read());
});
test('unrelated sessions and settled historical dedupe are excluded',()=>{
  const f=fixture();f.context.chatAbortControllers.set('other',f.entry({sessionKey:'agent:other:fixture',sessionId:'other',agentId:'other'}));
  f.context.dedupe.set('agent:done',{ok:true,payload:{...target,runId:'done',status:'completed'}});
  assert.equal(f.read().active_count,0);assert.equal(f.read().pending_admission_count,0);
});
test('bounded ids keep a complete count; excessive owner inventory is unknown',()=>{
  const f=fixture();for(let i=0;i<70;i++) f.context.chatAbortControllers.set('run-'+i,f.entry());
  assert.equal(f.read().active_count,70);assert.equal(f.read().active_run_ids.length,64);assert.equal(f.read().ids_truncated,true);
  for(let i=0;i<10_001;i++) f.context.dedupe.set('unrelated-'+i,{});expectUnknown(f.read());
});
test('memory read does not open/write files, prepare, reconcile or dispatch',()=>{
  const f=fixture();const entry=f.entry();f.context.chatAbortControllers.set('run',entry);
  const forbidden=()=>{throw new Error('forbidden effect');};
  Object.assign(f.context,{ensureSessionRowProjection:forbidden,prepareMembership:forbidden,
    reconcile:forbidden,dispatch:forbidden,openDatabase:forbidden,write:forbidden});
  const originals=new Map(['openSync','writeFileSync','appendFileSync','mkdirSync'].map(key=>[key,fs[key]]));
  const entries=[...f.context.chatAbortControllers],keys=Reflect.ownKeys(entry),values=keys.map(key=>entry[key]);
  try {
    for(const key of originals.keys()) fs[key]=forbidden;
    assert.equal(f.read().status,'observed');
    assert.deepEqual([...f.context.chatAbortControllers],entries);
    assert.deepEqual(Reflect.ownKeys(entry),keys);assert.deepEqual(keys.map(key=>entry[key]),values);
    assert.equal(f.context.chatQueuedTurns.size,0);assert.equal(f.context.dedupe.size,0);
  } finally {for(const [key,value] of originals) fs[key]=value;}
});
