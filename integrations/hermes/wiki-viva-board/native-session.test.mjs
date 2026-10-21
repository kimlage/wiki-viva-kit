import test from 'node:test';
import assert from 'node:assert/strict';
import {createNativeSessionAccess} from './native-session.mjs';
const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local'};
const execution={...Object.fromEntries([['connection_id','fixture'],['profile','research'],['target_profile','research']]),method:'native_session',stored_session_id:'stored-fixture'};
const ref={source_id:'source-a',binding_sha256:'a'.repeat(64),config_sha256:'b'.repeat(64)};
function fixture(){
 const calls=[],rows=new Map();let messages=[],events=[],epoch='epoch-fixture',seq=4,running=false,fail=false,runtimeId='runtime-fixture',truncated=false,activities=0,off=0,released=0,listener;
 const host={retainProfile:async(r)=>{assert.deepEqual(r,route);return()=>released++;},onEvent:(t,cb)=>{listener=cb;return()=>off++;},
  requestProfile:async(r,method,params)=>{
   assert.deepEqual(r,route);calls.push({method,params});
   if(method==='session.resume')return {session_id:runtimeId,resumed:execution.stored_session_id,running};
   if(method==='session.events.since')return {epoch,latest_seq:seq,truncated:truncated||epoch!=='epoch-fixture',events};
   if(method==='session.history')return {messages};
   if(method==='tools.list')return {toolsets:[{name:'unknown-toolset',enabled:true,tools:['new_capability_A','new_capability_B']}]};
   if(method==='prompt.submit'){if(fail)throw new Error('timeout');messages=[{role:'user',text:params.text,row_id:17}];events=[{session_id:'runtime-fixture',seq:5,type:'message.start'}];seq=5;return {status:'streaming',user_row_id:17};}
  },openSession:async(id,options)=>calls.push({method:'openSession',id,options})};
 const native=async(_r,path,_method,body)=>{
  if(path==='source-intent-claim'){
   if(rows.has(body.request_id))return {created:false,intent:structuredClone(rows.get(body.request_id))};
   const row={...ref,request_id:body.request_id,execution,status:'pending',prompt:'Native source intent '+body.request_id,identity:{status:'unknown'},read_verified:false};rows.set(body.request_id,row);return {created:true,intent:structuredClone(row)};
  }
  if(path==='source-intent-track'){const row=rows.get(body.request_id);Object.assign(row,body.tracking);return structuredClone(row);}
  if(path==='source-read-receipts')return {receipts:[...rows.values()].map(r=>structuredClone(r))};
 };
 const access=createNativeSessionAccess({host,native,live:()=>{},activity:()=>activities++});
 return {access,calls,rows,host,setFail:v=>fail=v,setRuntime:v=>runtimeId=v,setTruncated:v=>truncated=v,setReplay:v=>events=v,events:()=>structuredClone(events),activities:()=>activities,setRunning:v=>running=v,setEpoch:v=>epoch=v,
  complete:(id,name,result)=>{events=events.filter(e=>e.type!=='message.complete');events.push({session_id:'runtime-fixture',seq:++seq,type:'tool.complete',payload:{tool_id:id,name,result}},{session_id:'runtime-fixture',seq:++seq,type:'message.complete',payload:{persisted_turn:{complete:true,user_row_id:17,row_ids:[17]}}});messages.push({role:'tool',tool_call_id:id,name,content:{ok:true}},{role:'assistant',text:'Native result'});seq++;},
  mutateHistory:fn=>{messages=fn(messages);},event:e=>listener(e),disposed:()=>({off,released})};
}
test('one native prompt uses existing stored owner, retains native approvals and never creates a bot',async()=>{
 const f=fixture();const row=await f.access.read(route,ref,'fixture-request-0001',0);
 assert.equal(row.status,'pending');assert.equal(row.user_row_id,17);assert.equal(row.read_verified,false);assert.equal(row.prompt,undefined);
 assert.deepEqual(f.calls.find(c=>c.method==='prompt.submit').params,{session_id:'runtime-fixture',text:'Native source intent fixture-request-0001',queued:true});
 assert.equal(f.calls.filter(c=>c.method==='session.create').length,0);
 await f.access.open(route,execution);assert.deepEqual(f.calls.at(-1).options,{route,awaitHydration:true,forceResume:true});
 f.access.dispose();assert.deepEqual(f.disposed(),{off:1,released:1});
});
test('unknown native outcome never retries prompt and reconciles epoch/history instead',async()=>{
 const f=fixture();f.setFail(true);
 await assert.rejects(f.access.read(route,ref,'fixture-request-0001',0),/result_unknown/);
 await f.access.read(route,ref,'fixture-request-0001',0);
 f.setEpoch('new-epoch');await f.access.receipts(route,ref,0);
 assert.equal(f.calls.filter(c=>c.method==='prompt.submit').length,1);
 assert.ok(f.calls.some(c=>c.method==='session.history'));
});
test('two previously unseen tool names use the same glue; trace never becomes account or access proof',async()=>{
 const f=fixture();const catalogue=await f.access.inspect(route,execution);
 assert.deepEqual(catalogue[0].tools,['new_capability_A','new_capability_B']);
 await f.access.read(route,ref,'fixture-request-0001',0);f.complete('tool-call-1','entirely_new_provider_operation');
 let result=await f.access.receipts(route,ref,0);
 assert.equal(result.receipts[0].status,'native_trace_observed');assert.equal(result.receipts[0].read_verified,false);
 assert.deepEqual(result.receipts[0].tool_refs,[{id:'tool-call-1',name:'entirely_new_provider_operation',outcome:'unknown'}]);
 await f.access.read(route,ref,'fixture-request-0002',0);f.complete('tool-call-2','second_unknown_source_read');result=await f.access.receipts(route,ref,0);
 const second=result.receipts.find(r=>r.request_id==='fixture-request-0002');
 assert.equal(second.tool_refs[0].name,'second_unknown_source_read');assert.equal(second.grants_verified,false);
});
test('foreign user row and tool output cannot anchor this source intention',async()=>{
 const f=fixture();await f.access.read(route,ref,'fixture-request-0001',0);
 f.mutateHistory(()=>[{role:'user',row_id:17,text:'different source'},{role:'tool',tool_call_id:'foreign-call',name:'foreign-tool'},{role:'assistant',text:'done'}]);
 const result=await f.access.receipts(route,ref,0);assert.equal(result.receipts[0].status,'pending');
 f.event({connectionId:'foreign',profile:'research',session_id:'runtime-fixture',seq:900,type:'tool.complete'});
 assert.equal(f.calls.filter(c=>c.method==='prompt.submit').length,1);
});
test('busy native context is preserved and no prompt or grant is sent',async()=>{
 const f=fixture();f.setRunning(true);await assert.rejects(f.access.read(route,ref,'fixture-request-0001',0),/native_session_busy/);
 assert.equal(f.calls.filter(c=>c.method==='prompt.submit').length,0);assert.equal(f.rows.get('fixture-request-0001').status,'not_submitted');
});

