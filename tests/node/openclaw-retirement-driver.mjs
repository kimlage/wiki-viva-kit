/** Synthetic native-owner callbacks; no Gateway, model, account or credentials. */
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const {retireReviewedFailure}=await import(pathToFileURL(input.module).href);
const now=Date.now;Date.now=()=>now()+7200000; // Fixture-only expired observation.
const e={sessionId:'synthetic-session',status:'interrupted',abortedLastRun:true,
 restartRecoveryDeliveryRunId:'00000000-0000-4000-8000-000000000001',restartRecoveryDeliverySourceRunId:input.run,
 mainRestartRecovery:{cycleId:'synthetic-cycle',revision:7,chargedAttempts:0}};
let current=structuredClone(e),checks=0,committed=0;
const change=input.change;
if(change==='writer')current.activeWriterRunId='foreign';
if(change==='claim')current.restartRecoveryDeliveryRunId='other-claim';
if(change==='cycle')current.mainRestartRecovery.cycleId='other-cycle';
if(change==='delivery')current.pendingFinalDelivery={kind:'replayable',text:'Unconfirmed'};
if(change==='harness')current.restartRecoveryHarnessCompletion={taskId:'other'};
const api={exclusive:async run=>run(),load:()=>current,assertCurrent:()=>{checks++;if(change==='revoked'&&checks>1)throw Error('revoked');},
 competing:()=>change==='competing'||change==='late_competing'&&checks>1,liveOwner:()=>change==='live',pendingEmpty:()=>!(change==='queue'||change==='late_queue'&&checks>1),
 settle:async(entry,reviewed)=>{
  if(change==='commit_entry')current.pendingFinalDelivery={kind:'replayable'};
  if(change==='receipt')fs.appendFileSync(input.resolution,' ');
  if(change==='precommit_crash')throw Error('simulated crash before commit');
  reviewed.assertCurrent();
  if(!isDeepStrictEqual(current,reviewed.snapshot))throw Error('native full-entry CAS rejected');
  if(!reviewed.reason.includes('without result')||!reviewed.reason.includes('undetermined'))throw Error('untruthful notice');
  committed++;current={...current,abortedLastRun:false};delete current.mainRestartRecovery;delete current.restartRecoveryDeliverySourceRunId;
  if(change==='postcommit_crash')throw Error('simulated response lost after commit');
  return 'settled';
 }};
try{const result=await retireReviewedFailure({directory:input.directory,entry:e,sessionKey:'agent:research:synthetic'},api);
 const again=await retireReviewedFailure({directory:input.directory,entry:current,sessionKey:'agent:research:synthetic'},api);
 console.log(JSON.stringify({ok:true,result,again,committed,checks}));}
catch(e){const again=committed?await retireReviewedFailure({directory:input.directory,entry:current,sessionKey:'agent:research:synthetic'},api):undefined;console.log(JSON.stringify({ok:false,committed,again,error:e.message}));}
