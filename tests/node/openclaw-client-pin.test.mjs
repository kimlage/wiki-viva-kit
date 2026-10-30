import {test} from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {pinnedClientAdmission} from '../../scripts/openclaw/mission-client.mjs';
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function fixture(){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-client-pin-')));fs.writeFileSync(path.join(root,'package.json'),'{}');
 const spec={platform:process.platform,arch:process.arch};
 for(const [role,name]of[['launcher','@openai/codex'],['native','@openai/synthetic-platform']]){
  const dir=path.join(root,'node_modules',name);fs.mkdirSync(dir,{recursive:true});const file=role==='launcher'?'entry.js':'native';
  fs.writeFileSync(path.join(dir,'package.json'),JSON.stringify({name,version:'1.0.0'}));fs.writeFileSync(path.join(dir,file),role);
  spec[role]={name,version:'1.0.0',file,sha256:sha(role)};
 }
 const command=path.join(root,'node_modules/@openai/codex/entry.js');
 return {root,spec,command,options:{transport:'stdio',commandSource:'resolved-managed',command,args:['app-server','--listen','stdio://']},clean:()=>fs.rmSync(root,{recursive:true,force:true})};
}
test('only exact managed selection admits; package and native bytes are rechecked',()=>{const f=fixture();try{
 const admit=pinnedClientAdmission(f.root,f.spec);admit(f.options);
 for(const patch of [{commandSource:'config'},{commandSource:'env'},{transport:'websocket'},{command:'/Applications/Example.app/codex'},{args:['app-server','--listen','ws://127.0.0.1:0']}])assert.throws(()=>admit({...f.options,...patch}),/client_selection_changed/);
 fs.writeFileSync(path.join(f.root,'node_modules/@openai/synthetic-platform/native'),'replaced');assert.throws(()=>admit(f.options),/client_bytes_changed/);
 }finally{f.clean();}});
test('changed launcher, package version and unsupported platform fail closed',()=>{for(const change of ['launcher','version','platform']){const f=fixture();try{
 const admit=pinnedClientAdmission(f.root,f.spec);
 if(change==='launcher'){fs.writeFileSync(f.command,'replaced');assert.throws(()=>admit(f.options),/client_bytes_changed/);}
 if(change==='version'){const p=path.join(f.root,'node_modules/@openai/codex/package.json');fs.writeFileSync(p,JSON.stringify({name:'@openai/codex',version:'2.0.0'}));assert.throws(()=>admit(f.options),/client_package_changed/);}
 if(change==='platform')assert.throws(()=>pinnedClientAdmission(f.root,{...f.spec,platform:'unsupported'}),/client_platform_unsupported/);
 }finally{f.clean();}}});
test('exact native startup callback rejects replacement after asynchronous process registration',async()=>{
 const f=fixture();try{
  const admit=pinnedClientAdmission(f.root,f.spec);admit(f.options);
  const manifest=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
  const callback=manifest.files.find(f=>f.name==='shared-client-C0gEybHs.mjs').edits.find(([before])=>before.startsWith('CodexAppServerClient.start('))[1];
  const invoke=new Function('CodexAppServerClient','startOptions','assertStartupCurrent','resolveRemainingAcquireTimeout','timeoutMs','acquireStartedAt','wikiMissionGuard','return '+callback);
  let started=0;
  const client={start:async(options,assertCurrent)=>{await Promise.resolve();fs.writeFileSync(path.join(f.root,'node_modules/@openai/synthetic-platform/native'),'replaced after registration');assertCurrent();started++;}};
  await assert.rejects(invoke(client,f.options,()=>{},()=>{},1000,0,{authorizeClientStart:admit}),/client_bytes_changed/);
  assert.equal(started,0);
 }finally{f.clean();}
});
