/** Version-bound, fail-closed mission admission. Never logs prompts or credentials. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const threads = new Map();
const hooks = new Set();
let expectedHooks;
export function configureRuntime(names) { require(!expectedHooks, 'runtime_already_configured'); expectedHooks = new Set(names); }
export function loadedHook(name) { require(expectedHooks?.has(name), 'unknown_hook'); hooks.add(name); }
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
function load(runId) {
  require(typeof runId === 'string' && /^wiki-run-[a-f0-9]{32}$/.test(runId), 'invalid_run');
  const dir = directory(), runDir = path.join(dir, runId);
  require(fs.realpathSync(runDir) === runDir, 'run_symlink');
  const raw = read(path.join(runDir, 'mission.json'));
  const m = JSON.parse(raw), active = JSON.parse(read(path.join(dir, 'mission-active.json')));
  require(m.schema_version === 'wiki_openclaw_mission.v1' && m.run_id === runId && active.run_id === runId && active.contract_sha256 === sha(raw), 'contract_changed');
  require(typeof m.expires_at === 'string' && Date.parse(m.expires_at) > Date.now(), 'expired');
  require(m.provider === 'openai' && typeof m.model === 'string' && /^[a-zA-Z0-9._-]+$/.test(m.model) && ['high','max'].includes(m.effort), 'selection_invalid');
  require(typeof m.native_thread_id === 'string' && m.native_thread_id.length > 8 && typeof m.session_id === 'string' && typeof m.session_key === 'string', 'identity_required');
  require(/^[a-f0-9]{64}$/.test(m.message_sha256), 'message_digest_required');
  return {m, hash:sha(raw), runDir};
}
function current(lock) {
  const now = load(lock.m.run_id); require(now.hash === lock.hash, 'contract_changed');
}
export function authorizeChat(params) {
  assertRuntime();
  const lock = load(params?.idempotencyKey), m=lock.m;
  require(params.wikiMission === lock.hash && params.sessionKey === m.session_key && params.sessionId === m.session_id && params.thinking === m.effort && params.suppressCommandInterpretation === true && params.deliver === false && sha(params.message) === m.message_sha256, 'send_mismatch');
  return lock;
}
export function authorizeTurn(params, turn) {
  const lock=load(params.runId), m=lock.m;
  require(params.sessionKey === m.session_key && params.sessionId === m.session_id && params.provider === m.provider && params.modelId === m.model && turn.threadId === m.native_thread_id && turn.model === m.model && turn.effort === m.effort, 'turn_mismatch');
  if (turn.collaborationMode != null) require(turn.collaborationMode.settings?.model === m.model && turn.collaborationMode.settings?.reasoning_effort === m.effort, 'collaboration_mismatch');
  // Durable claim prevents a restarted process or a live model switch from
  // admitting another turn under the same mission. Recovery is inspect-only.
  writeExclusive(path.join(lock.runDir,'guard-turn.json'), {schema_version:'wiki_openclaw_guard_turn.v1',run_id:m.run_id,session_id:m.session_id,thread_id:m.native_thread_id,model:m.model,effort:m.effort,contract_sha256:lock.hash});
  threads.set(m.native_thread_id, lock);
}
export function bindTurn(runId, threadId, turnId) {
  const lock=threads.get(threadId); require(lock && lock.m.run_id===runId && !lock.turnId && typeof turnId==='string' && turnId.length>0, 'turn_binding_mismatch'); current(lock);
  writeExclusive(path.join(lock.runDir,'guard-bound-turn.json'), {run_id:runId,thread_id:threadId,turn_id:turnId,contract_sha256:lock.hash});
  lock.turnId=turnId;
}
export function recordTerminal(threadId, turn) {
  const lock=threads.get(threadId); require(lock && lock.turnId===turn.id, 'terminal_mismatch'); current(lock);
  const value={run_id:lock.m.run_id,thread_id:threadId,turn_id:turn.id,status:turn.status,contract_sha256:lock.hash};
  const file=path.join(lock.runDir,'guard-terminal.json');
  if(fs.existsSync(file)) require(JSON.stringify(JSON.parse(read(file)))===JSON.stringify(value),'terminal_changed');
  else writeExclusive(file,value);
}
export function checkInferenceSelection({path: endpoint,body,metadata,provider}) {
  const threadId = metadata?.threadId;
  const lock=threads.get(threadId);
  require(lock, 'unbound_inference'); current(lock);
  const m=lock.m;
  require(['/responses','/responses/compact'].includes(endpoint) && provider === m.provider && body?.model === m.model && body?.reasoning?.effort === m.effort, 'inference_mismatch');
  require(!metadata.parentThreadId && !metadata.parentTurnId && !metadata.subagent && !['memory','prewarm'].includes(metadata.requestKind), 'auxiliary_inference_not_admitted');
  return lock;
}
export function authorizeInference(input) {
  const lock=checkInferenceSelection(input), m=lock.m;
  const {path:endpoint,body,metadata}=input, threadId=metadata.threadId;
  require(lock.turnId && metadata.turnId === lock.turnId, 'turn_identity_mismatch');
  const record={run_id:m.run_id,thread_id:threadId,turn_id:metadata.turnId,model:body.model,effort:body.reasoning.effort,path:endpoint,contract_sha256:lock.hash};
  require(typeof record.turn_id === 'string' && record.turn_id.length > 0, 'turn_identity_required');
  const fd=fs.openSync(path.join(lock.runDir,'guard-inference.jsonl'),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_APPEND|fs.constants.O_NOFOLLOW,0o600);
  try {fs.writeFileSync(fd,JSON.stringify(record)+'\n');fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
  // This records selection admission, not network completion or billed usage.
  return () => current(lock);
}
