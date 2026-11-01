import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {readResidentNativeActivity} from '../../scripts/openclaw/mission-runtime.mjs';

const target={agentId:'example',sessionKey:'agent:example:observation-fixture',sessionId:'fixture-session'};
const generation=Symbol('fixture-generation');
const scope={scope:'resident_gateway_owners',complete:false,persisted_queue_count:null};
function fixture() {
  const context={chatAbortControllers:new Map(),chatQueuedTurns:new Map(),dedupe:new Map()};
  const native={assertCurrent:()=>{},isGenerationCurrent:value=>value===generation,
    isTerminalSettled:entry=>entry.projectSessionTerminalPending!==true && entry.projectSessionTerminalPersistence===undefined};
  const entry=extra=>({...target,controller:new AbortController(),lifecycleGeneration:generation,executionStarted:true,...extra});
  return {context,native,entry,read:()=>readResidentNativeActivity(context,target,native)};
}
function expectUnknown(result) {
  assert.equal(result.status,'unavailable');
  for(const key of ['has_active_run','active_run_ids','active_count','terminal_persistence_count','terminal_cleanup_count','queued_turn_count','pending_admission_count','persisted_queue_count']) assert.equal(result[key],null,key);
  assert.equal(result.complete,false);
  assert.equal(result.resident_complete,false);
}