test('missing or truncated native turn ownership remains unknown even with model text and tool history',async()=>{
 const f=fixture();await f.access.read(route,ref,'fixture-request-0001',0);f.complete('tool-call-1','unknown_read_tool');f.setEpoch('restarted-epoch');
 const result=await f.access.receipts(route,ref,0);assert.equal(result.receipts[0].status,'pending');assert.equal(result.receipts[0].read_verified,false);
});

test('a native tool failure is preserved as failure, never resource read success',async()=>{
 const f=fixture();await f.access.read(route,ref,'fixture-request-0001',0);f.complete('tool-call-1','unknown_extract',{success:false,error:'Native capability is search-only'});
 const result=await f.access.receipts(route,ref,0);assert.equal(result.receipts[0].status,'native_trace_failed');assert.equal(result.receipts[0].tool_refs[0].outcome,'reported_failure');assert.equal(result.receipts[0].read_verified,false);
});

test('legitimate runtime id change preserves the stored owner and original replay correlation',async()=>{
 const f=fixture();await f.access.read(route,ref,'fixture-request-0001',0);f.complete('tool-call-1','new_tool');f.setRuntime('resumed-runtime');
 const result=await f.access.receipts(route,ref,0);assert.equal(result.receipts[0].status,'native_trace_observed');
 assert.equal(f.calls.filter(c=>c.method==='session.events.since').at(-1).params.session_id,'runtime-fixture');
 assert.equal(f.calls.filter(c=>c.method==='session.history').at(-1).params.session_id,'resumed-runtime');
});
test('concurrent catalogue reads share and dispose one native profile lease',async()=>{
 const f=fixture();await Promise.all([f.access.inspect(route,execution),f.access.inspect(route,execution)]);f.access.dispose();assert.deepEqual(f.disposed(),{off:1,released:1});
});

test('owner-filtered live journal preserves a complete native trace when replay truncates',async()=>{
 const f=fixture();await f.access.read(route,ref,'fixture-request-0001',0);f.complete('tool-call-1','unseen_native_tool',{success:false,error:'private details stay native'});
 const journal=f.events();f.setReplay([]);f.setTruncated(true);
 f.event({connectionId:'other',profile:'research',session_id:'runtime-fixture',seq:100,type:'message.complete'});assert.equal(f.activities(),0);
 for(const frame of journal)f.event({...frame,connectionId:'fixture',profile:'research'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.rows.get('fixture-request-0001').status,'native_trace_failed');assert.ok(f.activities()>0);
 const record=JSON.stringify(f.rows.get('fixture-request-0001'));assert.ok(!record.includes('private details'));assert.equal(f.calls.filter(c=>c.method==='prompt.submit').length,1);
});
