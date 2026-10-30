import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createFixtureRegistry} from './native-capture-fixture.mjs';
function check(name,run){test(name,()=>{const f=createFixtureRegistry();try{run(f);}finally{f.clean();}});}
check('qualified captured code retains its native owner across async boundaries',f=>{
 const c=f.candidate();c.register();c.load();const cap=f.registry.capture(c.url);c.setCurrent(undefined);f.registry.assert(cap);
 assert.throws(()=>f.registry.capture(c.url),/wrong_owner/);assert.throws(()=>f.registry.assert({...cap}),/capability_required/);
});
check('unregistered copies and original modules cannot acquire a capability',f=>{
 const c=f.candidate();assert.throws(()=>f.registry.capture(c.url),/unqualified/);
 assert.throws(()=>f.registry.capture(new URL('file://'+path.join(f.pluginRoot,'dist/run.mjs')).href),/unqualified/);
});
for(const [name,mutate,pattern] of [
 ['changed non-hook module',c=>fs.writeFileSync(path.join(c.root,'dist/index.js'),'changed'),/unsupported_package/],
 ['false source inverse',c=>{c.artifact.sourceForCaptured=()=>'/other/source';},/round_trip/],
 ['false module root',c=>{c.artifact.moduleRoot=()=>'/other';},/round_trip/],
 ['unavailable native artifact',c=>{c.artifact.assertModuleAvailable=()=>{throw Error('native unavailable');};},/native unavailable/],
 ['wrong SDK link',(c,f)=>{fs.unlinkSync(path.join(c.root,'node_modules/openclaw'));const wrong=path.join(f.base,'wrong-core');fs.cpSync(f.coreRoot,wrong,{recursive:true});fs.symlinkSync(wrong,path.join(c.root,'node_modules/openclaw'));},/sdk_changed/]
])check(name+' refuses registration',(f)=>{const c=f.candidate();mutate(c,f);assert.throws(c.register,pattern);assert.equal(f.registry.roots.size,0);});
check('early native binding requires its own hook; execution requires all captured hooks',f=>{
 const c=f.candidate();c.register();
 assert.throws(()=>f.registry.capture(c.url),/hook_not_loaded/);
 f.registry.loaded('inference.mjs',c.inferUrl);
 assert.throws(()=>f.registry.capture(c.url),/hook_not_loaded/);
 const cap=f.registry.capture(c.inferUrl);
 assert.throws(()=>f.registry.assert(cap),/hooks_incomplete/);
 c.load();f.registry.assert(cap);
 // Readiness remains a runtime check, including retained capabilities.
 f.registry.roots.get(c.root).loaded.delete('run.mjs');
 assert.throws(()=>f.registry.assert(cap),/hooks_incomplete/);
});
check('revocation before late hook loading cannot reactivate an early capability',f=>{
 const c=f.candidate(),dispose=c.register();f.registry.loaded('inference.mjs',c.inferUrl);
 const cap=f.registry.capture(c.inferUrl);dispose();
 assert.throws(()=>f.registry.loaded('run.mjs',c.url),/retired/);
 assert.throws(()=>f.registry.assert(cap),/retired/);
});
check('URL variants and foreign invocation do not inherit authority',f=>{const c=f.candidate();c.register();c.load();for(const suffix of ['?copy=1','#copy'])assert.throws(()=>f.registry.capture(c.url+suffix),/capture_url/);c.setCurrent({...c.instance});assert.throws(()=>f.registry.capture(c.url),/wrong_owner/);});
check('catalog/setup instance cannot execute a runtime mission',f=>{const c=f.candidate({runtime:false});c.register();c.load();const cap=f.registry.capture(c.url);assert.throws(()=>f.registry.assert(cap),/runtime_owner_required/);});
for(const retire of [c=>{c.instance.owner.revoked=true;},c=>{c.instance.accepting=false;},c=>{c.instance.replacementReserved=true;},c=>{c.instance.forcedRetirement=true;},c=>c.control.abort()])check('native lifecycle revocation invalidates an issued capability',f=>{const c=f.candidate();c.register();c.load();const cap=f.registry.capture(c.url);retire(c);assert.throws(()=>f.registry.assert(cap),/owner_retired/);});
check('shared artifact disposal removes only the disposed owner',f=>{
 const a=f.candidate();const disposeA=a.register();a.load();const capA=f.registry.capture(a.url);
 const b=f.candidate({shared:a});const disposeB=b.register();a.setCurrent(b.instance);b.setCurrent(b.instance);const capB=f.registry.capture(b.url);
 disposeA();assert.throws(()=>f.registry.assert(capA),/retired/);f.registry.assert(capB);assert.equal(f.registry.capture(b.url).instance,b.instance);
 disposeB();assert.throws(()=>f.registry.assert(capB),/retired/);assert.throws(()=>f.registry.capture(b.url),/retired/);
});
