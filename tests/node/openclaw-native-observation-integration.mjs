/** Offline proof against pinned native function bodies, without a Gateway, DB or credentials. */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {transform,validatePackage} from '../../scripts/openclaw/mission-loader.mjs';
import * as guard from '../../scripts/openclaw/mission-guard.mjs';

const root=process.env.WIKI_TEST_OPENCLAW_CORE_ROOT;
const manifest=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
validatePackage(root,manifest.packages.core);
const sources=new Map(manifest.files.filter(f=>f.observation).map(f=>[f.name,transform(f.name,fs.readFileSync(path.join(root,f.relative),'utf8'))]));
const read=name=>sources.get(name)??fs.readFileSync(path.join(root,'dist',name),'utf8');
function nativeClass(file,name,deps) {
  const source=read(file),start=source.indexOf('class {',source.indexOf(`var ${name} = class`));
  assert.ok(start>=0,name);
  return expression(source,start).runInNewContext({Map,Set,Date,Promise,AbortController,process,Buffer,console,...deps});
}
function expression(source,start,prefix='(',suffix=')') {
  for(let end=source.indexOf('\n}',start);end>=0;end=source.indexOf('\n}',end+2)) {
    try {return new vm.Script(prefix+source.slice(start,end+2)+suffix);}catch(error){if(!(error instanceof SyntaxError))throw error;}
  }
  throw new Error('native_function_shape_changed');
}
function nativeFunction(file,name,deps) {
  const source=read(file), marker=`function ${name}(`, index=source.indexOf(marker);
  assert.ok(index>=0,name);
  const start=source.slice(index-6,index)==='async '?index-6:index;
  return expression(source,start).runInNewContext({Map,Set,Date,Promise,AbortController,process,Buffer,console,...deps});
}
const effects={domain:[],security:[]};
const forbidden=name=>(..._args)=>{effects.domain.push(name);throw new Error('forbidden_domain_effect:'+name);};
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'native-observation-proof-'));
process.on('exit',()=>fs.rmSync(temp,{recursive:true,force:true}));
const security=event=>{effects.security.push(event);fs.appendFileSync(path.join(temp,'security.log'),JSON.stringify(event)+'\n');};
const cap=guard.RESIDENT_OBSERVATION_CAPABILITY;
const client={connect:{client:{id:'cli',mode:'cli'},role:'operator',scopes:['operator.read'],caps:['ultrafast',cap],auth:{token:'synthetic-fixture'}},
  internal:{operatorRoleActor:{kind:'system'},authenticatedOperator:true,isLocalClient:true},usesSharedGatewayAuth:true,
  authPolicy:{},connectionSignal:new AbortController().signal};
const requestContext={getRuntimeConfig:()=>cfg};
const cfg={gateway:{auth:{mode:'token'}}};
const frames=[];
const context={connectParams:client.connect,configSnapshot:cfg,frame:{id:'fixture-connect'},pendingNodePairingCleanup:{},
  isLocalClient:true,sendFrame:async frame=>frames.push(frame),onHelloDelivered:()=>security({event:'hello-delivered'}),
  handler:{connId:'fixture-connection',bootId:'fixture-boot',gatewayMethods:['sessions.describe'],events:[],
    buildRequestContext:()=>requestContext,getClient:()=>client,getResolvedAuth:()=>({mode:'token'}),
    remoteAddr:'127.0.0.1',isClosed:()=>false,connectionWork:{signal:new AbortController().signal},
    advanceHandshakePhase:phase=>security({phase}),logGateway:{warn:message=>security({message})},
    refreshHealthSnapshot:forbidden('refreshHealthSnapshot')}};
const state={role:'operator',scopes:['operator.read'],resolvedAuth:{mode:'token'},authMethod:'token',
  authResult:{},hasTokenAuth:true,sessionUsesSharedGatewayAuth:true};
