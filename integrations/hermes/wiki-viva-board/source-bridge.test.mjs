import test from 'node:test';
import assert from 'node:assert/strict';
import { createSourceBridge } from './source-bridge.mjs';
const route={connectionId:'fixture-local',profile:'research',targetProfile:'research',mode:'local'};
const routeKey=JSON.stringify([route.connectionId,route.profile,route.targetProfile]);
const ref={source_id:'fictional-source',binding_sha256:'a'.repeat(64)};
const sourceBinding={...ref,config_sha256:'b'.repeat(64),source_kind:'repository',access_policy:{execution:{connection_id:route.connectionId,profile:route.profile,target_profile:route.targetProfile,method:'native_session',stored_session_id:'stored-fixture'}}};
function fixture(extra={}) {
  const calls=[],replies=[],setups=[];let epoch=0;const frame={};
  const host={profileRoutes:async()=>[route],retainProfile:async()=>()=>{},onEvent:()=>()=>{},requestProfile:async(r,method,params)=>{
    calls.push({r,method,params});
    if(method==='connectors.list')return {available:true,connectors:[{connector:'fictional-app',enabled:true,connected:false,connection_status:'disconnected',status_reason:null,gateway_disabled_tools:[]}]};
    if(method==='session.list')return {sessions:[{id:'stored-fixture',title:'Existing context'}]};
    if(method==='session.resume')return {session_id:'runtime-fixture',resumed:'stored-fixture',running:false};
    if(method==='session.events.since')return {epoch:'fixture-epoch',latest_seq:0};
    if(method==='prompt.submit')return {status:'streaming',user_row_id:17};
    return {servers:[{name:'fictional-mcp',connected:false,disabled:false,tools:0}]};
  }};
  const bridge=createSourceBridge({host,...extra,api:async request=>{calls.push(request);return request.path.includes('source-intent-claim')?{created:true,intent:{...sourceBinding,execution:sourceBinding.access_policy.execution,request_id:request.body.request_id,prompt:'Native intent'}}:request.path.includes('source-intent-track')?{...sourceBinding,execution:sourceBinding.access_policy.execution,request_id:request.body.request_id,...request.body.tracking}:sourceBinding;},
    openSetup:async input=>{setups.push(input);},frameWindow:()=>frame,wikiOrigin:'http://127.0.0.1:8765',channel:'fixture-channel-001',generation:0,currentGeneration:()=>epoch,reply:m=>replies.push(m),...extra});
  const message=(action='inspect',id='fixture-request-0001')=>({protocol:'wiki.source_access.v1',kind:'request',channel:'fixture-channel-001',request_id:id,action,source:ref,route_key:routeKey});
  const send=m=>bridge.receive({origin:'http://127.0.0.1:8765',source:frame,data:m});
  return {bridge,calls,replies,setups,message,send,frame,epoch:n=>epoch=n};
}
test('real ConnectorRow.connector and MCP status are capabilities, never access evidence',async()=>{
  const f=fixture();await f.send(f.message());const r=f.replies[0].result;
  assert.deepEqual(r.providers.map(p=>p.id),['fictional-app']);
  assert.equal(r.connection_verified,false);assert.equal(r.read_verified,false);
  assert.deepEqual(f.calls.filter(c=>c.method==='connectors.list')[0].params,{owner:{type:'account'}});
});
test('managed available:false stays unavailable; no invented providers or login calls',async()=>{
  const f=fixture({host:{profileRoutes:async()=>[route],requestProfile:async(r,m)=>m==='connectors.list'?{available:false,connectors:[]}:{servers:[]}}});
  await f.send(f.message());assert.deepEqual(f.replies[0].result.providers,[]);assert.equal(f.replies[0].result.managed_available,false);
});
test('foreign origin, foreign frame, arbitrary RPC/body and unknown route fail closed',async()=>{
  const f=fixture();
  await f.bridge.receive({origin:'null',source:f.frame,data:f.message()});
  await f.bridge.receive({origin:'http://127.0.0.1:8765',source:{},data:f.message()});
  await f.send({...f.message(),action:'shell.exec'});await f.send({...f.message(),argv:['bad']});
  assert.equal(f.calls.length,0);
  await f.send({...f.message(),route_key:'unknown'});assert.equal(f.replies.at(-1).ok,false);assert.equal(f.calls.length,0);
});
test('configure opens only the native UI and duplicate request never repeats its effect',async()=>{
  const f=fixture();const m=f.message('configure');await Promise.all([f.send(m),f.send(m)]);
  assert.equal(f.setups.length,1);assert.deepEqual(f.setups[0].route,{...route,key:routeKey});
  assert.equal(f.calls.filter(c=>c.method==='POST').length,0);assert.equal(f.calls.filter(c=>String(c.method).includes('connect')).length,0);
  await f.send({...m,action:'read_test'});assert.equal(f.calls.filter(c=>c.method==='POST').length,0);
});
test('saved owner/connection mismatch never reaches read-test',async()=>{
  const f=fixture({api:async()=>({...sourceBinding,access_policy:{execution:{...sourceBinding.access_policy.execution,connection_id:'another-owner'}}})});
  await f.send(f.message('read_test'));assert.equal(f.replies[0].error_code,'executor_profile_mismatch');
});
test('stale reload or closed source cancels setup after an awaited source lookup',async()=>{
  let release;const wait=new Promise(resolve=>release=resolve);
  const f=fixture({api:async()=>{await wait;return sourceBinding;}});
  const pending=f.send(f.message('configure'));await new Promise(r=>setTimeout(r,0));f.epoch(1);release();await pending;
  assert.equal(f.setups.length,0);assert.equal(f.replies.length,0);
  const g=fixture({api:async()=>{await wait;return sourceBinding;}});
  await g.bridge.receivePort({protocol:'wiki.source_access.v1',kind:'close',channel:'fixture-channel-001'});
  assert.equal(g.setups.length,0);
});
test('native intention claim routes only own plugin path with exact owner and request id',async()=>{
  const f=fixture();const m=f.message('read_test');await f.send(m);const call=f.calls.find(c=>c.method==='POST');
  assert.equal(call.connectionId,route.connectionId);assert.equal(call.profile,route.profile);
  assert.deepEqual(call.body,{source_id:ref.source_id,binding_sha256:ref.binding_sha256,config_sha256:sourceBinding.config_sha256,request_id:m.request_id});
  assert.match(call.path,/^\/api\/plugins\/wiki-viva-board\/source-intent-claim\?profile=research$/);
});

