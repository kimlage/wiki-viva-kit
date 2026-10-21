"""Synthetic Gmail profile read; never starts a real connection or reads mail."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[1] / 'integrations/hermes/wiki-viva-board/dashboard/managed_source_read.py'
spec = importlib.util.spec_from_file_location('fixture_managed_read', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    binding = {'platform': 'gmail', 'source_kind': 'account', 'access_policy': {'expected_identity': 'reader@example.test', 'execution': {'provider_id': 'gmail', 'account_alias': 'research', 'account_id': 'fixture-account'}}}
    account = {'connector': 'gmail', 'connectionId': 'fixture-account', 'alias': 'research', 'status': 'active', 'disabled': False}
    tool = {'slug': 'GMAIL_GET_PROFILE', 'facet': 'read', 'deprecated': False}
    schema = {'connector': 'gmail', 'tool': 'GMAIL_GET_PROFILE', 'input_schema': {'properties': {'user_id': {'type': 'string'}}, 'required': ['user_id']}}
    result = {'connector': 'gmail', 'tool': 'GMAIL_GET_PROFILE', 'account': 'research', 'data': {'emailAddress': 'reader@example.test', 'messagesTotal': 123, 'historyId': 'never-retained'}, 'error': None}
    calls = []
    class Portal:
        def list_accounts(self): calls.append('accounts'); return [copy.deepcopy(account)]
        def tools(self, slug): calls.append(('tools', slug)); return {'tools': [copy.deepcopy(tool)]}
    class Gateway:
        disabled = []
        def list_connectors(self): return [{'connector': 'gmail', 'enabled': True, 'gateway_disabled_tools': self.disabled}]
        def schemas(self, names): calls.append(('schema', names)); return { 'schemas': {names[0]: copy.deepcopy(schema)}}
        def execute(self, plans): calls.append(('execute', plans)); return [copy.deepcopy(result)]
    portal, gateway = Portal(), Gateway()
    def read(): return module.gmail_profile_read(binding, portal, gateway, SimpleNamespace)
    return binding, account, tool, schema, result, calls, gateway, read


def test_read_proves_only_selected_account_profile_and_discards_provider_content():
    _, _, _, _, _, calls, _, read = fixture()
    result = read()
    assert result['status'] == 'read_verified'
    assert result['identity'] == {'status': 'verified', 'confirmed_identity': 'reader@example.test'}
    assert result['observed_permissions'] == ['gmail.profile.read'] and not result['oauth_scopes_verified']
    assert 'historyId' not in str(result) and '123' not in str(result)
    plan = next(call[1][0] for call in calls if isinstance(call, tuple) and call[0] == 'execute')
    assert plan.connector == 'gmail' and plan.tool == 'GMAIL_GET_PROFILE'
    assert plan.arguments == {'user_id': 'me', 'connector_alias': 'research'}
    assert calls.count('accounts') == 2


@pytest.mark.parametrize('change,code', [('alias', 'account_selection_changed'), ('missing', 'account_selection_required'), ('expired', 'session_expired'), ('revoked', 'access_revoked'), ('facet', 'adapter_not_implemented'), ('deprecated', 'adapter_not_implemented'), ('schema', 'schema_mismatch'), ('disabled', 'policy_denied'), ('platform', 'adapter_not_implemented')])
def test_guard_failures_never_execute_or_start_connection(change, code):
    binding, account, tool, schema, _, calls, gateway, read = fixture()
    if change == 'alias': account['alias'] = 'another'
    if change == 'missing': binding['access_policy']['execution'].pop('account_id')
    if change in {'expired','revoked'}: account['status'] = change
    if change == 'facet': tool['facet'] = 'write'
    if change == 'deprecated': tool['deprecated'] = True
    if change == 'schema': schema['input_schema']['required'] = ['arbitrary_payload']
    if change == 'disabled': gateway.disabled = ['GMAIL_GET_PROFILE']
    if change == 'platform': binding['platform'] = 'drive'
    with pytest.raises(module.ManagedReadError, match=code): read()
    assert not any(isinstance(call,tuple) and call[0] == 'execute' for call in calls)


@pytest.mark.parametrize('change', ['wrong_account','missing_identity','account_changed','connection_required','denied'])
def test_provider_result_cannot_forge_identity_access_or_hide_required_consent(change):
    _, _, _, _, result, _, _, read = fixture()
    if change == 'wrong_account': result['data']['emailAddress'] = 'other@example.test'
    if change == 'missing_identity': result['data'] = {'label': 'reader@example.test'}
    if change == 'account_changed': result['account'] = 'other'
    if change == 'connection_required': result['error'] = {'code':'CONNECTION_REQUIRED','connect_url':'https://example.test/never-echo?code=fixture'}
    if change == 'denied': result['error'] = {'code':'TOOL_NOT_ALLOWED'}
    if change in {'missing_identity','account_changed','denied'}:
        with pytest.raises(module.ManagedReadError): read()
    else:
        receipt = read()
        assert receipt['status'] == 'blocked'
        assert receipt.get('identity',{}).get('status') != 'verified'
        assert not receipt.get('observed_permissions') and 'never-echo' not in str(receipt)