test('zero only describes resident owners, with global and persisted queue state unproven',()=>{
  const f=fixture();assert.deepEqual(f.read(),{...scope,status:'observed',has_active_run:false,active_run_ids:[],active_count:0,
    terminal_persistence_count:0,terminal_cleanup_count:0,queued_turn_count:0,pending_admission_count:0,resident_complete:true,ids_truncated:false,error_code:null});
  for(const key of Object.keys(f.context)) expectUnknown(readResidentNativeActivity({...f.context,[key]:undefined},target,f.native));
});
test('active, queued, terminal and pending owners stay distinct and deduplicated',()=>{
  const f=fixture();
  f.context.chatAbortControllers.set('active',f.entry());
  f.context.chatAbortControllers.set('terminal',f.entry({terminalOutcomeObserved:true,projectSessionTerminalPending:true}));
  f.context.chatAbortControllers.set('admitting',f.entry({executionStarted:false}));
  f.context.chatQueuedTurns.set('queued',f.entry());
  f.context.chatQueuedTurns.set('active',f.context.chatAbortControllers.get('active'));
  for(const id of ['active','terminal','admitting','queued','pending']) f.context.dedupe.set('agent:'+id,{ok:true,payload:{...target,runId:id,status:'accepted'}});
  f.context.dedupe.set('pending-chat:pending',{ok:true,payload:{...target,runId:'pending',status:'accepted'}});
  assert.deepEqual(f.read(),{...scope,status:'observed',has_active_run:true,active_run_ids:['active'],active_count:1,
    terminal_persistence_count:1,terminal_cleanup_count:0,queued_turn_count:1,pending_admission_count:2,resident_complete:true,ids_truncated:false,error_code:null});
});
test('queued cancellation transfer remains visible even after the old signal aborts',()=>{
  const f=fixture(),entry=f.entry({abortable:false});entry.controller.abort();
  f.context.chatQueuedTurns.set('collect-owner',entry);
  assert.equal(f.read().queued_turn_count,1);assert.equal(f.read().active_count,0);
});
test('terminal persistence is separate from settled registrations awaiting cleanup',()=>{
  for(const extra of [{projectSessionTerminalPending:true},{projectSessionTerminalPersistence:Promise.resolve()}]) {
    const f=fixture();f.context.chatAbortControllers.set('terminal',f.entry(extra));
    assert.equal(f.read().terminal_persistence_count,1);assert.equal(f.read().active_count,0);
    assert.equal(f.read().terminal_cleanup_count,0);
  }
  for(const extra of [{registrationCleanupRequested:true},{projectSessionTerminalObservedAt:123},{terminalOutcomeObserved:true}]) {
    const f=fixture();f.context.chatAbortControllers.set('terminal',f.entry(extra));
    assert.equal(f.read().terminal_cleanup_count,1);assert.equal(f.read().active_count,0);
    assert.equal(f.read().terminal_persistence_count,0);
  }
});
test('identity mismatch, stale generation and ambiguous admission never report idle',()=>{
  for(const extra of [{sessionId:'rebound-session'},{agentId:'other'},{lifecycleGeneration:Symbol('old')},{executionStarted:undefined}]) {
    const f=fixture();f.context.chatAbortControllers.set('run',f.entry(extra));expectUnknown(f.read());
  }
  const f=fixture();f.context.dedupe.set('pending-chat:pending',{ok:true,payload:{status:'accepted',runId:'pending',sessionKey:target.sessionKey}});expectUnknown(f.read());
  f.context.dedupe.clear();f.context.chatAbortControllers.set('run',f.entry());f.context.chatQueuedTurns.set('run',f.entry());expectUnknown(f.read());
});
test('unaddressable resident owners cannot prove zero',()=>{
  for(const key of ['chatAbortControllers','chatQueuedTurns']) {
    const f=fixture();f.context[key].set('unbound',f.entry({sessionKey:undefined,sessionId:undefined}));expectUnknown(f.read());
  }
  const f=fixture();f.context.dedupe.set('agent:unbound',{ok:true,payload:{status:'accepted',runId:'unbound'}});expectUnknown(f.read());
});
test('an exact native owner covers incomplete accepted dedupe, while contradictions remain unknown',()=>{
  for(const map of ['chatAbortControllers','chatQueuedTurns']) {
    const f=fixture();f.context[map].set('run',f.entry());
    f.context.dedupe.set('agent:run',{ok:true,payload:{runId:'run',status:'accepted',sessionKey:target.sessionKey}});
    assert.equal(f.read().resident_complete,true);assert.equal(f.read().pending_admission_count,0);
    assert.equal(f.read().active_count+f.read().queued_turn_count,1);
    f.context.dedupe.get('agent:run').payload.sessionId='other-physical-session';expectUnknown(f.read());
  }
});
test('revocation or rebind during the synchronous read discards all counts',()=>{
  const f=fixture();f.context.chatAbortControllers.set('run',f.entry());
  let current=true,checks=0;
  f.native.assertCurrent=()=>{checks++;if(!current)throw new Error('resident authority changed');};
  f.native.isTerminalSettled=()=>{current=false;return true;};
  expectUnknown(f.read());assert.equal(checks,2);
  const g=fixture();g.native.assertCurrent=()=>{throw new Error('cold or retired capture');};
  expectUnknown(g.read());
  const h=fixture();h.context.chatAbortControllers.set('run',h.entry());
  h.native.isTerminalSettled=()=>{h.context.chatQueuedTurns=new Map();return true;};expectUnknown(h.read());
});
test('absent or non-synchronous native evidence cannot qualify a read',()=>{
  const f=fixture();delete f.native.assertCurrent;expectUnknown(f.read());
  for(const key of ['assertCurrent','isGenerationCurrent','isTerminalSettled']) {
    const g=fixture();g.context.chatAbortControllers.set('run',g.entry());
    g.native[key]=()=>Promise.resolve(true);expectUnknown(g.read());
  }
  const h=fixture(),entry=h.entry();entry.controller.abort();
  h.context.chatAbortControllers.set('cancelled-unsettled',entry);expectUnknown(h.read());
});
test('unrelated sessions and settled historical dedupe are excluded',()=>{
  const f=fixture();f.context.chatAbortControllers.set('other',f.entry({sessionKey:'agent:other:fixture',sessionId:'other',agentId:'other'}));
  f.context.dedupe.set('agent:done',{ok:true,payload:{...target,runId:'done',status:'completed'}});
  assert.equal(f.read().active_count,0);assert.equal(f.read().pending_admission_count,0);
});
test('bounded ids keep a complete count; excessive owner inventory is unknown',()=>{
  const f=fixture();for(let i=0;i<70;i++) f.context.chatAbortControllers.set('run-'+i,f.entry());
  assert.equal(f.read().active_count,70);assert.equal(f.read().active_run_ids.length,64);assert.equal(f.read().ids_truncated,true);
  for(let i=0;i<10_001;i++) f.context.dedupe.set('unrelated-'+i,{});expectUnknown(f.read());
});
test('memory read does not open/write files, prepare, reconcile or dispatch',()=>{
  const f=fixture();const entry=f.entry();f.context.chatAbortControllers.set('run',entry);
  const forbidden=()=>{throw new Error('forbidden effect');};
  Object.assign(f.context,{ensureSessionRowProjection:forbidden,prepareMembership:forbidden,
    reconcile:forbidden,dispatch:forbidden,openDatabase:forbidden,write:forbidden});
  const originals=new Map(['openSync','writeFileSync','appendFileSync','mkdirSync'].map(key=>[key,fs[key]]));
  const entries=[...f.context.chatAbortControllers],keys=Reflect.ownKeys(entry),values=keys.map(key=>entry[key]);
  try {
    for(const key of originals.keys()) fs[key]=forbidden;
    assert.equal(f.read().status,'observed');
    assert.deepEqual([...f.context.chatAbortControllers],entries);
    assert.deepEqual(Reflect.ownKeys(entry),keys);assert.deepEqual(keys.map(key=>entry[key]),values);
    assert.equal(f.context.chatQueuedTurns.size,0);assert.equal(f.context.dedupe.size,0);
  } finally {for(const [key,value] of originals) fs[key]=value;}
});