test('managed account choices come from actual scoped account rows, never default/unnamed or disabled accounts',async()=>{
 const methods=[];
 const f=fixture({host:{profileRoutes:async()=>[route],requestProfile:async(r,m,p)=>{
   methods.push({r,m,p});
   if(m==='connectors.list')return {available:true,connectors:[{connector:'gmail'}]};
   if(m==='mcp.servers.status')return {servers:[]};
   return {accounts:[{connection_id:'fixture-account',connector:'gmail',alias:'research',label:'Research',status:'active',disabled:false},{connection_id:'retired',connector:'gmail',alias:'retired',label:'Retired',status:'active',disabled:true},{connection_id:'unnamed',connector:'gmail',alias:null,label:'Unknown',status:'active'}]};
 }}});
 await f.send(f.message());
 assert.deepEqual(f.replies[0].result.accounts,[{id:'fixture-account',connector:'gmail',alias:'research',label:'Research',status:'active'}]);
 const call=methods.find(r=>r.m==='connectors.accounts');assert.deepEqual(call.p,{});assert.equal(call.r.profile,'research');
 assert.equal(f.replies[0].result.connection_verified,false);
});

test('closing a source releases its native listener/lease and reopening uses a fresh access object',async()=>{
 let released=0,off=0,listener;const methods=[];
 const f=fixture({host:{profileRoutes:async()=>[route],retainProfile:async()=>()=>released++,onEvent:(_type,cb)=>{listener=cb;return()=>off++;},requestProfile:async(_route,method)=>{
  methods.push(method);
  if(method==='session.resume')return {session_id:'runtime-fixture',resumed:'stored-fixture'};
  if(method==='session.events.since')return {epoch:'fixture-epoch',latest_seq:0};
  if(method==='prompt.submit')return {user_row_id:17};
 }}});
 await f.send(f.message('read_test'));const before=methods.length,callsBefore=f.calls.length;
 await f.bridge.receivePort({protocol:'wiki.source_access.v1',kind:'close',channel:'fixture-channel-001'});
 assert.deepEqual({off,released},{off:1,released:1});
 listener({connectionId:route.connectionId,profile:route.profile,session_id:'runtime-fixture',seq:9,type:'message.complete'});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(methods.length,before);assert.equal(f.calls.length,callsBefore);
 await f.send(f.message('read_test','fixture-request-0002'));
 assert.equal(f.replies.at(-1).ok,true);assert.equal(methods.filter(method=>method==='prompt.submit').length,2);
 f.bridge.dispose();assert.deepEqual({off,released},{off:2,released:2});
});

test('generic native settings validate newly discovered toolsets in the exact executor profile',async()=>{
 const scopes=[];const host={profileRoutes:async()=>[route],requestProfile:async()=>({}),toolsets:{list:async scope=>{scopes.push(scope);return [{name:'unseen-tools-A',enabled:false},{name:'new-tools-B',enabled:true}];}}};
 const f=fixture({host});await f.send(f.message());
 assert.deepEqual(f.replies.at(-1).result.toolsets.map(row=>row.name),['unseen-tools-A','new-tools-B']);
 for(const [i,name] of ['unseen-tools-A','new-tools-B'].entries())await f.send({...f.message('configure','fixture-toolset-000'+i),setup_method:'toolset:'+name});
 assert.deepEqual(f.setups.map(row=>({method:row.method,toolset:row.toolset})),[{method:'native_toolset',toolset:'unseen-tools-A'},{method:'native_toolset',toolset:'new-tools-B'}]);
 assert.ok(scopes.every(scope=>JSON.stringify(scope)===JSON.stringify({connectionId:route.connectionId,profile:route.profile})));
 await f.send({...f.message('configure','fixture-toolset-0003'),setup_method:'toolset:absent-tools'});
 assert.equal(f.replies.at(-1).ok,false);assert.equal(f.setups.length,2);
 assert.equal(f.calls.filter(call=>call.method==='POST').length,0);
});
