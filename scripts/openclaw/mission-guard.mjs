/** Version-bound, fail-closed mission admission. Never logs prompts or credentials. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {assertOwner,assertCapture,markNativeHook} from './mission-runtime.mjs';
export {captureOwner,registerNativeArtifact} from './mission-runtime.mjs';
const threads = new Map();
const creations = new WeakSet(), createdThreads = new Map();
const bindings = new WeakMap(), routes = new WeakMap();
const recoveries = new Map();
const TURN_HOOK='run-attempt-CGHsrfPB.mjs';
const INFERENCE_HOOK='inference-dispatch-CO6tTs4q.mjs';
const ROUTE_HOOK='shared-client-C0gEybHs.mjs';
const CREATION_HOOK='thread-lifecycle-run-BHM-L-56.mjs';
const hooks = new Set();
let expectedHooks,clientAdmission;
export function configureRuntime(names,admitClient) { require(!expectedHooks, 'runtime_already_configured'); expectedHooks = new Set(names); clientAdmission=admitClient; }
export function authorizeClientStart(options) { require(typeof clientAdmission==='function','client_pin_required'); clientAdmission(options); }
export function loadedHook(name,url) { require(expectedHooks?.has(name), 'unknown_hook'); markNativeHook(name,url); hooks.add(name); }
export function assertRuntime() { require(expectedHooks?.size > 0 && hooks.size === expectedHooks.size && [...expectedHooks].every(name=>hooks.has(name)), 'incomplete_overlay'); }
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const require = (test, code) => { if (!test) throw new Error(`wiki_mission_${code}`); };
function directory() {
  const dir = process.env.WIKI_OPENCLAW_MISSION_DIR;
  require(typeof dir === 'string' && path.isAbsolute(dir), 'directory_required');
  require(fs.realpathSync(dir) === dir, 'directory_symlink');
  return dir;
}
function read(file) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const stat = fs.fstatSync(fd); require(stat.isFile() && stat.size <= 32768, 'invalid_file');
    return fs.readFileSync(fd);
  } finally { fs.closeSync(fd); }
}
function writeExclusive(file, value) {
  const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(value)+'\n'); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
}
function load(runId, permission=true) {
  require(typeof runId === 'string' && /^wiki-run-[a-f0-9]{32}$/.test(runId), 'invalid_run');
  const dir = directory(), runDir = path.join(dir, runId);
  require(fs.realpathSync(runDir) === runDir, 'run_symlink');
  const raw = read(path.join(runDir, 'mission.json'));
  const m = JSON.parse(raw), active = JSON.parse(read(path.join(dir, 'mission-active.json')));
  require(m.schema_version === 'wiki_openclaw_mission.v1' && m.run_id === runId && active.run_id === runId && active.contract_sha256 === sha(raw), 'contract_changed');
  require(typeof m.expires_at === 'string' && Number.isFinite(Date.parse(m.expires_at))
    && (!permission || Date.parse(m.expires_at) > Date.now()), 'expired');
  require(m.provider === 'openai' && typeof m.model === 'string' && /^[a-zA-Z0-9._-]+$/.test(m.model) && ['high','max'].includes(m.effort), 'selection_invalid');
  require((m.native_thread_binding === 'first_turn' ? m.native_thread_id === null : m.native_thread_binding === undefined && typeof m.native_thread_id === 'string' && m.native_thread_id.length > 8) && typeof m.session_id === 'string' && typeof m.session_key === 'string', 'identity_required');
  require(/^[a-f0-9]{64}$/.test(m.message_sha256), 'message_digest_required');
  return {m, hash:sha(raw), runDir};
}
function current(lock, permission=true) {
  if(lock.owner) {
    assertOwner(lock.owner,TURN_HOOK);
    assertRoute(lock.route);
    lock.assertRouteCurrent();
  }
  const now = load(lock.m.run_id,permission); require(now.hash === lock.hash, 'contract_changed');
  if(permission && lock.recovery) assertRecoveryContext(lock);
}

function assertRecoveryContext(lock) {
  const r=lock.m.recovery;
  require(r?.mode==='read_only' && r.max_continuations===1 && path.isAbsolute(r.repo_root)
    && fs.realpathSync(r.repo_root)===r.repo_root,'recovery_policy_required');
  const git=(...args)=>execFileSync('git',args,{cwd:r.repo_root,encoding:'utf8',stdio:['ignore','pipe','ignore']}).trim();
  require(git('rev-parse','HEAD')===r.approved_head && git('status','--porcelain','--untracked-files=all')==='', 'recovery_context_changed');
  require(typeof r.action_path==='string' && !path.isAbsolute(r.action_path) && !r.action_path.split('/').includes('..'), 'recovery_context_changed');
  require(sha(read(path.join(r.repo_root,r.action_path)))===r.action_sha256
    && sha(read(path.join(r.repo_root,'wiki.config.yaml')))===r.config_sha256,'recovery_context_changed');
}

/** Only the version-qualified core calls this inside its live recovery admission.
 * A continuation gets a new native run/turn; the original mission is never sent again.
 */