const hello=nativeFunction('message-handler-a7VR9SDC.mjs','sendGatewayHello',{
  wikiMissionGuard:guard,sha256Base64Url:()=> 'synthetic-scope',getSessionRowProjection:forbidden('getSessionRowProjection'),
  buildGatewaySnapshot:forbidden('buildGatewaySnapshot'),getHealthCache:()=>null,getHealthVersion:()=>1,wikiObservationPresenceVersion:()=>1,
  listControlUiPluginTabs:forbidden('listControlUiPluginTabs'),listControlUiPluginWidgetKinds:forbidden('listControlUiPluginWidgetKinds'),
  listControlUiLinkReaders:forbidden('listControlUiLinkReaders'),hasMultipleSessionSharingIdentities:forbidden('openProfileDatabase'),
  resolveControlUiLinkLocation:()=>undefined,resolveRuntimeServiceBuildId:()=>undefined,resolveRuntimeServiceVersion:()=> 'fixture',
  operatorSessionCap:()=>undefined,resolveBrowserAuthOrigin:()=>undefined,SYSTEM_RUN_EXECUTION_CONTEXT_CAPABILITY:'fixture',
  GATEWAY_SERVER_CAPS:new Proxy({}, {get:(_target,key)=>String(key)}),MAX_PAYLOAD_BYTES:10000,MAX_BUFFERED_BYTES:10000,TICK_INTERVAL_MS:1000,
  resolveChatAttachmentPolicy:()=>({}),allowedSessionVisibilities:()=>['shared'],resolveControlUiIdentity:()=>undefined,
  getGatewaySuspendAdmissionPhase:()=> 'active',emitGatewayAuthSecurityEvent:security,logWs:(...event)=>security({event}),
  shouldScheduleBackgroundHealthRefresh:forbidden('scheduleHealthRefresh')
});
try {
  await hello(context,state,{},undefined);
  assert.equal(frames.length,1);assert.equal(frames[0].ok,true);assert.deepEqual(Array.from(frames[0].payload.snapshot.presence),[]);
  assert.equal(effects.domain.length,0);
  assert.ok(effects.security.some(event=>event.action==='gateway.auth.succeeded'));
  assert.ok(effects.security.some(event=>event.event?.[1]==='hello-ok'));
  assert.ok(fs.statSync(path.join(temp,'security.log')).size>0,'security writes are allowed and observed, never silenced');
  console.log('native hello: domain preparation absent; native security events/log sink preserved');
} finally {assert.equal(effects.domain.length,0);}

// Execute the real outer and inner constructors, including removal of
// sharedStateMode and normalization of null deviceIdentity. No socket is opened.
let inner;
const Inner=nativeClass('client-DZgDBpiJ.mjs','GatewayClient$1',{
  wikiMissionGuard:guard,resolveHostDeps:deps=>deps,
  GatewayClientDeviceAuth:class {load=forbidden('loadDeviceAuth');},
  GatewayProtocolClient:class {constructor(options){this.options=options;}},
  resolveConnectChallengeTimeoutMs:()=>1000,DEFAULT_GATEWAY_REQUEST_TIMEOUT_MS:5000,randomUUID:()=> 'fixture-request'
});
const Outer=nativeClass('client-DZgDBpiJ.mjs','GatewayClient',{
  wikiMissionGuard:guard,GatewayClient$1:class extends Inner {constructor(opts){super(opts);inner=this;}},
  resolveGatewayClientPlatformIdentity:()=>({platform:'fixture',deviceFamily:'fixture'}),shouldSuppressStoredDeviceAuth:()=>true,
  registerSecretValueForRedaction:()=>{},normalizeDeviceAuthRole:role=>role,
  loadDeviceAuthToken:forbidden('loadDeviceAuthToken'),loadDeviceAuthTokenReadOnly:forbidden('loadDeviceAuthTokenReadOnly'),
  signEd25519Payload:forbidden('signDevicePayload'),publicKeyRawBase64UrlFromEd25519Pem:forbidden('devicePublicKey'),
  ensureInheritedManagedProxyRoutingActive:()=>{},registerManagedProxyGatewayLoopbackBypass:()=>{},
  logDebug:()=>{},logError:()=>{},redactToolPayloadText:value=>value,VERSION:'fixture'
});
const nativeClientOptions={caps:[cap],deviceIdentity:null,sharedStateMode:'read-only',clientName:'cli',mode:'cli',url:'ws://127.0.0.1:19880'};
new Outer(nativeClientOptions);
assert.equal(inner.opts.deviceIdentity,undefined);assert.equal(inner.opts.sharedStateMode,undefined);
let assembled=0;
inner.assembleConnectParams=()=>{assembled++;return {params:client.connect};};
const challenge={nonce:'synthetic-nonce',challengeTs:1,generation:1,assertCurrent:()=>{}};
assert.throws(()=>inner.protocol.options.buildConnectPlan({...challenge,serverCapabilities:[]}));
assert.equal(assembled,0);
inner.protocol.options.buildConnectPlan({...challenge,serverCapabilities:[cap]});
assert.equal(assembled,1);assert.equal(effects.domain.length,0);
assert.throws(()=>new Outer({...nativeClientOptions,deviceIdentity:undefined}));
console.log('native client: pre-connect capability fence survives both wrapper normalizations');

