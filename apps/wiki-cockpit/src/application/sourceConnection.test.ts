import {expect,it} from 'vitest';
import type {SourceAccess,SourceEntity} from '../types';
import {savedSourceRoute,sourceConnectionState} from './sourceConnection';
const now=Date.parse('2026-10-21T12:00:00Z');
const access:SourceAccess={schema_version:'wiki_source_access.v1',binding_sha256:'a'.repeat(64),status:'verified',verified:true,expected_identity:'reader@example.test',confirmed_identity:'reader@example.test',coordinator:'research',executor:'Hermes',requested_scopes:['read'],granted_scopes:['read'],checked_at:'2026-10-21T11:59:00Z',valid_until:'2026-10-21T12:10:00Z',evidence_ref:'receipt:synthetic',error_code:'',execution_ready:false,business_authority:'unknown'};
const source={source_id:'source-a',access,access_policy:{schema_version:'wiki_source_access.v1',expected_identity:'reader@example.test',coordinator:'research',executor:'Hermes',requested_scopes:['read']}} as SourceEntity;
it('requires current identity and scope evidence, not a saved route or account catalogue',()=>{
 expect(sourceConnectionState(source,{now,bindingSha:access.binding_sha256,available:true,accountFound:true,bindingMatches:true,accountsAvailable:true})).toBe('verified');
 for(const change of [{evidence_ref:''},{confirmed_identity:'another@example.test'},{granted_scopes:[]},{valid_until:'2026-10-21T11:59:30Z'},{checked_at:'2026-10-21T12:01:00Z'},{verified:false}]){
  expect(sourceConnectionState({...source,access:{...access,...change}},{now,bindingSha:access.binding_sha256,available:true,accountFound:true})).toBe('unverified');
 }
});
it.each([['revoked','revoked'],['session_expired','expired'],['authority_blocked','no_access'],['awaiting_approval','approval'],['executor_unavailable','executor_unavailable'],['execution_unknown','indeterminate']])('preserves evidenced %s separately from login and generic failure',(status,state)=>{
 const row={...source,access:{...access,status,verified:false}};
 expect(sourceConnectionState(row,{now,bindingSha:access.binding_sha256,available:true})).toBe(state);
 expect(sourceConnectionState({...row,access:{...row.access,evidence_ref:''} as SourceAccess},{now,bindingSha:access.binding_sha256,available:true,accountFound:true})).toBe('unverified');
});
it('does not turn native account-manager authorization or session busy into an expired source login',()=>{
 expect(sourceConnectionState(source,{now,bindingSha:access.binding_sha256,error:'authorization_missing',available:true})).toBe('executor_unavailable');
 expect(sourceConnectionState(source,{now,bindingSha:access.binding_sha256,error:'native_session_busy',available:true})).toBe('busy');
 expect(sourceConnectionState(source,{now,bindingSha:access.binding_sha256,unresolved:true,available:true})).toBe('indeterminate');
});
it('keeps a saved route exact and never falls back to a different default owner',()=>{
 const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local' as const,key:'route'};
 const saved={...source,access_policy:{...source.access_policy!,execution:{connection_id:'fixture',profile:'research',target_profile:'research',method:'native_session' as const,stored_session_id:'stored'}}};
 const other={...route,profile:'default',targetProfile:'default',key:'default'};
 expect(savedSourceRoute(saved,[other,route])).toEqual(route);
 expect(savedSourceRoute(saved,[other])).toBeUndefined();
 expect(savedSourceRoute(source,[other,route])).toBeUndefined();
 expect(savedSourceRoute(source,[route])).toEqual(route);
});

it('rejects missing or stale current binding evidence and keeps kernel hold explicit',()=>{
 expect(sourceConnectionState(source,{now,available:true,accountFound:true})).toBe('unverified');
 expect(sourceConnectionState(source,{now,bindingSha:'b'.repeat(64),available:true,accountFound:true})).toBe('unverified');
 expect(sourceConnectionState(source,{now,error:'source_authorization_unavailable',available:true})).toBe('authorization_hold');
});

it.each([
 {available:true,accountFound:false,bindingMatches:false,accountsAvailable:true},
 {available:true,accountFound:true,bindingMatches:false,accountsAvailable:true},
 {available:true,accountFound:true,bindingMatches:true,accountsAvailable:false},
 {available:false,accountFound:true,bindingMatches:true,accountsAvailable:true},
])('does not keep a historical verified observation green without the exact live connection %j',(live)=>{
 const state=sourceConnectionState(source,{now,bindingSha:access.binding_sha256,...live});
 expect(state).not.toBe('verified');
 expect(['revoked','expired']).not.toContain(state);
});
