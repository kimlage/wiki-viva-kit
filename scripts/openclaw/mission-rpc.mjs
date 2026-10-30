/** Version-bound native CLI facade. Auth stays in the native resolver, never stdin/argv. */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {validatePackage} from './mission-loader.mjs';
export function requestOptions(input) {
  if (!input || Object.keys(input).sort().join(',') !== 'expectUrl,method,params' ||
      !['chat.history','chat.send','sessions.patch'].includes(input.method) ||
      !input.params || typeof input.params !== 'object' || Array.isArray(input.params)) throw new Error('invalid_rpc_request');
  const url=new URL(input.expectUrl);
  if(url.protocol!=='ws:' || !['127.0.0.1','[::1]'].includes(url.hostname) || !url.port ||
      url.username || url.password || url.search || url.hash || !['','/'].includes(url.pathname)) throw new Error('invalid_rpc_target');
  const extra={sharedStateMode:'read-only',progress:false};
  if(input.method==='chat.send') {
    if(!/^[a-f0-9]{64}$/.test(input.params.wikiMission) || input.params.suppressCommandInterpretation!==true || input.params.deliver!==false) throw new Error('mission_required');
    // The native handler requires this scope for command-suppressed input.
    // Request it through the existing authenticated CLI identity; never change grants.
    extra.scopes=['operator.admin'];
  }
  return {opts:{expectUrl:input.expectUrl,json:true,timeout:'20000'},extra};
}
export function safeFailure(error) {
  const codes=['INVALID_REQUEST','UNAVAILABLE','FORBIDDEN','UNAUTHORIZED','NOT_FOUND','TIMEOUT'];
  const code=codes.includes(error?.gatewayCode)?error.gatewayCode:'UNKNOWN';
  return {type:code==='UNKNOWN'?'transport_or_local':'rpc_rejection',code,
    reason:error?.message==='system provenance fields require admin scope'?'system_provenance_requires_admin':'native_call_failed'};
}
async function main() {
  try {
    let raw='';for await(const part of process.stdin) {raw+=part;if(raw.length>131072)throw new Error('input_too_large');}
    const input=JSON.parse(raw),{opts,extra}=requestOptions(input);
    const root=process.argv[2],manifest=JSON.parse(fs.readFileSync(new URL('./mission-overlay.json',import.meta.url),'utf8'));
    validatePackage(root,manifest.packages.core);
    const native=await import(pathToFileURL(path.join(root,'dist/gateway-rpc.runtime.js')).href);
    const result=await native.callGatewayFromCliRuntime(input.method,opts,input.params,extra);
    process.stdout.write(JSON.stringify(result)+'\n');
  } catch(error) {process.stdout.write(JSON.stringify({ok:false,error:safeFailure(error)})+'\n');process.exitCode=1;}
}
if(process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url) await main();