const physical={agentId:'example',sessionKey:'agent:example:fixture',sessionId:'fixture-session'};
const entry={sessionId:physical.sessionId,lifecycleRevision:1};
const membership=new Set(['synthetic-member']),generation=Symbol('generation');
const projection={sharingRevision:1,getPolicyConfig:()=>cfg,sharingTargetState:()=>({status:'ready',target:{
  canonicalKey:physical.sessionKey,agentId:physical.agentId,generation,entry}}),
  readSource:()=>({agentId:physical.agentId,path:'/synthetic/session.sqlite',databaseIdentity:'fixture',databaseBirthtime:1}),
  readMembership:()=>new Set(membership)};
Object.assign(requestContext,{getCommittedRuntimeConfig:()=>cfg,chatAbortControllers:new Map(),chatQueuedTurns:new Map(),dedupe:new Map(),
  ensureSessionRowProjection:forbidden('ensureSessionRowProjection')});
const policyCalls=[];
const nativeMethod=nativeFunction('request-authorization-jFWXJ1Lv.mjs','authorizeGatewayMethod',{
  parseGatewayRole:value=>value,isRoleAuthorizedForMethod:()=>true,resolveGatewayOperatorRoleActor:()=>({kind:'system'}),
  isOperatorScope:value=>value==='operator.read',resolveSessionMethodScope:()=> 'operator.sessions.read',
  authorizeOperatorScopesForRequiredScope:(_scope,scopes)=>{policyCalls.push('scopes');return {allowed:scopes.includes('operator.read'),missingScope:'operator.read'};},
  isInProcessSessionRun:()=>false,resolveLeastPrivilegeOperatorScopesForMethod:()=>['operator.read'],missingScopeErrorShape:value=>({code:'FORBIDDEN',...value}),
  errorShape:(code,message)=>({code,message}),ErrorCodes:{INVALID_REQUEST:'INVALID_REQUEST',FORBIDDEN:'FORBIDDEN'}
});
const nativeProfile=nativeFunction('gateway-client-identity-C-9Xwi8i.mjs','authorizeAuthenticatedProfileForMethod',{
  resolveGatewayOperatorRoleActor:()=>({kind:'system'}),ErrorCodes:{FORBIDDEN:'FORBIDDEN'},errorShape:(code,message)=>({code,message})
});
const prepareSharing=()=>{policyCalls.push('visibility');return {entryFilter:()=>true};};
const resolveAgent=(_cfg,key,id)=>({ok:key===physical.sessionKey && id===physical.agentId,agentId:id});
const nativeDescribe=nativeFunction('session-sharing-BFM0s33P.mjs','authorizeSessionDescribe',{
  resolveDirectSessionTargets:(_method,params)=>[{sessionKey:params.key,agentId:params.agentId}],resolveRequestedSessionAgentId:resolveAgent,
  prepareProjectedSessionSharing:prepareSharing,gatewayClientSessionCreator:()=>undefined
});
const nativeSession=nativeFunction('session-sharing-BFM0s33P.mjs','resolveSessionMutationAuthorization',{
  isAgentRunStartMethod:()=>false,resolveSessionMethodScope:()=> 'operator.sessions.read',isSessionArchiveMutation:()=>false,
  isGatewayAdmin:()=>false,isGatewayClientProfilePending:()=>false,authorizeSessionDescribe:nativeDescribe
});
const preDispatch=nativeFunction('request-authorization-jFWXJ1Lv.mjs','authorizeGatewayRequestPreDispatch',{
  wikiMissionGuard:guard,withPluginRuntimeRegistryScope:(_registry,run)=>run(),authorizeGatewayMethod:nativeMethod,
  gatewayRouterUploadPolicyError:()=>null,authorizeAuthenticatedProfileForMethod:nativeProfile,
  getSessionRowProjection:()=>projection,isIncognitoSessionKey:()=>false,resolveRequestedSessionAgentId:resolveAgent,
  wikiObservationPermissionPending:()=>false,resolveSessionMutationAuthorization:nativeSession,
  wikiObservationAuthorizeIncognito:()=>null,wikiObservationPrepareSharing:prepareSharing,wikiObservationHasBoundary:()=>false,
  getAsyncWorkSignal:forbidden('ordinaryPreDispatch')
});
const params={key:physical.sessionKey,agentId:physical.agentId,wikiObservation:{version:1,sessionId:physical.sessionId}};
const methodRegistry={isObservation:()=>true,getScope:()=> 'operator.read',requiresAuthenticatedProfile:()=>false};
const authorization=await preDispatch({method:'sessions.describe',requestParams:params,client,context:requestContext,
  hasCurrentClientAuthority:()=>true,methodRegistry});
