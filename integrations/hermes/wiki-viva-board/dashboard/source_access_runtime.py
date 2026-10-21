"""Source-bound native read receipts. No credential export or browser assertions.

The native plugin API supplies its authenticated profile scope and its canonical
Git reader. The wiki supplies the source configuration and repository scope.
"""
from pathlib import Path
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class SourceReadError(ValueError):
    pass


class SourceAccessRuntime:
    def __init__(self, wiki_origin, *, profile_matches, receipt_root, repo_reader, head_reader, managed_reader=None):
        origin = urllib.parse.urlsplit(wiki_origin)
        if origin.scheme != 'http' or origin.hostname not in {'127.0.0.1', 'localhost', '::1'} or origin.path not in {'', '/'} or origin.query or origin.fragment or origin.username or origin.password:
            raise SourceReadError('wiki_origin_not_allowlisted')
        self.wiki_origin = wiki_origin.rstrip('/')
        self.profile_matches = profile_matches
        self.receipt_root = receipt_root
        self.repo_reader = repo_reader
        self.head_reader = head_reader
        self.managed_reader = managed_reader

    def attest_host(self, challenge):
        if not re.fullmatch(r'[a-f0-9]{48}', challenge):
            raise SourceReadError('source_host_challenge_invalid')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise SourceReadError('source_binding_redirect_refused')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
        with opener.open(self.wiki_origin + '/api/health', timeout=8) as response:
            security = json.loads(response.read(100_000))['operator_security']
        # Existing local operator CSRF nonce: backend-to-backend, memory only.
        # Never returned to either frame, stored in a receipt, or logged.
        body = json.dumps({'challenge': challenge, 'host_id': 'wiki-viva-board'}).encode()
        request = urllib.request.Request(self.wiki_origin + '/api/source-host/attest', data=body,
            headers={'Content-Type': 'application/json', 'Origin': self.wiki_origin,
                     security['nonce_header']: security['nonce'], security['attempt_header']: 'source-host-' + challenge}, method='POST')
        with opener.open(request, timeout=8) as response:
            result = json.loads(response.read(10_000))
        if result.get('attested') is not True:
            raise SourceReadError('source_host_not_allowed')
        return {'attested': True}

    def binding(self, source_id, expected_sha):
        if not re.fullmatch(r'[\w-]{1,160}', source_id) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha):
            raise SourceReadError('source_binding_invalid')
        url = self.wiki_origin + '/api/sources/' + urllib.parse.quote(source_id, safe='') + '/access-binding'
        # Fixed trusted loopback; no auth header, browser cookie or redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise SourceReadError('source_binding_redirect_refused')
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(url, timeout=8) as response:
                raw = response.read(100_001)
        except urllib.error.HTTPError as exc:
            try:
                code = json.loads(exc.read(10_000)).get('error', '')
            except (OSError, ValueError):
                code = ''
            if code in {'source_access_repository_locator_mismatch', 'source_access_resource_not_supported', 'source_operation_unknown_source', 'source_operation_invalid_recipe'}:
                raise SourceReadError(code) from None
            raise SourceReadError('source_configuration_unavailable') from None
        if len(raw) > 100_000:
            raise SourceReadError('source_binding_too_large')
        value = json.loads(raw)
        if value.get('source_id') != source_id or value.get('binding_sha256') != expected_sha:
            raise SourceReadError('source_binding_changed')
        if not re.fullmatch(r'[a-f0-9]{64}', str(value.get('config_sha256', ''))):
            raise SourceReadError('source_configuration_invalid')
        return value

    @staticmethod
    def public_binding(binding):
        return {k: binding.get(k) for k in ('source_id', 'context', 'platform', 'source_kind', 'config_sha256', 'binding_sha256', 'access_policy', 'resource_options')}

    def _scope(self, binding):
        execution = (binding.get('access_policy') or {}).get('execution') or {}
        if not execution or not self.profile_matches(execution.get('target_profile', '')):
            raise SourceReadError('executor_profile_mismatch')
        return execution

    async def read_test(self, source_id, expected_sha, config_sha, request_id):
        if not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_id):
            raise SourceReadError('source_request_invalid')
        binding = await asyncio.to_thread(self.binding, source_id, expected_sha)
        if binding['config_sha256'] != config_sha:
            raise SourceReadError('source_configuration_changed')
        execution = self._scope(binding)
        directory = Path(self.receipt_root()) / 'wiki-source-access'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / (hashlib.sha256(request_id.encode()).hexdigest() + '.json')
        fingerprint = digest({'source_id': source_id, 'binding_sha256': expected_sha, 'config_sha256': config_sha, 'execution': execution})
        pending = {'schema_version': 'wiki_native_source_read.v1', 'request_id': request_id,
                   'request_sha256': fingerprint, 'source_id': source_id, 'binding_sha256': expected_sha,
                   'config_sha256': config_sha, 'status': 'pending', 'execution': execution,
                   'executor_pid': os.getpid(), 'identity': {'status': 'unknown'},
                   'write_verified': False, 'grant_started': False}
        try:
            with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as f:
                json.dump(pending, f, sort_keys=True)
        except FileExistsError:
            try:
                prior = json.loads(target.read_text())
            except ValueError:
                return {'status': 'pending', 'request_id': request_id}
            if prior.get('request_sha256') != fingerprint:
                raise SourceReadError('source_request_reused')
            return prior  # Reconcile, never rerun a timed-out request.
        receipt = dict(pending)
        now = dt.datetime.now(dt.timezone.utc)
        receipt.update(checked_at=now.isoformat(), valid_until=(now + dt.timedelta(minutes=5)).isoformat())
        try:
            if execution.get('method') == 'managed_connector' and self.managed_reader:
                result = await self.managed_reader(binding)
                latest = await asyncio.to_thread(self.binding, source_id, expected_sha)
                if latest['config_sha256'] != config_sha or latest.get('access_policy') != binding.get('access_policy'):
                    raise SourceReadError('source_configuration_changed')
                receipt.update(result)
            elif execution.get('method') != 'local_git':
                receipt.update(status='unsupported', error_code='source_read_adapter_not_implemented')
            else:
                scope = binding.get('read_scope') or {}
                if scope.get('kind') != 'wiki_repository' or binding.get('source_kind') != 'repository' or execution.get('resource_ref') != 'wiki_repository':
                    raise SourceReadError('source_resource_not_supported')
                # Only the canonical wiki endpoint supplies this path. No browser path.
                path = scope.get('repository_root')
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise SourceReadError('source_resource_invalid')
                before = await asyncio.to_thread(self.head_reader, path)
                data = await self.repo_reader(path)
                after = await asyncio.to_thread(self.head_reader, path)
                latest = await asyncio.to_thread(self.binding, source_id, expected_sha)
                if latest['config_sha256'] != config_sha or latest.get('access_policy') != binding.get('access_policy'):
                    raise SourceReadError('source_configuration_changed')
                if not isinstance(data, dict) or not re.fullmatch(r'[a-f0-9]{40,64}', before or '') or before != after:
                    raise SourceReadError('source_changed_during_read')
                receipt.update(status='read_verified', scope={'kind': 'wiki_repository', 'resource_sha256': digest(path), 'source_scope': scope.get('source_scope')},
                    commit_before=before, commit_after=after, identity={'status': 'not_applicable'},
                    observed_permissions=['git.metadata.read'], data_summary={'changed': data.get('changed'), 'detached': data.get('detached')})
        except Exception as exc:
            code = str(exc) if isinstance(exc, SourceReadError) else 'source_read_failed'
            if getattr(exc, 'status_code', None) == 403:
                code = 'source_policy_denied'
            receipt.update(status='blocked', error_code=code)
        temporary = target.with_suffix('.tmp')
        with os.fdopen(os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as f:
            json.dump(receipt, f, sort_keys=True)
        temporary.replace(target)
        return receipt

    def receipts(self, source_id, expected_sha, config_sha):
        binding = self.binding(source_id, expected_sha)
        if binding['config_sha256'] != config_sha:
            raise SourceReadError('source_configuration_changed')
        self._scope(binding)
        directory = Path(self.receipt_root()) / 'wiki-source-access'
        rows = []
        for path in directory.glob('*.json'):
            try:
                row = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if row.get('source_id') == source_id and row.get('binding_sha256') == expected_sha and row.get('config_sha256') == config_sha and row.get('execution') == binding['access_policy']['execution']:
                rows.append(row)
        return sorted(rows, key=lambda r: r.get('checked_at', ''), reverse=True)[:10]
