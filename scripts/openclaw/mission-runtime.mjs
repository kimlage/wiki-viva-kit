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