assert.equal(authorization.error,null);assert.ok(policyCalls.includes('scopes'));assert.ok(policyCalls.includes('visibility'));
const source=read('sessions-read-DenbZWtx.mjs'),start=source.indexOf('{',source.indexOf('const sessionByKeyReadHandlers ='));
const handlers=expression(source,start).runInNewContext({wikiMissionGuard:guard,
  wikiObservationGenerationCurrent:()=>true,wikiObservationTerminalSettled:()=>true,wikiObservationProcessInstanceId:()=> 'fixture-process',
  requireSessionRowProjection:forbidden('requireSessionRowProjection'),withReadySessionRows:forbidden('withReadySessionRows'),
  assertValidParams:forbidden('ordinarySessionPresentation')});
let payload;
await handlers['sessions.describe']({params,client,context:requestContext,wikiObservationAuthorization:authorization.wikiObservationAuthorization,
  respond:(ok,value)=>{assert.equal(ok,true);payload=value;}});
assert.equal(payload.status,'observed');assert.equal(payload.complete,false);assert.equal(payload.sessionId,physical.sessionId);
client.connect.scopes=[];
assert.throws(()=>authorization.wikiObservationAuthorization.assertCurrent());
const refused=await preDispatch({method:'sessions.describe',requestParams:params,client,context:requestContext,
  hasCurrentClientAuthority:()=>true,methodRegistry});
assert.equal(refused.error.code,'FORBIDDEN');assert.equal(effects.domain.length,0);
console.log('native preDispatch and sessions.describe: scopes/visibility retained, exact resident response, revocation enforced');

client.connect.scopes=['operator.read'];
Object.assign(context.handler,{upgradeReq:{headers:{}},setCloseCause:(...event)=>security({event}),
  close:(...event)=>security({event}),logWsControl:{warn:message=>security({message})}});
Object.assign(context,{markHandshakeFailure:(...event)=>security({event}),sendHandshakeErrorResponse:(...event)=>security({event})});
let credentialChecks=0;
const authDeps={
  admitGatewayConnect:async()=>({role:'operator',scopes:['operator.read'],isControlUi:false,startupPending:false}),
  resolveConnectAuthState:async({connectAuth})=>{credentialChecks++;const ok=connectAuth.token==='synthetic-fixture';
    return {authOk:ok,sharedAuthOk:ok,authMethod:'token',authResult:ok?{}:{reason:'token_mismatch'}};},
  resolveConnectAuthDecision:async({state})=>state,resolvePairingLocality:()=> 'local-direct',
  shouldSkipLocalBackendSelfPairing:()=>false,shouldPreserveLocalCliSharedAuthScopes:()=>true,
  isTrustedProxyControlUiOperatorAuth:()=>false,evaluateMissingDeviceIdentity:({authOk})=>({kind:authOk?'allow':'reject-unauthorized'}),
  verifyGatewayConnectDeviceProof:nativeFunction('message-handler-a7VR9SDC.mjs','verifyGatewayConnectDeviceProof',{}),
  verifyDeviceBootstrapToken:forbidden('verifyDeviceBootstrapToken'),verifyDeviceToken:forbidden('verifyDeviceToken'),
  resolveSharedGatewaySessionGeneration:()=> 'fixture-generation',shouldSkipControlUiPairing:()=>null,
  captureGatewayAuthPolicy:()=>client.authPolicy,resolveUnauthorizedHandshakeContext:()=>({authProvided:'token',recommendedNextStep:'check-config'}),
  emitGatewayAuthSecurityEvent:security,formatGatewayAuthFailureMessage:()=> 'invalid credentials',shouldLimitMissingCredentialAuthLog:()=>false,
  formatForLog:String,truncateCloseReason:String,ErrorCodes:{INVALID_REQUEST:'INVALID_REQUEST'},resolveAuthConnectErrorDetailCode:()=> 'TOKEN_MISMATCH'
};
const authCore=nativeFunction('message-handler-a7VR9SDC.mjs','authenticateGatewayConnectCore',authDeps);
const auth=nativeFunction('message-handler-a7VR9SDC.mjs','authenticateGatewayConnect',{authenticateGatewayConnectCore:authCore});
guard.assertResidentObservationConnect(context);
const authenticated=await auth(context);
guard.assertResidentObservationConnect(context,authenticated);
assert.equal(credentialChecks,1);assert.equal(authenticated.authMethod,'token');
const tokens=nativeFunction('message-handler-a7VR9SDC.mjs','issueGatewayConnectDeviceTokens',{ensureDeviceToken:forbidden('issueDeviceToken')});
const deviceAuth=nativeFunction('message-handler-a7VR9SDC.mjs','authorizeGatewayConnectDevice',{
  normalizeNodeHostCompatibilityMetadata:value=>value,isBrowserCopilotClient:()=>false,issueGatewayConnectDeviceTokens:tokens
});
const authorized=await deviceAuth(context,authenticated);
guard.assertResidentObservationConnect(context,authorized);
assert.equal(authorized.deviceToken,null);assert.deepEqual(Array.from(authorized.bootstrapDeviceTokens),[]);
client.connect.auth.token='synthetic-wrong';
assert.equal(await auth(context),undefined);
assert.equal(credentialChecks,2);assert.ok(effects.security.some(event=>event.action==='gateway.auth.failed'));
client.connect.auth.token='synthetic-fixture';
assert.equal(effects.domain.length,0);
console.log('native authentication/device authorization: existing credentials checked, rejection audited, no pairing or token issuance');

