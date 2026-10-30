/** Retire only an expired, independently reconciled original. Never dispatch. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
const repositoryRoot=fs.realpathSync(fileURLToPath(new URL('../../',import.meta.url)));
const require=(ok,code)=>{if(!ok)throw new Error(`wiki_mission_retirement_${code}`);};
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const sorted=value=>Array.isArray(value)?value.map(sorted):value && typeof value==='object'
  ?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sorted(value[key])])):value;
const digest=value=>sha(JSON.stringify(sorted(value)));
export function retirementWorkerArguments(args,carrierUrl,runtimeSource,runtimeGeneration){
  require(Array.isArray(args),'worker_arguments');
  require(!runtimeGeneration,'worker_generation');
  const root=process.env.WIKI_OPENCLAW_CORE_ROOT;
  require(typeof root==='string'&&fs.realpathSync(root)===root,'worker_root');
  for(const value of [carrierUrl,runtimeSource?.moduleUrl,runtimeSource?.sourceLoaderUrl].filter(v=>v!==undefined)){
    const url=new URL(value),file=fileURLToPath(url);
    require(url.protocol==='file:'&&!url.search&&!url.hash&&file.startsWith(root+path.sep+'dist'+path.sep)
      &&fs.realpathSync(file)===file,'worker_source');
  }
  require(carrierUrl!==undefined,'worker_carrier');
  return [...args,'--import',new URL('./mission-worker-loader.mjs',import.meta.url).href];
}
function read(file){
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  try{const stat=fs.fstatSync(fd);require(stat.isFile()&&stat.size<=256000,'invalid_file');return fs.readFileSync(fd);}
  finally{fs.closeSync(fd);}
}
function json(file){return JSON.parse(read(file));}

/** A reviewed receipt is evidence, not a model terminal or a permission grant. */
export function reviewedFailure(directory,entry,sessionKey){
  const run=entry.restartRecoveryDeliverySourceRunId;
  if(typeof run!=='string'||!/^wiki-run-[a-f0-9]{32}$/.test(run))return null;
  require(path.isAbsolute(directory)&&fs.realpathSync(directory)===directory,'directory');
  const dir=path.join(directory,run),file=path.join(dir,'failure-resolution.json');
  if(!fs.existsSync(file))return null;
  require(fs.realpathSync(dir)===dir&&!fs.existsSync(path.join(directory,'mission-active.json')),'active_or_symlink');
  const bytes=read(file),receipt=JSON.parse(bytes),intent=json(path.join(dir,'intent.json')),plan=intent.plan;
  const raw=read(path.join(dir,'mission.json')),m=JSON.parse(raw),hash=sha(raw),e=receipt.evidence,r=receipt.review;
  require(receipt.schema_version==='wiki_openclaw_failure_resolution.v1'&&receipt.status==='resolved_without_result'
    &&receipt.effect_key===run&&receipt.session_id===entry.sessionId&&receipt.plan_sha256===digest(plan)
    &&intent.plan_sha256===digest(plan)&&plan.effect_key===run&&m.plan_sha256===digest(plan)
    &&receipt.evidence_basis==='preserved_observation_independently_reviewed'
    &&receipt.external_effects==='not_determined_by_this_receipt'&&receipt.review_sha256===digest(r)
    &&receipt.evidence_sha256===digest(e)&&sha(receipt.evidence_raw)===r.evidence_sha256
    &&digest(JSON.parse(receipt.evidence_raw))===digest(e),'receipt_changed');
  require(e.status==='expired_interrupted'&&e.runId===run&&e.contract_sha256===hash
    &&e.expires_at===m.expires_at&&Number.isFinite(Date.parse(m.expires_at))&&Date.parse(m.expires_at)<=Date.now()
    &&m.run_id===run&&m.schema_version==='wiki_openclaw_mission.v1'
    &&m.session_key===sessionKey&&m.session_id===entry.sessionId
    &&plan.route.session_key===sessionKey&&plan.route.session_id===entry.sessionId
    &&m.native_thread_id===plan.mission.native_thread_id&&m.model===plan.mission.model.split('/')[1]
    &&m.provider===plan.mission.model.split('/')[0]&&m.effort===plan.mission.effort
    &&m.recovery?.mode==='read_only'&&m.recovery.max_continuations===1,'contract_changed');
  require(r.schema_version==='wiki_openclaw_failure_review.v1'&&r.decision==='resolve_without_result'
    &&r.run_id===run&&r.session_id===m.session_id&&r.plan_sha256===digest(plan)
    &&receipt.action_id===plan.binding.action_id&&r.action_id===receipt.action_id
    &&typeof r.author==='string'&&typeof r.reviewer==='string'&&r.author.trim()!==r.reviewer.trim()
    &&[r.author,r.reviewer,r.reason,r.limits].every(v=>typeof v==='string'&&v.trim().length>=8)
    &&/^[a-f0-9]{40}$/.test(r.head)&&/^[a-f0-9]{64}$/.test(r.action_sha256),'review_changed');
  require(!fs.existsSync(path.join(dir,'result.json'))&&!fs.existsSync(path.join(dir,'guard-terminal.json'))
    &&!fs.readdirSync(dir).some(name=>name.startsWith('guard-recovery')),'result_or_continuation');
  const accepted=json(path.join(dir,'accepted.json')),turn=json(path.join(dir,'guard-turn.json')),
    bound=json(path.join(dir,'guard-bound-turn.json'));
  require(accepted.run_id===run&&accepted.plan_sha256===digest(plan)
    &&turn.run_id===run&&turn.session_id===m.session_id&&turn.thread_id===m.native_thread_id
    &&turn.contract_sha256===hash&&turn.model===m.model&&turn.effort===m.effort
    &&bound.run_id===run&&bound.thread_id===turn.thread_id&&bound.contract_sha256===hash
    &&typeof bound.turn_id==='string'&&bound.turn_id.length>0,'lineage_changed');
  const lines=read(path.join(dir,'guard-inference.jsonl')).toString().trim().split('\n');
  require(lines.length>0&&lines.every(line=>{const i=JSON.parse(line);return !i.native_run_id
    &&['run_id','thread_id','contract_sha256','model','effort'].every(key=>i[key]===turn[key])
    &&i.turn_id===bound.turn_id&&['/responses','/responses/compact'].includes(i.path); }),'inference_changed');
  const root=repositoryRoot;
  require(m.recovery.repo_root===root,'root');
  const git=(...args)=>execFileSync('git',args,{cwd:root,encoding:'utf8',stdio:['ignore','pipe','ignore']}).trim();
  const branch=git('branch','--show-current'),head=git('rev-parse','HEAD');
  // This narrowly qualified native adapter supports the kit's approved main.
  require(branch==='main'&&head===git('rev-parse','refs/remotes/origin/main')
    &&git('status','--porcelain','--untracked-files=all')==='','unapproved_checkout');
  git('merge-base','--is-ancestor',r.head,head);git('merge-base','--is-ancestor',m.recovery.approved_head,head);
  const b=plan.binding;
  require(typeof b.action_path==='string'&&!path.isAbsolute(b.action_path)
    &&!plan.binding.action_path.split('/').includes('..')
    &&sha(read(path.join(root,b.action_path)))===r.action_sha256
    &&sha(execFileSync('git',['show',r.head+':'+b.action_path],{cwd:root,stdio:['ignore','pipe','ignore']}))===r.action_sha256,'action_changed');
  const originalConfig=execFileSync('git',['show',b.base_head+':wiki.config.yaml'],{cwd:root,stdio:['ignore','pipe','ignore']});
  const expected={schema_version:'wiki_openclaw_mission.v1',run_id:run,session_key:plan.route.session_key,
    session_id:plan.route.session_id,native_thread_id:plan.mission.native_thread_id,
    provider:plan.mission.model.split('/')[0],model:plan.mission.model.split('/')[1],effort:plan.mission.effort,
    message_sha256:plan.message_sha256,plan_sha256:digest(plan),action_id:b.action_id,action_sha256:b.action_sha256,
    expires_at:e.expires_at,recovery:{...plan.mission.recovery,repo_root:root,approved_head:b.base_head,
      action_path:b.action_path,action_sha256:b.action_sha256,config_sha256:sha(originalConfig)}};
  require(isDeepStrictEqual(m,expected)&&isDeepStrictEqual(plan.mission.recovery,{mode:'read_only',max_continuations:1})
    &&Object.keys(e).sort().join(',')==='contract_sha256,expires_at,runId,status','contract_changed');
  return {run_id:run,receipt_sha256:sha(bytes),contract_sha256:hash,session_id:m.session_id,
    thread_id:m.native_thread_id};
}

