/** Qualifies code through the native original/artifact/instance relationship. */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=(ok,code)=>{if(!ok)throw new Error(`wiki_mission_${code}`);};
export class NativeCaptureRegistry {
  constructor({pluginRoot,coreRoot,files,validatePackage}) {
    Object.assign(this,{pluginRoot,coreRoot,files,validatePackage});
    this.roots=new Map();this.capabilities=new WeakSet();
  }
  register(params,artifact,readInstance) {
    if(params.instance?.pluginId!=='codex')return ()=>{};
    require(fs.realpathSync(params.rootDir)===this.pluginRoot && params.rootDir===this.pluginRoot,'capture_original_root');
    require(typeof readInstance==='function' && typeof params.instance.onModuleDispose==='function','capture_owner_missing');
    const packageFile=artifact.resolve(path.join(this.pluginRoot,'package.json'));
    const root=path.dirname(packageFile);
    require(root!==this.pluginRoot && fs.realpathSync(root)===root,'capture_root');
    this.validatePackage(root);
    const sdk=fs.realpathSync(createRequire(packageFile).resolve('openclaw/plugin-sdk/process-runtime'));
    require(sdk.startsWith(this.coreRoot+path.sep),'capture_sdk_changed');
    for(const f of this.files) {
      const original=path.join(this.pluginRoot,f.relative), captured=path.join(root,f.relative);
      require(artifact.resolve(original)===captured && artifact.sourceForCaptured(captured)===original && artifact.moduleRoot(captured)===root && fs.realpathSync(captured)===captured,'capture_round_trip');
      artifact.assertModuleAvailable(captured);
    }
    // Do not publish a partly checked registration. A retained artifact may be
    // shared by several native instances; disposal removes only its association.
    let entry=this.roots.get(root);
    if(!entry){entry={root,owners:new Map(),loaded:new Set()};this.roots.set(root,entry);}
    require(!entry.owners.has(params.instance),'capture_owner_duplicate');
    const record={instance:params.instance,artifact,readInstance,entry,active:true};
    entry.owners.set(params.instance,record);
    return ()=>{record.active=false;entry.owners.delete(params.instance);};
  }
  module(file) {
    for(const entry of this.roots.values()) {
      const f=this.files.find(f=>path.join(entry.root,f.relative)===file);
      if(f) {
        require(entry.owners.size>0 && fs.realpathSync(file)===file,'capture_retired');
        for(const record of entry.owners.values()) {
          record.artifact.assertModuleAvailable(file);
          require(record.artifact.sourceForCaptured(file)===path.join(this.pluginRoot,f.relative),'capture_origin_changed');
        }
        return {entry,spec:f};
      }
    }
    return null;
  }
  loaded(name,url) {
    if(!url?.startsWith('file:'))return;
    const found=this.module(fileURLToPath(url));
    if(found){require(found.spec.name===name,'capture_hook_mismatch');found.entry.loaded.add(name);}
  }
  capture(url) {
    require(typeof url==='string' && url.startsWith('file:') && !new URL(url).search && !new URL(url).hash,'capture_url');
    const found=this.module(fileURLToPath(url));require(found,'capture_unqualified_code');
    const {entry,spec}=found;
    const current=new Set([...entry.owners.values()].map(r=>r.readInstance()));
    require(current.size===1,'capture_owner_ambiguous');
    const instance=[...current][0], record=entry.owners.get(instance);
    require(record,'capture_wrong_owner');
    // Native route/catalog setup may load inference before the turn module.
    // Capture identity now; execution still requires every hook in assert().
    require(entry.loaded.has(spec.name),'capture_hook_not_loaded');
    const cap=Object.freeze({record,instance,hook:spec.name});this.capabilities.add(cap);
    this.assert(cap,false);return cap;
  }
  assert(cap,runtime=true,hook) {
    require(cap && this.capabilities.has(cap),'capture_capability_required');
    const {record,instance}=cap;
    require(record.active && record.entry.owners.get(instance)===record && !instance.owner?.revoked && instance.accepting===true && !instance.replacementReserved && !instance.forcedRetirement && instance.lifecycle?.signal?.aborted===false,'capture_owner_retired');
    if(hook)require(cap.hook===hook && record.entry.loaded.has(hook),'capture_role_hook_required');
    else if(runtime)require(this.files.every(f=>record.entry.loaded.has(f.name)),'capture_hooks_incomplete');
    if(runtime)require(instance.owner?.instance===instance && instance.owner.record?.id==='codex' && instance.runtimeScope?.pluginTrustedOfficialInstall===true && typeof instance.owner.record.source==='string' && fs.realpathSync(instance.owner.record.source).startsWith(this.pluginRoot+path.sep),'capture_runtime_owner_required');
  }
}
let registry;
export function configureNativeRegistry(value){require(!registry,'capture_registry_already_configured');registry=value;}
export function registerNativeArtifact(params,artifact,readInstance){require(registry,'capture_registry_required');return registry.register(params,artifact,readInstance);}
export function qualifyNativeModule(file){return registry?.module(file);}
export function markNativeHook(name,url){registry?.loaded(name,url);}
export function captureOwner(url){require(registry,'capture_registry_required');return registry.capture(url);}
export function assertOwner(cap,hook){require(registry,'capture_registry_required');registry.assert(cap,true,hook);}
export function assertCapture(cap,hook){require(registry,'capture_registry_required');registry.assert(cap,false,hook);}

