"""One fixed, account-bound read via Hermes' existing managed connector client.

Tool/schema and active named account are rechecked before dispatch. No search,
connection request, reconnect, policy change, fallback account or mail content.
Clients and the call factory are injected so tests need no account or network.
"""
import re


class ManagedReadError(ValueError):
    pass


def gmail_profile_read(binding, portal, gateway, call_factory):
    policy = binding.get('access_policy') or {}
    execution = policy.get('execution') or {}
    if binding.get('platform') != 'gmail' or binding.get('source_kind') != 'account' or execution.get('provider_id') != 'gmail':
        raise ManagedReadError('source_read_adapter_not_implemented')
    alias = execution.get('account_alias', '')
    account_id = execution.get('account_id', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', alias) or not re.fullmatch(r'[\w-]{1,160}', account_id):
        raise ManagedReadError('source_account_selection_required')
    expected = policy.get('expected_identity', '')
    if not isinstance(expected, str) or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', expected):
        raise ManagedReadError('source_expected_identity_required')

    def account():
        rows = portal.list_accounts()
        matches = [row for row in rows if row.get('connector') == 'gmail' and row.get('connectionId') == account_id and row.get('alias') == alias and not row.get('disabled')]
        if len(matches) != 1:
            raise ManagedReadError('source_account_selection_changed')
        state = matches[0].get('status')
        if state == 'expired': raise ManagedReadError('session_expired')
        if state == 'revoked': raise ManagedReadError('source_access_revoked')
        if state != 'active': raise ManagedReadError('authorization_missing')
        return matches[0]

    account()
    catalog = gateway.list_connectors()
    connector = next((row for row in catalog if row.get('connector') == 'gmail'), None)
    if not connector or not connector.get('enabled'):
        raise ManagedReadError('source_policy_denied')
    listing = portal.tools('gmail')
    listing = listing.model_dump() if hasattr(listing, 'model_dump') else listing
    tools = listing.get('tools', [])
    tool = next((row for row in tools if row.get('slug') in {'GMAIL_GET_PROFILE', 'GET_PROFILE'} and row.get('facet') == 'read' and not row.get('deprecated')), None)
    if not tool:
        raise ManagedReadError('source_read_adapter_not_implemented')
    if any(name in connector.get('gateway_disabled_tools', []) for name in {'GET_PROFILE', 'GMAIL_GET_PROFILE'}):
        raise ManagedReadError('source_policy_denied')
    name = 'connectors__gmail__GET_PROFILE'
    schemas = gateway.schemas([name]).get('schemas', {})
    schema = schemas.get(name)
    if not isinstance(schema, dict) or schema.get('connector') != 'gmail' or schema.get('tool') not in {'GET_PROFILE', 'GMAIL_GET_PROFILE'}:
        raise ManagedReadError('source_read_schema_mismatch')
    inputs = schema.get('input_schema') or {}
    properties = inputs.get('properties') or {}
    selectors = [key for key in ('user_id', 'userId') if key in properties]
    if len(selectors) != 1 or set(inputs.get('required') or []) - {selectors[0]}:
        raise ManagedReadError('source_read_schema_mismatch')
    # The gateway strips connector_alias and resolves exactly that account.
    # No caller-supplied provider tool or arguments reach execute.
    arguments = {selectors[0]: 'me', 'connector_alias': alias}
    rows = gateway.execute([call_factory(position=0, name=name, connector='gmail', tool=schema['tool'], arguments=arguments)])
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ManagedReadError('source_read_failed')
    row = rows[0]
    error = row.get('error') or {}
    if error:
        # Never return auth URLs or automatically follow them. The native gateway
        # may mint a CONNECTION_REQUIRED link; it is not a completed OAuth grant.
        code = error.get('code')
        if code == 'CONNECTION_REQUIRED':
            return {'status': 'blocked', 'error_code': 'authorization_missing', 'connection_flow_status': 'native_gateway_reported_connection_required'}
        raise ManagedReadError('source_policy_denied' if code == 'TOOL_NOT_ALLOWED' else 'source_read_failed')
    if row.get('connector') != 'gmail' or row.get('tool') not in {'GET_PROFILE', 'GMAIL_GET_PROFILE'} or row.get('account') != alias:
        raise ManagedReadError('source_account_selection_changed')
    data = row.get('data')
    # Only these documented envelope layers and the Gmail profile identity are
    # consumed. Message counts/content and provider diagnostics are discarded.
    for _ in range(3):
        if not isinstance(data, dict): break
        email = data.get('emailAddress')
        if isinstance(email, str): break
        data = data.get('data')
    email = data.get('emailAddress') if isinstance(data, dict) else None
    if not isinstance(email, str) or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email):
        raise ManagedReadError('source_identity_not_observed')
    if email.casefold() != expected.casefold():
        return {'status': 'blocked', 'error_code': 'wrong_account', 'identity': {'status': 'mismatch', 'confirmed_identity': email}}
    account()  # A reconnect/rename during dispatch invalidates the account proof.
    return {'status': 'read_verified', 'identity': {'status': 'verified', 'confirmed_identity': email},
            'observed_permissions': ['gmail.profile.read'], 'scope': {'kind': 'gmail_account_profile', 'account_id': account_id, 'account_alias': alias},
            'provider_tool': 'GMAIL_GET_PROFILE', 'oauth_scopes_verified': False}