const coreHandler=handlers['sessions.describe'];
Object.assign(methodRegistry,{getHandler:()=>coreHandler,getReadSharing:()=>undefined});
let operatorChecks=0;
const authority={assertCurrent:()=>{operatorChecks++;},assertPreparationCurrent:()=>{operatorChecks++;}};
const router=nativeFunction('server-methods-BgKN9CSB.mjs','handleGatewayRequest',{
  wikiMissionGuard:guard,coreGatewayHandlers:{'sessions.describe':coreHandler},getAsyncWorkSignal:()=>new AbortController().signal,
  _usingCtx:()=>({u:value=>value,e:null,d(){if(this.e)throw this.e;}}),
  resolveRuntimeSessionParticipantRequest:()=>undefined,createExpectedProfileBinding:forbidden('createExpectedProfileBinding'),
  retainSessionListForegroundWork:()=>()=>{},readGatewayRequestMutationAuthority:()=>authority,
  isGatewayClientProfilePending:()=>false,captureGatewayRequestOperatorGuard:()=>()=>{operatorChecks++;},
  authorizeGatewayRequestPreDispatch:preDispatch,composeSessionSourceAssertion:()=>()=>{},withSessionMutationCommitGuard:()=>undefined,
  prepareGatewayRequestHandler:nativeFunction('lazy-core-handlers-D2IxYK_e.mjs','prepareGatewayRequestHandler',{preparations:new WeakMap()}),
  gatewayRouterUploadPolicyError:()=>null,bindGatewayRequestHandlerMutationAuthority:(_opts,handlerOptions)=>handlerOptions,
  bindChatSendDiagnostics:()=>{},GatewayRpcDiagnostics:{runHandler:run=>run()},
  runWithGatewayRequestEnvelope:async(_method,_client,run)=>await run(),runWithGatewayObservationScope:async(_method,run)=>await run(),
  dispatchSharedRead:forbidden('dispatchSharedRead'),AgentDatabaseAdmissionError:class extends Error {},
  SessionMutationAuthorizationChangedError:class extends Error {}
});
const options={req:{method:'sessions.describe',params},client,context:requestContext,methodRegistry,
  isWebchatConnect:p=>p.client.mode==='webchat',hasCurrentClientAuthority:()=>true,acceptsSerializedJson:true,
  respond:(ok,value)=>{assert.equal(ok,true);payload=value;}};
payload=undefined;
await router(options);
assert.equal(payload.status,'observed');assert.ok(operatorChecks>0);assert.equal(effects.domain.length,0);
await assert.rejects(router({...options,req:{...options.req,expectedProfileId:'synthetic-human'}}));
await assert.rejects(router({...options,methodRegistry:{...methodRegistry,getReadSharing:()=>({})}}));
await assert.rejects(router({...options,methodRegistry:{...methodRegistry,getHandler:()=>()=>{throw new Error('override');}}}));
assert.equal(effects.domain.length,0);
console.log('native router: complete policy-to-handler envelope; profile prep, overrides and shared-read refused');