/** Read the existing Gateway owners only. Native callbacks must be synchronous,
 * pure, and bound to the authorized resident session. assertCurrent must throw
 * on changed identity/authority. This helper neither implements authorization
 * nor makes RPC/handshake pure; it is not exposed by the CLI or the GET.
 * These maps cannot establish global activity or persisted queue completeness.
 */
export function readResidentNativeActivity(context,target,native) {
  const scope={scope:'resident_gateway_owners',complete:false,persisted_queue_count:null};
  const unavailable=()=>({...scope,status:'unavailable',has_active_run:null,active_run_ids:null,
    active_count:null,terminal_persistence_count:null,terminal_cleanup_count:null,queued_turn_count:null,
    pending_admission_count:null,resident_complete:false,ids_truncated:false,
    error_code:'native_activity_unproven'});
  const maps=[context?.chatAbortControllers,context?.chatQueuedTurns,context?.dedupe];
  if(!target || typeof target.agentId!=='string' || !/^[a-z][a-z0-9_-]{0,63}$/.test(target.agentId)
      || typeof target.sessionKey!=='string' || !target.sessionKey.startsWith(`agent:${target.agentId}:`)
      || target.sessionKey.length>240 || /\s/.test(target.sessionKey)
      || typeof target.sessionId!=='string' || !target.sessionId || target.sessionId.length>240 || /\s/.test(target.sessionId)
      || !maps.every(value=>value instanceof Map && value.size<=10_000)
      || typeof native?.assertCurrent!=='function' || typeof native.isGenerationCurrent!=='function'
      || typeof native.isTerminalSettled!=='function') return unavailable();
  const {agentId,sessionKey,sessionId}=target;
  const [activeOwners,queuedOwners,admissions]=maps;
  const active=new Set(),terminal=new Set(),cleanup=new Set(),queued=new Set(),pending=new Set();
  const registrations=new Map();
  const addressable=entry=>[entry?.sessionKey,entry?.sessionId].some(value=>typeof value==='string' && value.trim()!=='' );
  const matches=entry=>entry?.sessionKey===sessionKey || entry?.sessionId===sessionId;
  const exact=entry=>entry?.sessionKey===sessionKey && entry?.sessionId===sessionId
    && (entry.agentId===agentId || entry.agentId===undefined);
  const validId=id=>typeof id==='string' && /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,239}$/.test(id);
  const assertCurrent=()=>{
    if(native.assertCurrent()!==undefined || target.agentId!==agentId || target.sessionKey!==sessionKey
        || target.sessionId!==sessionId || context.chatAbortControllers!==activeOwners
        || context.chatQueuedTurns!==queuedOwners || context.dedupe!==admissions) throw new Error('observation_changed');
  };
  try {
    assertCurrent();
    for(const [id,entry] of activeOwners) {
      if(!addressable(entry)) return unavailable();
      if(!matches(entry)) continue;
      if(!validId(id) || !exact(entry) || !entry.controller?.signal
          || entry.lifecycleGeneration===undefined || native.isGenerationCurrent(entry.lifecycleGeneration)!==true) return unavailable();
      registrations.set(id,entry);
      const settled=native.isTerminalSettled(entry);
      if(typeof settled!=='boolean') return unavailable();
      const settling=entry.terminalOutcomeObserved===true || entry.registrationCleanupRequested===true
        || entry.projectSessionTerminalObservedAt!==undefined;
      if(!settled) terminal.add(id);
      else if(settling) cleanup.add(id);
      else if(entry.controller.signal.aborted) return unavailable();
      else if(entry.executionStarted===true) active.add(id);
      else if(entry.executionStarted===false) pending.add(id);
      else return unavailable();
    }
    for(const [id,entry] of queuedOwners) {
      if(!addressable(entry)) return unavailable();
      if(!matches(entry)) continue;
      if(!validId(id) || !exact(entry) || !entry.controller?.signal) return unavailable();
      // Cancellation ownership may have moved to a collect aggregate. The
      // native entry remains queued until completeQueuedChatTurn removes it.
      if(registrations.has(id) && registrations.get(id).controller!==entry.controller) return unavailable();
      // A final reply can await persistence while its independent queue owner
      // remains. No single phase is proved; neither owner may imply queue zero.
      if(terminal.has(id) || cleanup.has(id)) return unavailable();
      registrations.set(id,entry);
      if(!active.has(id) && !terminal.has(id) && !cleanup.has(id)) {pending.delete(id);queued.add(id);}
    }
    for(const [key,entry] of admissions) {
      if(typeof key!=='string' || !['agent:','pending-chat:'].some(prefix=>key.startsWith(prefix))
          || entry?.ok!==true || entry.payload?.status!=='accepted') continue;
      const payload=entry.payload;
      const prefix=key.startsWith('agent:')?'agent:':'pending-chat:';
      const id=payload.runId ?? key.slice(prefix.length);
      if(!validId(id) || key.slice(prefix.length)!==id) return unavailable();
      const aliases=Array.isArray(payload.sessionKeyAliases)?payload.sessionKeyAliases:[];
      if(aliases.length>64) return unavailable();
      // Native accepted payloads can omit sessionId. A matching already
      // qualified owner covers that run, but contradictory facts fail closed.
      if(registrations.has(id)) {
        if((payload.sessionKey!==undefined && payload.sessionKey!==sessionKey)
            || (payload.sessionId!==undefined && payload.sessionId!==sessionId)
            || (payload.agentId!==undefined && payload.agentId!==agentId)) return unavailable();
        continue;
      }
      if(!addressable(payload)) return unavailable();
      if(!matches(payload) && !aliases.includes(sessionKey)) continue;
      // An alias or incomplete retained payload cannot prove the physical
      // identity of pending work. Never turn that uncertainty into zero.
      if(!exact(payload)) return unavailable();
      if(!active.has(id) && !terminal.has(id) && !cleanup.has(id) && !queued.has(id)) pending.add(id);
    }
    assertCurrent();
    const ids=[...active].sort();
    return {...scope,status:'observed',has_active_run:active.size>0,active_run_ids:ids.slice(0,64),
      active_count:active.size,terminal_persistence_count:terminal.size,terminal_cleanup_count:cleanup.size,
      queued_turn_count:queued.size,pending_admission_count:pending.size,resident_complete:true,
      ids_truncated:ids.length>64,error_code:null};
  } catch {
    return unavailable();
  }
}

