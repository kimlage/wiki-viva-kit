"""Synthetic intent ledger: no native tool, provider, session or grant is executed."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest
from wiki_core.web.source_host import SourceHostPairing
MODULE=Path(__file__).resolve().parents[1]/'integrations/hermes/wiki-viva-board/dashboard/source_access_runtime.py'
spec=importlib.util.spec_from_file_location('fixture_native_intents',MODULE)
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
SHA='a'*64;CONFIG='b'*64
EXECUTION=dict(connection_id='fixture',profile='research',target_profile='research',method='native_session',stored_session_id='stored-fixture')
def service(tmp_path):
 binding=dict(source_id='source-a',context='research',platform='unknown-app',locator='synthetic-resource',binding_sha256=SHA,config_sha256=CONFIG,access_policy={'execution':copy.deepcopy(EXECUTION)})
 runtime=native.SourceAccessRuntime('http://127.0.0.1:8765',profile_matches=lambda p:p=='research',receipt_root=lambda:tmp_path,admit_read=lambda *a:None)
 runtime.binding=lambda *a:copy.deepcopy(binding)
 return runtime,binding
def test_exclusive_claim_is_context_bound_and_never_replays(tmp_path):
 runtime,binding=service(tmp_path)
 first=runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 assert first['created'] and not first['intent']['read_verified']
 assert runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')['created'] is False
 with pytest.raises(native.SourceReadError,match='unknown'):runtime.claim('source-a',SHA,CONFIG,'fixture-request-0002')
 binding['config_sha256']='c'*64
 with pytest.raises(native.SourceReadError,match='configuration_changed'):runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
def test_tracking_never_certifies_identity_permissions_or_provider_content(tmp_path):
 runtime,_=service(tmp_path);runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 for field in ['identity','granted_scopes','read_verified','result','argv']:
  with pytest.raises(native.SourceReadError,match='tracking_invalid'):
   runtime.track('source-a',SHA,CONFIG,'fixture-request-0001',{'status':'native_trace_observed',field:True})
 row=runtime.track('source-a',SHA,CONFIG,'fixture-request-0001',{'status':'native_trace_observed','runtime_session_id':'runtime-fixture','user_row_id':17,'tool_refs':[{'id':'tool-1','name':'unknown-provider-op'}]})
 assert not row['read_verified'] and not row['write_verified'] and not row['grants_verified']
 assert row['identity']=={'status':'unknown'}
 assert runtime.track('source-a',SHA,CONFIG,'fixture-request-0001',{'status':'submitted'})['status']=='native_trace_observed'
 with pytest.raises(native.SourceReadError,match='tracking_invalid'):runtime.track('source-a',SHA,CONFIG,'fixture-request-0001',{'status':'submitted','user_row_id':18})
 assert runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')['created'] is False
 assert runtime.claim('source-a',SHA,CONFIG,'fixture-request-0002')['created'] is True
 assert len(runtime.receipts('source-a',SHA,CONFIG))==2
 assert all(p.stat().st_mode&0o777==0o600 for p in (tmp_path/'wiki-native-intents').glob('*.json'))
def test_wrong_profile_and_missing_native_owner_never_claim(tmp_path):
 runtime,binding=service(tmp_path);binding['access_policy']['execution']['target_profile']='another'
 with pytest.raises(native.SourceReadError,match='profile_mismatch'):runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 assert not (tmp_path/'wiki-native-intents').exists()
@pytest.mark.parametrize('origin',['https://127.0.0.1:8765','http://example.test','http://127.0.0.1/path','http://user@localhost','http://localhost/?redirect=other'])
def test_native_binding_only_reads_fixed_loopback_origin(origin):
 with pytest.raises(native.SourceReadError,match='not_allowlisted'):native.SourceAccessRuntime(origin,profile_matches=None,receipt_root=None)
def test_pairing_remains_one_use_and_bounded(monkeypatch):
 import wiki_core.web.source_host as module
 now=[100.0];monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
 pair=SourceHostPairing();challenge=pair.challenge();assert not pair.status(challenge)['attested']
 assert pair.attest(challenge,'wiki-viva-board')['attested']
 with pytest.raises(ValueError):pair.attest(challenge,'wiki-viva-board')
 now[0]+=46;assert not pair.status(challenge)['attested']

def test_old_claim_can_be_reconciled_after_source_configuration_changes(tmp_path):
 runtime,binding=service(tmp_path);runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 binding['config_sha256']='c'*64
 assert len(runtime.receipts('source-a',SHA,'c'*64))==1
 row=runtime.track('source-a',SHA,CONFIG,'fixture-request-0001',{'status':'native_trace_observed','tool_refs':[{'id':'tool-1','name':'native_tool','outcome':'unknown'}]})
 assert not row['read_verified']
 assert runtime.claim('source-a',SHA,'c'*64,'fixture-request-0002')['created']


def connection_service(tmp_path):
 runtime,binding=service(tmp_path)
 binding['access_policy']={'expected_identity':'corporate@example.test','connection':{k:v for k,v in EXECUTION.items() if k not in {'method','stored_session_id'}}}
 binding['auth']={'method':'mcp','ref':'browser-controller','scopes':['read'],'note':'Browser-only corporate account; do not substitute a personal API account.'}
 return runtime,binding


def test_connection_only_intent_pins_acknowledged_owner_once_without_mutating_source(tmp_path):
 runtime,binding=connection_service(tmp_path);before=copy.deepcopy(binding)
 claim=runtime.claim('source-a',SHA,CONFIG,'fixture-connection-0001')['intent']
 assert claim['execution']['method']=='profile_bot' and 'stored_session_id' not in claim['execution']
 with pytest.raises(native.SourceReadError,match='owner_required'):
  runtime.track('source-a',SHA,CONFIG,claim['request_id'],{'status':'submitted'})
 pinned=runtime.track('source-a',SHA,CONFIG,claim['request_id'],{'status':'pending','owner_stored_session_id':'canonical-tip'})
 assert pinned['owner_stored_session_id']=='canonical-tip'
 with pytest.raises(native.SourceReadError,match='owner_changed'):
  runtime.track('source-a',SHA,CONFIG,claim['request_id'],{'status':'pending','owner_stored_session_id':'another-owner'})
 assert runtime.claim('source-a',SHA,CONFIG,claim['request_id'])['intent']['owner_stored_session_id']=='canonical-tip'
 assert binding==before and not pinned['grants_verified'] and not pinned['read_verified']


def test_profile_stop_holds_new_tests_but_preserves_receipt_recovery(tmp_path):
 runtime,_=connection_service(tmp_path)
 row=runtime.claim('source-a',SHA,CONFIG,'fixture-connection-0001')['intent']
 runtime.profile_stopped=lambda:True
 assert runtime.public_binding(runtime.binding())['execution_hold']=='profile_stopped'
 assert runtime.claim('source-a',SHA,CONFIG,row['request_id'])['created'] is False
 with pytest.raises(native.SourceReadError,match='profile_stopped'):
  runtime.claim('source-a',SHA,CONFIG,'fixture-connection-0002')
 assert len(runtime.receipts('source-a',SHA,CONFIG))==1
 assert runtime.track('source-a',SHA,CONFIG,row['request_id'],{'status':'not_submitted'})['status']=='not_submitted'


def test_new_connection_cannot_erase_method_or_claim_an_ambiguous_account(tmp_path):
 runtime,binding=connection_service(tmp_path)
 binding['access_policy']['expected_identity']=''
 with pytest.raises(native.SourceReadError,match='identity_ambiguous'):
  runtime.claim('source-a',SHA,CONFIG,'fixture-connection-0001')
 binding['access_policy']['connection'].update(provider_id='fictional-provider',account_id='declared-account',account_alias='research')
 row=runtime.claim('source-a',SHA,CONFIG,'fixture-connection-0001')['intent']
 assert binding['auth']['note'] in row['prompt']
 assert 'A connection reference cannot replace a browser-only restriction with an API or a different account.' in row['prompt']
 assert json.loads(row['prompt'].split('\n')[-1])['auth']==binding['auth']
 assert not row['read_verified'] and not row['grants_verified']


def test_passive_host_cannot_start_a_read_without_kernel_admission(tmp_path):
 runtime,binding=service(tmp_path)
 runtime.admit_read=None
 assert runtime.public_binding(binding)['execution_hold']=='source_authorization_unavailable'
 with pytest.raises(native.SourceReadError,match='authorization_unavailable'):
  runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 assert not list((tmp_path/'wiki-native-intents').glob('*.json'))


def test_failed_admission_cannot_be_overridden_by_source_labels_or_account(tmp_path):
 runtime,binding=connection_service(tmp_path)
 def deny(*args): raise PermissionError('private diagnostic must not escape')
 runtime.admit_read=deny
 with pytest.raises(native.SourceReadError,match='^source_authorization_denied$'):
  runtime.claim('source-a',SHA,CONFIG,'fixture-request-0001')
 assert not list((tmp_path/'wiki-native-intents').glob('*.json'))
