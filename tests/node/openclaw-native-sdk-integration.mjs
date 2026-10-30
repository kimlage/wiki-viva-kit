/** Opt-in offline integration: real pinned native capture/resolver, synthetic plugin only. */
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {registerHooks} from 'node:module';import {fileURLToPath,pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {treeHash,validatePackage,transform,assertSharedSdkBridge} from '../../scripts/openclaw/mission-loader.mjs';
import * as guard from '../../scripts/openclaw/mission-guard.mjs';
import {NativeCaptureRegistry,configureNativeRegistry} from '../../scripts/openclaw/mission-runtime.mjs';
const core=process.env.WIKI_TEST_OPENCLAW_CORE_ROOT;assert(core,'Provide the pinned native core for this offline test');
const manifest=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
validatePackage(core,manifest.packages.core);
const mode=process.argv[2]||'bridge';assert(['bridge','absolute','preloaded','integrity','late'].includes(mode),'Unknown test case');
const scratch=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-native-sdk-')));
process.env.OPENCLAW_STATE_DIR=path.join(scratch,'state');process.env.OPENCLAW_CONFIG_PATH=path.join(scratch,'config.json');
fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH,'{}');
const sdk=path.join(core,'dist/plugin-sdk/process-runtime.js'),nativeLoader=path.join(core,'dist/plugin-setup-module-inWd3Rne.mjs');
let instance,other;
try {
 if(mode==='preloaded')await import(pathToFileURL(sdk).href);
 const plugin=path.join(scratch,'synthetic-plugin');fs.mkdirSync(path.join(plugin,'node_modules'),{recursive:true});fs.symlinkSync(core,path.join(plugin,'node_modules/openclaw'),'dir');
 fs.writeFileSync(path.join(plugin,'package.json'),JSON.stringify({name:'synthetic-native-guard',version:'0.0.0',type:'module'}));
 const binding=mode==='absolute'
  ? `import * as bridge from ${JSON.stringify(new URL('../../scripts/openclaw/mission-guard.mjs',import.meta.url).href)};`
  : 'import {wikiMissionBridge as bridge} from "openclaw/plugin-sdk/process-runtime";';
 fs.writeFileSync(path.join(plugin,'a.mjs'),`${binding}\nbridge.loadedHook('a.mjs',import.meta.url);export const capturedUrl=import.meta.url;export function capability(){return bridge.captureOwner(import.meta.url);}export function describe(){return {url:import.meta.url,frozen:Object.isFrozen(bridge),keys:Object.keys(bridge)}};`);
 fs.writeFileSync(path.join(plugin,'b.mjs'),`${binding}\nbridge.loadedHook('b.mjs',import.meta.url);`);
 const entry=path.join(plugin,'entry.mjs');fs.writeFileSync(entry,(mode==='late'?'':"import './b.mjs';")+"export * from './a.mjs';");
 const fixtureSpec={name:'synthetic-native-guard',version:'0.0.0',tree_sha256:treeHash(plugin)};
 const registry=new NativeCaptureRegistry({pluginRoot:plugin,coreRoot:core,files:['a.mjs','b.mjs'].map(name=>({name,relative:name})),validatePackage:root=>validatePackage(root,fixtureSpec)});
 configureNativeRegistry(registry);guard.configureRuntime(['a.mjs','b.mjs','process-runtime.js','plugin-setup-module-inWd3Rne.mjs']);
 const overlay=registerHooks({load(url,context,nextLoad){const out=nextLoad(url,context);if(!url.startsWith('file:'))return out;const file=fileURLToPath(url);if(file!==sdk&&file!==nativeLoader)return out;return {...out,source:transform(path.basename(file),typeof out.source==='string'?out.source:Buffer.from(out.source).toString())};}});
 const sdkModule=await import(pathToFileURL(sdk).href);
 if(mode==='preloaded') {assert.throws(()=>assertSharedSdkBridge(sdkModule),/sdk_overlay_missing/);console.log(JSON.stringify({case:mode,refused:true}));}
 else {
  assertSharedSdkBridge(sdkModule);
  const {n:PluginInstance,r:bind}=await import(pathToFileURL(nativeLoader).href);
  const {t:createRegistry}=await import(pathToFileURL(path.join(core,'dist/registry-empty-mS6HujHb.mjs')).href);
  const {M:captureScope}=await import(pathToFileURL(path.join(core,'dist/plugin-generation-source-lookup-BCzbJZNI.mjs')).href);
  const nativeRegistry=createRegistry(),record={id:'codex',origin:'global',source:entry,trustedOfficialInstall:true};nativeRegistry.plugins.push(record);
  instance=new PluginInstance('codex',{record,registry:nativeRegistry});
  const captures=path.join(scratch,'captures');fs.mkdirSync(captures);
  await captureScope(captures,async()=>{
   if(mode==='integrity')fs.appendFileSync(path.join(plugin,'a.mjs'),'\n// changed after pin\n');
   if(mode==='integrity') {assert.throws(()=>bind({instance,origin:'global',source:entry,rootDir:plugin,pluginSdkResolution:'auto'}),/unsupported_package/);console.log(JSON.stringify({case:mode,refused:true}));return;}
   bind({instance,origin:'global',source:entry,rootDir:plugin,pluginSdkResolution:'auto'});
   if(mode==='absolute') {assert.throws(()=>instance.loadModule(entry),/unknown_hook/);console.log(JSON.stringify({case:mode,reproduced:'wiki_mission_unknown_hook'}));return;}
   const wrapped=instance.loadModule(entry),description=wrapped.describe();
   assert.notEqual(description.url,pathToFileURL(path.join(plugin,'a.mjs')).href);assert(description.frozen);
   assert(!description.keys.includes('configureRuntime'));assert(!description.keys.includes('registerNativeArtifact'));
   // loadModule already exercises native wrapping. Read its cached raw namespace
   // only to test capability identity; never replace the native invocation scope.
   const raw=instance.run(()=>instance.moduleLoader(entry));
   const capability=instance.run(()=>raw.capability());
   if(mode==='late') {
    assert.throws(()=>registry.assert(capability),/capture_hooks_incomplete/);
    assert.throws(()=>guard.authorizeTurn({}, {}, capability),/capture_hooks_incomplete/);
    assert.throws(()=>guard.checkInferenceSelection({owner:capability}),/capture_hooks_incomplete/);
    instance.loadModule(path.join(plugin,'b.mjs'));
   }
   guard.assertRuntime();registry.assert(capability);
   assert.throws(()=>guard.captureOwner(description.url),/capture_wrong_owner/);
   const another=createRegistry(),otherRecord={...record};another.plugins.push(otherRecord);other=new PluginInstance('codex',{record:otherRecord,registry:another});
   assert.throws(()=>other.run(()=>guard.captureOwner(description.url)),/capture_wrong_owner/);
   assert.equal(sdkModule.wikiMissionBridge.loadedHook,guard.loadedHook);
   await instance.dispose(undefined,{waitForSettlement:true});
   assert(instance.owner.revoked&&instance.lifecycle.signal.aborted&&!instance.accepting);
   assert.throws(()=>registry.assert(capability),/capture_owner_retired/);assert.throws(()=>wrapped.describe());
   console.log(JSON.stringify({case:mode,shared_host_guard:true,native_owner_verified:true,native_revocation_verified:true,configured_hooks:4,production_hooks:manifest.files.length}));
  });
 }
 overlay.deregister();
} finally {
 if(other)await other.dispose(undefined,{waitForSettlement:true});
 if(instance&&!instance.lifecycle.signal.aborted)await instance.dispose(undefined,{waitForSettlement:true});
 fs.rmSync(scratch,{recursive:true,force:true});
}
