/** Real native database/writer, isolated synthetic state; zero model/Gateway. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-retirement-native-')));
Object.assign(process.env,{OPENCLAW_STATE_DIR:root,OPENCLAW_HOME:root,OPENCLAW_PROFILE:'synthetic-retirement',OPENCLAW_CONFIG_PATH:path.join(root,'openclaw.json'),OPENCLAW_CONFIG_READONLY:'1'});
fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH,JSON.stringify({agents:{ownership:'explicit',entries:{research:{workspace:path.join(root,'workspace')}}}}));
const core=process.env.WIKI_TEST_OPENCLAW_CORE_ROOT;
const mutations=await import(core+'/dist/session-accessor.entry-mutation-telsi3Ig.mjs');
const load=(await import(core+'/dist/session-accessor.sqlite-exact-read-HBi2gDDN.mjs')).a;
const append=(await import(core+'/dist/transcript-CpqWjSbD.mjs')).t;
const {n:expectedState}=await import(core+'/dist/session-transcript-turn-state-Bqkxfhzx.mjs');
const scope={agentId:'research',sessionKey:'agent:research:synthetic-retirement'};
const sessionId='00000000-0000-4000-8000-000000000002';
const entry={sessionId,updatedAt:Date.now(),status:'interrupted',abortedLastRun:true,
 restartRecoveryDeliveryRunId:'00000000-0000-4000-8000-000000000001',restartRecoveryDeliverySourceRunId:'wiki-run-'+'a'.repeat(32),
 mainRestartRecovery:{cycleId:'synthetic-cycle',revision:7,chargedAttempts:0}};
let checks=0;
try{
 const created=await mutations.r(scope,()=>({ok:true,entry}));assert.equal(created.ok,true,JSON.stringify(created));
 const snapshot=load(scope).entry;
 const attempt=async(snapshot,id,assertCurrent)=>append({...scope,expectedSessionId:sessionId,
  expectedLifecycleRevision:snapshot.lifecycleRevision??null,
  expectedSessionState:{...expectedState(snapshot),wikiMissionRetirementEntry:structuredClone(snapshot)},
  idempotencyKey:id,text:'Synthetic reviewed retirement without result; external effects unknown.',assertCurrent,
  sessionLifecyclePatch:{abortedLastRun:false,mainRestartRecovery:undefined,restartRecoveryDeliveryRunId:undefined,restartRecoveryDeliverySourceRunId:undefined,status:'interrupted'}});
 // A field absent from the ordinary expected-state projection changes after capture.
 await mutations.l(scope,()=>({lastRunError:'Synthetic changed native custody observation'}));
 assert.equal(load(scope).entry.lastRunError,'Synthetic changed native custody observation');
 const rejected=await attempt(snapshot,'stale-cas',()=>{checks++;});
 assert.equal(rejected.ok,false,'actual writer ignored the full-entry CAS');
 const afterRejected=load(scope).entry;assert.equal(afterRejected.abortedLastRun,true);assert.equal(afterRejected.lastRunError,'Synthetic changed native custody observation');
 await mutations.l(scope,()=>({lastRunError:undefined}));
 const current=load(scope).entry;
 await assert.rejects(()=>attempt(current,'revoked',()=>{throw Error('synthetic revoked before commit');}));
 assert.equal(load(scope).entry.abortedLastRun,true);
 const lifecycle=await import(core+'/dist/session-lifecycle-admission-B5CJ-emz.mjs');
 const physical=(await import(core+'/dist/session-accessor.sqlite-scope-BkgwxatT.mjs')).s(scope);
 const databasePath=(await import(core+'/dist/openclaw-agent-db.paths-BbmZlEP5.mjs')).l((await import(core+'/dist/session-accessor.sqlite-scope-helpers-CfDTAEsL.mjs')).i(physical));
 const target={scope:databasePath,identities:[scope.sessionKey,sessionId]};
 let incoming;
 await assert.rejects(()=>lifecycle.v('synthetic-reviewed-retirement',{...target,kind:'synthetic-retirement',run:()=>attempt(current,'pending-admission',()=>{
  incoming??=lifecycle.n({...target,owner:Symbol('synthetic-incoming'),assertAllowed:()=>{}});
  if(lifecycle.l(target))throw Error('synthetic competing pending admission');
 })}),/synthetic competing pending admission/);
 const lease=await incoming;lease.release();
 assert.equal(load(scope).entry.abortedLastRun,true);
 const passed=await attempt(current,'reviewed-cas',()=>{checks++;});assert.equal(passed.ok,true,JSON.stringify(passed));
 assert.equal(load(scope).entry.abortedLastRun,false);
 const again=await attempt(current,'reviewed-cas',()=>{checks++;});assert.equal(again.ok,false);
 const read=(await import(core+'/dist/session-transcript-readers-Bka5K3vB.mjs')).c;
 const messages=await read({...scope,sessionId},{mode:'all'});assert.equal(messages.length,1);assert.equal(messages[0].idempotencyKey,'reviewed-cas');
 console.log(JSON.stringify({ok:true,real_native_worker:true,stale_entry_rejected:true,revoked_rejected:true,native_pending_admission_rejected:true,settlement_and_notice_committed:true,replay_rejected:true,checks,synthetic_state:root}));
}catch(e){console.error(e);process.exitCode=1;}
// Native worker pools have idle timers; this bounded test owns its isolated process.
setTimeout(()=>process.exit(process.exitCode||0),100);
