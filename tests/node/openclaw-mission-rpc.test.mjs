import {test} from 'node:test';
import assert from 'node:assert/strict';
import {requestOptions,safeFailure} from '../../scripts/openclaw/mission-rpc.mjs';
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