export function authorizeNativeRecovery(agent, sourceRunId, cfg, assertAdmissionCurrent) {
  assertRuntime();
  const lock=load(sourceRunId),m=lock.m;
  require(typeof assertAdmissionCurrent==='function','recovery_admission_required');
  assertAdmissionCurrent();
  const id=agent.idempotencyKey;
  require(typeof id==='string' && /^[a-f0-9-]{36}$/.test(id) && id!==sourceRunId
    && agent.sessionKey===m.session_key && agent.expectedExistingSessionId===m.session_id
    && typeof agent.internalRuntimeHandoffId==='string' && agent.internalRuntimeHandoffId.length>0
    && agent.internalExecutionIdentityRecoveryAttempt===1 && agent.inputProvenance?.kind==='internal_system'
    && agent.deliver===false,'recovery_identity_mismatch');
  const safe=new Set(['read','ls','session_status']);
  const agentCfg=cfg?.agents?.entries?.[agent.agentId];
  const bootstrapOnly=agentCfg?.tools;
  // Native normalization owns optional keys with undefined values. They are
  // absent policy, unlike null/false/empty defined overrides.
  const definedKeys=value=>Object.keys(value??{}).filter(key=>value[key]!==undefined);
  const sandbox=agentCfg?.sandbox;
  require(agentCfg && Array.isArray(cfg.tools?.allow) && cfg.tools.allow.length>0
    && cfg.tools.allow.every(t=>safe.has(t)) && !cfg.tools.alsoAllow && !cfg.tools.byProvider
    && (!bootstrapOnly || definedKeys(bootstrapOnly).length===1 && definedKeys(bootstrapOnly.exec).length===1 && bootstrapOnly.exec.mode==='ask')
    && cfg.tools.fs?.workspaceOnly===true && sandbox?.mode==='all' && sandbox.workspaceAccess==='ro'
    && sandbox.backend==='docker' && sandbox.docker?.readOnlyRoot===true && sandbox.docker.network==='none',
    'recovery_tools_not_qualified');
  lock.recovery={native_run_id:id};assertRecoveryContext(lock);
  const original=JSON.parse(read(path.join(lock.runDir,'guard-bound-turn.json')));
  require(original.run_id===sourceRunId && original.thread_id===m.native_thread_id
    && original.contract_sha256===lock.hash && typeof original.turn_id==='string' && original.turn_id.length>0
    && (original.session_id===undefined || original.session_id===m.session_id),'recovery_original_turn_required');
  const terminalFile=path.join(lock.runDir,'guard-terminal.json');
  require(!fs.existsSync(terminalFile) || JSON.parse(read(terminalFile)).status!=='completed','recovery_already_completed');
  const claim={schema_version:'wiki_openclaw_recovery.v1',run_id:sourceRunId,native_run_id:id,
    session_id:m.session_id,thread_id:m.native_thread_id,source_turn_id:original.turn_id,
    contract_sha256:lock.hash,model:m.model,effort:m.effort};
  if(recoveries.has(id)) {
    require(recoveries.get(id).hash===lock.hash,'recovery_changed');
  } else {
    // No reconstruction of a consumed admission from disk after another crash.
    writeExclusive(path.join(lock.runDir,'guard-recovery.json'),claim);
    recoveries.set(id,lock);
  }
  agent.model=`${m.provider}/${m.model}`;agent.thinking=m.effort;
  agent.forceRestartSafeTools=true;
  return ()=>{assertAdmissionCurrent();current(lock);};
}
export function authorizeChat(params) {
  assertRuntime();
  const lock = load(params?.idempotencyKey), m=lock.m;
  require(params.wikiMission === lock.hash && params.sessionKey === m.session_key && params.sessionId === m.session_id && params.thinking === m.effort && params.suppressCommandInterpretation === true && params.deliver === false && sha(params.message) === m.message_sha256, 'send_mismatch');
  return lock;
}
// Called inside the native final admission transaction, before input insertion.
export function authorizeAdmission(params, relation, sessionId) {
  const lock=authorizeChat(params);
  if(lock.m.native_thread_binding !== 'first_turn') return;
  require(params.expectedLeafEntryId === null && relation === 'exact' && sessionId === lock.m.session_id,'bootstrap_not_empty');
  writeExclusive(path.join(lock.runDir,'guard-bootstrap-admission.json'),{run_id:lock.m.run_id,session_id:sessionId,contract_sha256:lock.hash});
}
export function beginBootstrapThread(params,client,saved,owner,assertCurrent) {
  const lock=recoveries.get(params.runId) ?? load(params.runId),m=lock.m;
  if(lock.recovery) {
    assertOwner(owner,CREATION_HOOK);current(lock);assertCurrent();
    require(saved && saved.threadId===m.native_thread_id && params.sessionId===m.session_id
      && params.sessionKey===m.session_key && params.provider===m.provider && params.modelId===m.model,
      'recovery_existing_thread_required');
    return null;
  }
  if(m.native_thread_binding !== 'first_turn') return null;
  assertOwner(owner,CREATION_HOOK);
  require(!saved && client && typeof assertCurrent==='function' && params.sessionId===m.session_id && params.sessionKey===m.session_key && params.provider===m.provider && params.modelId===m.model,'bootstrap_existing_binding');
  assertCurrent();
  const admission=JSON.parse(read(path.join(lock.runDir,'guard-bootstrap-admission.json')));
  require(admission.run_id===m.run_id && admission.session_id===m.session_id && admission.contract_sha256===lock.hash,'bootstrap_admission_required');
  writeExclusive(path.join(lock.runDir,'guard-bootstrap-start.json'),admission);
  const creation={lock,client,owner,assertCurrent};creations.add(creation);return creation;
}
function currentCreation(creation) {
  require(creation && creations.has(creation),'bootstrap_creation_required');
  assertOwner(creation.owner,CREATION_HOOK);
  // The native binding lease ends when lifecycle preparation returns. Once
  // committed, the turn's own authority and exact route guard take over.
  if(!creation.threadId)creation.assertCurrent();
  current(creation.lock);
}
export function completeBootstrapThread(creation,started) {
  if(creation===null)return;
  currentCreation(creation);
  const {lock}=creation,m=lock.m;
  require(!creation.threadId && typeof started?.threadId==='string' && started.threadId.length>8 && !createdThreads.has(started.threadId) && !threads.has(started.threadId) && started.lifecycle?.action==='started' && !started.lifecycle.preserveExistingBinding && !started.lifecycle.rotatedContextEngineBinding && started.model===m.model && started.modelProvider===m.provider,'bootstrap_thread_mismatch');
  writeExclusive(path.join(lock.runDir,'guard-bootstrap-thread.json'),{run_id:m.run_id,session_id:m.session_id,thread_id:started.threadId,model:m.model,contract_sha256:lock.hash});
  creation.threadId=started.threadId;createdThreads.set(started.threadId,creation);
}
function assertBinding(binding,runtime=true) {
  require(binding && bindings.get(binding.fn)===binding,'inference_binding_required');
  (runtime ? assertOwner : assertCapture)(binding.owner,INFERENCE_HOOK);
  binding.assertCurrent();
}
function assertRoute(route) {
  require(route && routes.get(route.handle)===route,'inference_route_required');
  assertBinding(route.binding);
  assertOwner(route.owner,ROUTE_HOOK);
  route.handle.assertCurrent();
}
export function registerInferenceBinding(fn,client,provider,owner,assertCurrent) {
  assertCapture(owner,INFERENCE_HOOK);
  require(typeof fn==='function' && !bindings.has(fn) && client && typeof client==='object' && provider==='openai' && typeof assertCurrent==='function','inference_binding_invalid');
  assertCurrent();bindings.set(fn,{fn,client,provider,owner,assertCurrent});return fn;
}
export function registerInferenceRoute(client,fn,handle,owner) {
  const binding=bindings.get(fn);assertBinding(binding,false);
  assertCapture(owner,ROUTE_HOOK);
  require(!binding.route && binding.client===client && binding.owner.record===owner.record && handle && typeof handle==='object' && typeof handle.assertCurrent==='function' && !routes.has(handle),'inference_route_invalid');
  handle.assertCurrent();const route={handle,binding,owner};binding.route=route;routes.set(handle,route);return handle;
}
export function authorizeTurn(params, turn, owner,client,handle,assertRouteCurrent) {
  assertOwner(owner,TURN_HOOK);
  const route=routes.get(handle);assertRoute(route);
  require(route.binding.client===client && typeof assertRouteCurrent==='function','turn_route_mismatch');
  assertRouteCurrent();
  const lock=recoveries.get(params.runId) ?? load(params.runId), m=lock.m;
  if(lock.recovery) current(lock);
  if(m.native_thread_binding==='first_turn') {
    const creation=createdThreads.get(turn.threadId);currentCreation(creation);
    require(creation.lock.hash===lock.hash && creation.client===client && creation.owner.record===owner.record,'bootstrap_turn_mismatch');
  } else require(turn.threadId===m.native_thread_id,'turn_mismatch');
  require(params.sessionKey === m.session_key && params.sessionId === m.session_id && params.provider === m.provider && params.modelId === m.model && turn.model === m.model && turn.effort === m.effort, 'turn_mismatch');
  if (turn.collaborationMode != null) require(turn.collaborationMode.settings?.model === m.model && turn.collaborationMode.settings?.reasoning_effort === m.effort, 'collaboration_mismatch');
  // Durable claim prevents a restarted process or a live model switch from
  // admitting another turn under the same mission. Recovery is inspect-only.
  writeExclusive(path.join(lock.runDir,lock.recovery?'guard-recovery-turn.json':'guard-turn.json'), {schema_version:'wiki_openclaw_guard_turn.v1',run_id:m.run_id,...lock.recovery,session_id:m.session_id,thread_id:turn.threadId,model:m.model,effort:m.effort,contract_sha256:lock.hash});
  lock.owner=owner;
  lock.route=route;lock.assertRouteCurrent=assertRouteCurrent;
  threads.set(turn.threadId, lock);
  return () => current(lock);
}
export function bindTurn(runId, threadId, turnId) {
  const lock=threads.get(threadId); require(lock && (lock.recovery?.native_run_id ?? lock.m.run_id)===runId && !lock.turnId && typeof turnId==='string' && turnId.length>0, 'turn_binding_mismatch'); current(lock);
  writeExclusive(path.join(lock.runDir,lock.recovery?'guard-recovery-bound-turn.json':'guard-bound-turn.json'), {run_id:lock.m.run_id,...lock.recovery,thread_id:threadId,turn_id:turnId,contract_sha256:lock.hash});
  lock.turnId=turnId;
}
export function recordTerminal(threadId, turn) {
  const lock=threads.get(threadId); require(lock && lock.turnId===turn.id, 'terminal_mismatch'); current(lock,false);
  const value={run_id:lock.m.run_id,...lock.recovery,thread_id:threadId,turn_id:turn.id,status:turn.status,contract_sha256:lock.hash};
  const file=path.join(lock.runDir,lock.recovery?'guard-recovery-terminal.json':'guard-terminal.json');
  if(fs.existsSync(file)) require(JSON.stringify(JSON.parse(read(file)))===JSON.stringify(value),'terminal_changed');
  else writeExclusive(file,value);
}
export function checkInferenceSelection({path: endpoint,body,metadata,provider,binding:fn}) {
  const binding=bindings.get(fn);assertBinding(binding);
  const threadId = metadata?.threadId;
  const lock=threads.get(threadId);
  require(lock, 'unbound_inference'); current(lock);
  require(binding===lock.route.binding && provider===binding.provider, 'inference_route_mismatch');
  const m=lock.m;
  require(['/responses','/responses/compact'].includes(endpoint) && provider === m.provider && body?.model === m.model && body?.reasoning?.effort === m.effort, 'inference_mismatch');
  require(!metadata.parentThreadId && !metadata.parentTurnId && !metadata.subagent && !['memory','prewarm'].includes(metadata.requestKind), 'auxiliary_inference_not_admitted');
  return lock;
}
export function authorizeInference(input) {
  const lock=checkInferenceSelection(input), m=lock.m;
  const {path:endpoint,body,metadata}=input, threadId=metadata.threadId;
  require(lock.turnId && metadata.turnId === lock.turnId, 'turn_identity_mismatch');
  const record={run_id:m.run_id,...lock.recovery,thread_id:threadId,turn_id:metadata.turnId,model:body.model,effort:body.reasoning.effort,path:endpoint,contract_sha256:lock.hash};
  require(typeof record.turn_id === 'string' && record.turn_id.length > 0, 'turn_identity_required');
  const fd=fs.openSync(path.join(lock.runDir,lock.recovery?'guard-recovery-inference.jsonl':'guard-inference.jsonl'),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_APPEND|fs.constants.O_NOFOLLOW,0o600);
  try {fs.writeFileSync(fd,JSON.stringify(record)+'\n');fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
  // This records selection admission, not network completion or billed usage.
  return () => current(lock);
}
