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
