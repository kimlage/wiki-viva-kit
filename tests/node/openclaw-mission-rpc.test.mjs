import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {requestOptions,safeFailure} from '../../scripts/openclaw/mission-rpc.mjs';
import {treeHash} from '../../scripts/openclaw/mission-loader.mjs';
const base={expectUrl:'ws://127.0.0.1:19880',method:'chat.send',params:{wikiMission:'a'.repeat(64),suppressCommandInterpretation:true,deliver:false}};
test('mission requests native admin scope without auth overrides or shared-state writes',()=>{
 const {opts,extra}=requestOptions(base);
 assert.deepEqual(extra,{sharedStateMode:'read-only',progress:false,scopes:['operator.admin']});
 assert.deepEqual(opts,{expectUrl:base.expectUrl,json:true,timeout:'20000'});
 for(const method of ['chat.history','sessions.patch'])assert.equal(requestOptions({...base,method}).extra.scopes,undefined);
});
test('transport refuses arbitrary methods, targets, grants and non-mission sends',()=>{
 for(const change of [{method:'config.set'},{token:'secret'},{expectUrl:'ws://example.test:123'},{expectUrl:'ws://u:p@127.0.0.1:123'},{params:{}}])assert.throws(()=>requestOptions({...base,...change}));
});
test('safe errors preserve native refusal class without arbitrary error details',()=>{
 assert.deepEqual(safeFailure({gatewayCode:'INVALID_REQUEST',message:'system provenance fields require admin scope',details:{token:'secret'}}),{type:'rpc_rejection',code:'INVALID_REQUEST',reason:'system_provenance_requires_admin'});
 assert.equal(JSON.stringify(safeFailure({message:'Bearer private-value',gatewayCode:'private-value'})).includes('private-value'),false);
});
test('resident observation has one closed method with no identity or scope grant override',()=>{
 const input={expectUrl:base.expectUrl,method:'sessions.describe',params:{key:'agent:example:fixture',agentId:'example',wikiObservation:{version:1,sessionId:'fixture-session'}}};
 const {opts,extra}=requestOptions(input);
 assert.equal(opts.timeout,'5000');assert.equal(extra.scopes,undefined);assert.equal(extra.deviceIdentity,null);
 assert.deepEqual(extra.caps,['wiki.resident-observation.v1']);assert.equal(extra.sharedStateMode,'read-only');
 for(const params of [{key:input.params.key},{...input.params,includeLastMessage:false},{...input.params,wikiObservation:false},
   {...input.params,wikiObservation:{version:1,sessionId:'fixture-session',token:'synthetic-forbidden'}},
   {...input.params,agentId:'foreign'}])assert.throws(()=>requestOptions({...input,params}));
 for(const field of ['scopes','token','caps','config'])assert.throws(()=>requestOptions({...input,[field]:{}}));
});

test('each RPC qualifies the full package once and observation retains root, package and hook refusals',()=>{
 const scratch=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-rpc-qualification-')));
 try {
  const scripts=path.join(scratch,'scripts'),root=path.join(scratch,'core');
  fs.cpSync(new URL('../../scripts/openclaw/',import.meta.url),scripts,{recursive:true});
  fs.mkdirSync(path.join(root,'dist'),{recursive:true});
  fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({name:'synthetic-core',version:'1',type:'module'}));
  const counted=path.join(root,'counted.js');fs.writeFileSync(counted,'// full-package sentinel');
  const source='globalThis.rawHooks=(globalThis.rawHooks||0)+1;';
  const files=[0,1,2].map(i=>({name:`client-${i}.mjs`,relative:`dist/client-${i}.mjs`,package:'core',observation:'client',
   sha256:crypto.createHash('sha256').update(source).digest('hex'),edits:[[source,'globalThis.closedHooks=(globalThis.closedHooks||0)+1;']]}));
  for(const file of files)fs.writeFileSync(path.join(root,file.relative),source);
  fs.writeFileSync(path.join(root,'dist/gateway-dispatch-config-DSayH5yx.mjs'),
   "import fs from 'node:fs';export function t(){if(process.env.WIKI_RPC_FIXTURE_CHANGE==='hook')fs.appendFileSync(new URL('./client-0.mjs',import.meta.url),'\\n// replaced after qualification');return {};}");
  fs.writeFileSync(path.join(root,'dist/gateway-rpc.runtime.js'),
   files.map(f=>`import './${f.name}';`).join('\n')+'\nexport async function callGatewayFromCliRuntime(method){return {method,passes:globalThis.packagePasses,closedHooks:globalThis.closedHooks||0};}');
  const manifest={packages:{core:{name:'synthetic-core',version:'1',tree_sha256:treeHash(root)}},files};
  const manifestPath=path.join(scripts,'mission-overlay.json');fs.writeFileSync(manifestPath,JSON.stringify(manifest));
  const preload=path.join(scratch,'count.mjs');
  fs.writeFileSync(preload,`import fs from 'node:fs';const read=fs.readFileSync;globalThis.packagePasses=0;fs.readFileSync=function(file,...args){if(String(file)===${JSON.stringify(counted)})globalThis.packagePasses++;return read.call(this,file,...args);};`);
  const input={expectUrl:base.expectUrl,method:'sessions.describe',params:{key:'agent:example:fixture',agentId:'example',wikiObservation:{version:1,sessionId:'fixture-session'}}};
  const invoke=(request=input,location=root,change='')=>spawnSync(process.execPath,['--import',preload,path.join(scripts,'mission-rpc.mjs'),location],
   {input:JSON.stringify(request),encoding:'utf8',env:{...process.env,WIKI_OPENCLAW_GUARD_BOOTSTRAP:'0',WIKI_RPC_FIXTURE_CHANGE:change},timeout:10000});
  for(const request of [input,input,{...base,method:'chat.history'},base,{...base,method:'sessions.patch'}]) {
   const result=invoke(request);assert.equal(result.status,0,result.stderr+result.stdout);
   assert.deepEqual(JSON.parse(result.stdout),{method:request.method,passes:1,closedHooks:request===input?3:0});
  }
  const refuses=result=>{assert.equal(result.status,1,result.stderr+result.stdout);assert.equal(JSON.parse(result.stdout).ok,false);};
  const alias=path.join(scratch,'alias');fs.symlinkSync(root,alias,'dir');refuses(invoke(input,alias));
  fs.appendFileSync(counted,'\n// tampered');refuses(invoke());fs.writeFileSync(counted,'// full-package sentinel');
  fs.writeFileSync(manifestPath,JSON.stringify({...manifest,files:files.slice(0,2)}));refuses(invoke());fs.writeFileSync(manifestPath,JSON.stringify(manifest));
  refuses(invoke(input,root,'hook'));
 } finally {fs.rmSync(scratch,{recursive:true,force:true});}
});