export function assertRetirableEntry(entry,proof){
  const state=entry.mainRestartRecovery;
  require(entry.sessionId===proof.session_id&&entry.abortedLastRun===true&&entry.status==='interrupted'
    &&entry.restartRecoveryDeliverySourceRunId===proof.run_id
    &&typeof entry.restartRecoveryDeliveryRunId==='string'&&entry.restartRecoveryDeliveryRunId!==proof.run_id
    &&state&&typeof state.cycleId==='string'&&Number.isInteger(state.revision)
    &&!state.reservation&&!state.foregroundClaims&&!state.tombstone
    &&!entry.activeWriterRunId&&!entry.pendingFinalDelivery&&!entry.restartRecoveryHarnessCompletion
    &&!entry.restartRecoveryBeforeAgentReplyState&&!entry.restartRecoveryDeliveryReceiptState
    &&(entry.restartRecoveryRuns??[]).every(r=>[proof.run_id,entry.restartRecoveryDeliveryRunId].includes(r.runId)),
    'custody_changed');
}

export function retirementObservationMatches(full,observed,projection='full'){
  if(projection==='full')return isDeepStrictEqual(full,observed);
  require(projection==='list','observation_projection');
  // Exactly the three snapshots omitted by the pinned native list reader.
  const list=structuredClone(full);
  for(const key of ['sessionDiffBaseline','skillsSnapshot','systemPromptReport'])delete list[key];
  return isDeepStrictEqual(list,observed);
}

/** APIs are supplied only by the version-qualified native recovery owner. */
export async function retireReviewedFailure(params,api){
  if(typeof params.entry?.restartRecoveryDeliverySourceRunId!=='string'
    ||!/^wiki-run-[a-f0-9]{32}$/.test(params.entry.restartRecoveryDeliverySourceRunId))return null;
  const captured=api.load();
  require(retirementObservationMatches(captured,params.entry,params.observationProjection),'observation_changed');
  const proof=reviewedFailure(params.directory,captured,params.sessionKey);
  if(!proof)return null;
  return api.exclusive(async()=>{
    const entry=api.load();assertRetirableEntry(entry,proof);
    require(isDeepStrictEqual(entry,captured),'observation_changed');
    const snapshot=structuredClone(entry);
    const assertCurrent=()=>{
      api.assertCurrent();
      require(JSON.stringify(reviewedFailure(params.directory,snapshot,params.sessionKey))===JSON.stringify(proof),'receipt_replaced');
      require(!api.competing()&&!api.liveOwner()&&api.pendingEmpty(),'new_custody');
    };
    assertCurrent();
    return api.settle(entry,{
      reason:`reviewed expired mission ${proof.run_id} reconciled without result (receipt ${proof.receipt_sha256}); external effects undetermined; lifecycle end time records this retirement only`,
      assertCurrent,snapshot
    });
  });
}
