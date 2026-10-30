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