// This capability narrows a native authenticated connection. It is neither an
// identity nor a grant. Native auth, scope checks and security logging still run.
export const RESIDENT_OBSERVATION_CAPABILITY='wiki.resident-observation.v1';
const observationRequire=(ok)=>{if(!ok)throw new Error('wiki_observation_unavailable');};
const record=value=>value!==null && typeof value==='object' && !Array.isArray(value);
const exactKeys=(value,keys)=>record(value) && Object.keys(value).sort().join(',')===keys;
const boundedIdentity=value=>typeof value==='string' && value.length>0 && value.length<=240
  && value.trim()===value && !/[\x00-\x20\x7f]/.test(value);
export const hasResidentObservation=params=>record(params) && Object.hasOwn(params,'wikiObservation');
export const isResidentObservationConnect=params=>Array.isArray(params?.caps) && params.caps.includes(RESIDENT_OBSERVATION_CAPABILITY);
export function validateResidentObservation(method,params) {
  observationRequire(method==='sessions.describe' && exactKeys(params,'agentId,key,wikiObservation')
    && exactKeys(params.wikiObservation,'sessionId,version') && params.wikiObservation.version===1
    && boundedIdentity(params.agentId) && /^[a-z0-9][a-z0-9_-]*$/.test(params.agentId)
    && boundedIdentity(params.key) && params.key.startsWith(`agent:${params.agentId}:`)
    && !params.key.includes(':incognito:') && boundedIdentity(params.wikiObservation.sessionId));
  return {agentId:params.agentId,sessionKey:params.key,sessionId:params.wikiObservation.sessionId};
}
export function assertResidentObservationChallenge(options,capabilities) {
  if(!isResidentObservationConnect(options)) return;
  observationRequire(Array.isArray(capabilities) && capabilities.includes(RESIDENT_OBSERVATION_CAPABILITY)
    && options.deviceIdentity===null && options.mode==='cli' && options.clientName==='cli'
    && options.sharedStateMode==='read-only');
}
export function residentObservationClientGuard(options) {
  if(!isResidentObservationConnect(options))return;
  const check=capabilities=>assertResidentObservationChallenge(options,capabilities);
  check([RESIDENT_OBSERVATION_CAPABILITY]);
  return check;
}
export function checkResidentObservationClientChallenge(options,capabilities) {
  if(!isResidentObservationConnect(options))return;
  observationRequire(typeof options.wikiObservationChallengeGuard==='function');
  options.wikiObservationChallengeGuard(capabilities);
}
/** Called before config fallback and again before native credential bootstrap. */
export function assertResidentObservationCall(input,facts) {
  if(!isResidentObservationConnect(input))return;
  validateResidentObservation(input.method,input.params);
  observationRequire(record(input.config) && input.clientName==='cli' && input.mode==='cli'
    && input.deviceIdentity===null && input.sharedStateMode==='read-only'
    && !input.url && !input.token && !input.password && !input.useStoredDeviceAuth && !input.preparedDeviceAuth
    && !input.approvalRuntimeToken && !input.agentRuntimeIdentityToken && !input.serviceTargetUrl
    && !input.localPortOverride && !input.ignoreEnvUrlOverride && !input.skipImplicitAuth
    && input.config.gateway?.mode!=='remote' && !input.config.gateway?.remote
    && input.config.gateway?.tls?.enabled!==true);
  const url=new URL(input.expectUrl);
  observationRequire(url.protocol==='ws:' && ['127.0.0.1','[::1]'].includes(url.hostname)
    && url.port && !url.username && !url.password && !url.search && !url.hash && ['','/'].includes(url.pathname));
  if(facts) {
    observationRequire(!facts.urlOverrideSource && ['token','password'].includes(facts.authMode)
      && facts.secretRefCanWin===false);
    const auth=facts.readCredentials();
    observationRequire(typeof auth[facts.authMode]==='string' && Boolean(auth[facts.authMode].trim()));
  }
}
export function assertResidentObservationConnect(context,state) {
  const p=context.connectParams;
  if(!isResidentObservationConnect(p))return;
  const allowed=new Set(['minProtocol','maxProtocol','client','role','scopes','caps','auth','locale','userAgent']);
  observationRequire(Object.keys(p).every(k=>allowed.has(k)) && p.role==='operator'
    && p.client?.id==='cli' && p.client?.mode==='cli' && context.isLocalClient===true
    && ['127.0.0.1','::1','::ffff:127.0.0.1'].includes(context.handler.remoteAddr)
    && !context.hasProxyHeaders && !context.hasBrowserOriginHeader && !context.browserOrigin
    && Array.isArray(p.caps) && p.caps.every(c=>c==='ultrafast'||c===RESIDENT_OBSERVATION_CAPABILITY)
    && record(p.auth) && Object.keys(p.auth).every(k=>k==='token'||k==='password')
    && Boolean(p.auth.token||p.auth.password)
    && ['token','password'].includes(context.handler.getResolvedAuth().mode));
  context.handler.connectionWork.signal.throwIfAborted();
  observationRequire(!context.handler.isClosed() && !context.pendingNodePairingCleanup?.value);
  if(state) observationRequire(state.role==='operator' && ['token','password'].includes(state.authMethod)
    && !state.device && !state.deviceToken && !state.bootstrapTokenCandidate && !state.issuedBootstrapProfile
    && !state.handoffBootstrapProfile && !state.authResult?.user && !state.authResult?.tailscaleIdentity
    && state.sessionUsesSharedGatewayAuth===true);
}
/** Runs before both native expected-profile preparations. No client fabrication. */
export function assertResidentObservationRequest(req,client,options={}) {
  if(!hasResidentObservation(req?.params) && !isResidentObservationConnect(client?.connect))return;
  validateResidentObservation(req.method,req.params);
  observationRequire(!Object.hasOwn(req,'expectedProfileId') && !options.expectedProfileBinding
    && !options.prepareDispatchCurrent
    && (options.isWebchatConnect===undefined || typeof options.isWebchatConnect==='function' && options.isWebchatConnect(client.connect)===false)
    && isResidentObservationConnect(client?.connect) && client.connect.client?.id==='cli'
    && client.connect.client?.mode==='cli' && client.connect.role==='operator' && !client.connect.device
    && client.usesSharedGatewayAuth===true && client.internal?.operatorRoleActor?.kind==='system'
    && client.internal.authenticatedOperator===true && client.internal.isLocalClient===true
    && !client.internal.syntheticClient && !client.internal.operatorRunAuthority && !client.internal.agentRuntimeIdentity
    && !client.authenticatedGitHubIdentitySync && !client.authenticatedUserProfile && !client.authenticatedUserId
    && !client.preparedSessionProfile && !client.presenceKey && !client.invalidated);
  client.connectionSignal?.throwIfAborted();
}
export function assertResidentObservationMethod(req,client,registry,coreHandler) {
  if(!hasResidentObservation(req?.params) && !isResidentObservationConnect(client?.connect))return;
  observationRequire(registry.isObservation(req.method)===true && registry.getReadSharing?.(req.method)===undefined
    && registry.getScope(req.method)==='operator.read' && typeof coreHandler==='function'
    && registry.getHandler(req.method)===coreHandler);
}
/** Capture exact already-published owner facts. Every API here is a resident read. */
export async function authorizeResidentObservation(params,native) {
  const fail=()=>({error:{code:'UNAVAILABLE',message:'Resident observation unavailable'}});
  try {
    const {client,context}=params;
    const req={method:params.method,params:params.requestParams};
    const target=validateResidentObservation(req.method,req.params);
    const connect=client.connect, internal=client.internal, actor=internal.operatorRoleActor;
    const scopes=JSON.stringify(connect.scopes), authPolicy=client.authPolicy;
    const cfg=context.getRuntimeConfig(), policyConfig=(context.getCommittedRuntimeConfig??context.getRuntimeConfig)();
    const assertCaller=()=>{
      assertResidentObservationRequest(req,client,params);
      observationRequire(client.connect===connect && client.internal===internal && internal.operatorRoleActor===actor
        && client.authPolicy===authPolicy && JSON.stringify(connect.scopes)===scopes
        && context.getRuntimeConfig()===cfg && (context.getCommittedRuntimeConfig??context.getRuntimeConfig)()===policyConfig);
      params.signal?.throwIfAborted();
      observationRequire(typeof params.hasCurrentClientAuthority==='function' && params.hasCurrentClientAuthority());
      params.assertInvocationCurrent?.();
    };
    assertCaller();
    const scope=native.authorizeMethod();
    if(scope.error)return {error:scope.error};
    const uploadError=native.uploadPolicy();
    if(uploadError)return {error:uploadError};
    // No sync callback is permitted above. The native profile function still
    // decides whether the granted scope requires a human profile.
    const profileError=await native.authorizeProfile(scope.sessionScope);
    assertCaller();
    if(profileError)return {error:profileError};
    if(context.unavailableGatewayMethods?.has(params.method) || context.agentDatabaseStartup?.hasPendingAgents)return fail();
    const agent=native.resolveAgent(cfg,target.sessionKey,target.agentId);
    if(!agent.ok)return {error:agent.error};
    observationRequire(agent.agentId===target.agentId);
    const projection=native.getProjection(context);
    observationRequire(projection && projection.getPolicyConfig()===policyConfig);
    const revision=projection.sharingRevision;
    observationRequire(revision!==undefined && !native.isIncognito(target.sessionKey));
    const query={key:target.sessionKey,agentId:target.agentId};
    const resident=projection.sharingTargetState(query);
    observationRequire(resident?.status==='ready');
    const row=resident.target, entry=row.entry, generation=row.generation, lifecycleRevision=entry.lifecycleRevision;
    observationRequire(row.canonicalKey===query.key && row.agentId===query.agentId && entry.sessionId===target.sessionId
      && generation!==undefined && entry.incognito!==true && !native.permissionPending(target.sessionId));
    const source=projection.readSource(query), members=projection.readMembership(query);
    observationRequire(source && members instanceof Set);
    const sameSource=current=>current && ['agentId','path','databaseIdentity','databaseBirthtime'].every(k=>current[k]===source[k]);
    const assertCurrent=()=>{
      assertCaller();
      observationRequire(native.getProjection(context)===projection && projection.sharingRevision===revision
        && projection.getPolicyConfig()===policyConfig && !native.permissionPending(target.sessionId));
      const now=projection.sharingTargetState(query), membership=projection.readMembership(query);
      observationRequire(now?.status==='ready' && now.target.canonicalKey===query.key && now.target.agentId===query.agentId
        && now.target.generation===generation && now.target.entry===entry && entry.sessionId===target.sessionId
        && entry.lifecycleRevision===lifecycleRevision && sameSource(projection.readSource(query))
        && membership instanceof Set && membership.size===members.size && [...members].every(id=>membership.has(id)));
      const currentScope=native.authorizeMethod();
      observationRequire(!currentScope.error && currentScope.sessionScope===scope.sessionScope);
      const currentAgent=native.resolveAgent(cfg,target.sessionKey,target.agentId);
      observationRequire(currentAgent.ok && currentAgent.agentId===target.agentId);
    };
    assertCurrent();
    const authorization=native.authorizeSession({method:params.method,requestParams:req.params,client,context,
      sessionScope:scope.sessionScope,sessionRowRead:{state:{cfg,policyConfig},describe(selected){
        assertCurrent();observationRequire(selected.key===query.key && selected.agentId===query.agentId);
        return {entry,membership:members};
      }}});
    if(authorization.error)return {error:authorization.error};
    const denied=native.authorizeIncognito({client,sessionKey:query.key,target:row});
    if(denied)return {error:denied};
    const sharing=native.prepareSharing({cfg:policyConfig,client,isMember:(_target,id)=>members.has(id)});
    if(native.hasBoundary(client,policyConfig,sharing) && sharing.entryFilter?.(query.key,entry)===false)return fail();
    assertCurrent();
    return {error:null,sessionScope:scope.sessionScope,wikiObservationAuthorization:Object.freeze({target,assertCurrent})};
  } catch {return fail();}
}
/** Only the router passes this authority; no request field can supply it. */
export function respondResidentObservation(params,authorization,context,native) {
  const target=validateResidentObservation('sessions.describe',params);
  observationRequire(authorization && Object.keys(target).every(k=>authorization.target[k]===target[k]));
  authorization.assertCurrent();
  const activity=readResidentNativeActivity(context,target,{assertCurrent:authorization.assertCurrent,
    isGenerationCurrent:native.isGenerationCurrent,isTerminalSettled:native.isTerminalSettled});
  authorization.assertCurrent();
  const processInstanceId=native.processInstanceId();
  observationRequire(boundedIdentity(processInstanceId));
  return {schema_version:'wiki_resident_observation.v1',...target,process_instance_id:processInstanceId,
    observed_at:new Date().toISOString(),...activity};
}
