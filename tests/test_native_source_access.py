"""Public synthetic native-edge contract, without installed services/accounts."""
import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest

from wiki_core.web.source_host import SourceHostPairing

MODULE = Path(__file__).resolve().parents[1] / 'integrations/hermes/wiki-viva-board/dashboard/source_access_runtime.py'
spec = importlib.util.spec_from_file_location('fixture_native_source_access', MODULE)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
SHA = 'a' * 64
CONFIG = 'b' * 64
EXECUTION = dict(connection_id='fixture', profile='research', target_profile='research', method='local_git', provider_id='', resource_ref='wiki_repository')


def service(tmp_path):
    calls = []
    binding = dict(source_id='source-a', context='research', source_kind='repository', binding_sha256=SHA, config_sha256=CONFIG,
                   access_policy={'execution': copy.deepcopy(EXECUTION)},
                   read_scope=dict(kind='wiki_repository', repository_root=str(tmp_path), source_scope='repository_root'))
    async def read(path):
        calls.append(path)
        return {'changed': 2, 'detached': False, 'files': ['private-file-not-retained']}
    runtime = native.SourceAccessRuntime('http://127.0.0.1:8765', profile_matches=lambda p: p == 'research',
        receipt_root=lambda: tmp_path, repo_reader=read, head_reader=lambda p: 'c' * 40)
    runtime.binding = lambda *args: copy.deepcopy(binding)
    return runtime, binding, calls


def run(runtime, request='fixture-request-0001', config=CONFIG):
    return asyncio.run(runtime.read_test('source-a', SHA, config, request))


def test_read_receipt_survives_reopen_without_rerunning_or_claiming_account(tmp_path):
    runtime, binding, calls = service(tmp_path)
    receipt = run(runtime)
    assert receipt['status'] == 'read_verified'
    assert receipt['identity'] == {'status': 'not_applicable'}
    assert receipt['observed_permissions'] == ['git.metadata.read']
    assert not receipt['write_verified'] and not receipt['grant_started']
    assert 'private-file' not in str(receipt) and str(tmp_path) not in str(receipt)
    assert receipt['commit_before'] == receipt['commit_after']
    assert run(runtime) == receipt and len(calls) == 1
    reopened, _, reopened_calls = service(tmp_path)
    assert reopened.receipts('source-a', SHA, CONFIG) == [receipt]
    assert run(reopened) == receipt and not reopened_calls
    binding['config_sha256'] = 'd' * 64
    with pytest.raises(native.SourceReadError, match='configuration_changed'):
        runtime.receipts('source-a', SHA, CONFIG)
    assert runtime.receipts('source-a', SHA, 'd' * 64) == []


def test_wrong_profile_and_stale_configuration_never_read(tmp_path):
    runtime, binding, calls = service(tmp_path)
    binding['access_policy']['execution']['target_profile'] = 'other'
    with pytest.raises(native.SourceReadError, match='profile_mismatch'):
        run(runtime)
    binding['access_policy']['execution']['target_profile'] = 'research'
    with pytest.raises(native.SourceReadError, match='configuration_changed'):
        run(runtime, config='d' * 64)
    assert not calls


@pytest.mark.parametrize('change', ['scope', 'method', 'head', 'config', 'denied'])
def test_failed_read_cannot_produce_positive_receipt(tmp_path, change):
    runtime, binding, calls = service(tmp_path)
    if change == 'scope': binding['read_scope'] = None
    if change == 'method': binding['access_policy']['execution']['method'] = 'mcp'
    if change == 'head':
        heads = iter(['c' * 40, 'e' * 40]); runtime.head_reader = lambda p: next(heads)
    if change == 'config':
        async def changed(path):
            binding['config_sha256'] = 'd' * 64
            return {}
        runtime.repo_reader = changed
    if change == 'denied':
        class Denied(Exception): status_code = 403
        async def denied(path): raise Denied('private message')
        runtime.repo_reader = denied
    result = run(runtime)
    assert result['status'] in {'blocked', 'unsupported'}
    assert result['identity']['status'] == 'unknown'
    assert not result.get('observed_permissions') and 'private message' not in str(result)
    if change == 'denied': assert result['error_code'] == 'source_policy_denied'
    if change in {'scope', 'method'}: assert calls == []


def test_pending_read_reconciles_without_duplicate_execution(tmp_path):
    runtime, binding, calls = service(tmp_path)
    async def interrupted(path):
        raise asyncio.CancelledError()
    runtime.repo_reader = interrupted
    with pytest.raises(asyncio.CancelledError): run(runtime)
    assert run(runtime)['status'] == 'pending' and not calls
    binding['access_policy']['execution']['provider_id'] = 'changed'
    with pytest.raises(native.SourceReadError, match='request_reused'): run(runtime)


@pytest.mark.parametrize('origin', ['https://127.0.0.1:8765', 'http://example.test', 'http://127.0.0.1/path', 'http://user@localhost', 'http://localhost/?redirect=other'])
def test_native_edge_only_reads_fixed_loopback_origin(tmp_path, origin):
    with pytest.raises(native.SourceReadError, match='not_allowlisted'):
        native.SourceAccessRuntime(origin, profile_matches=None, receipt_root=None, repo_reader=None, head_reader=None)


def test_pairing_is_one_use_bounded_and_expires(monkeypatch):
    import wiki_core.web.source_host as module
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    pair = SourceHostPairing(); challenge = pair.challenge()
    assert not pair.status(challenge)['attested']
    with pytest.raises(ValueError): pair.attest(challenge, 'arbitrary-parent')
    assert pair.attest(challenge, 'wiki-viva-board') == {'attested': True}
    with pytest.raises(ValueError): pair.attest(challenge, 'wiki-viva-board')
    assert pair.status(challenge)['attested']
    now[0] += 46
    assert not pair.status(challenge)['attested']
    with pytest.raises(ValueError): pair.attest(challenge, 'wiki-viva-board')
    for _ in range(128): pair.challenge()
    with pytest.raises(ValueError, match='busy'): pair.challenge()


def test_blocking_binding_and_git_head_keep_loop_responsive_and_profile_context(tmp_path):
    import contextvars
    import threading

    profile = contextvars.ContextVar('synthetic_source_profile')
    runtime, binding, calls = service(tmp_path)
    started, release = threading.Event(), threading.Event()
    observed = []

    async def scenario():
        loop_thread = threading.get_ident()
        token = profile.set('research')
        def blocking(stage, result):
            observed.append((stage, threading.get_ident(), profile.get()))
            started.set()
            assert release.wait(2), 'event loop could not unblock the native I/O worker'
            return copy.deepcopy(result)
        runtime.binding = lambda *args: blocking('binding', binding)
        runtime.head_reader = lambda path: blocking('head', 'c' * 40)
        try:
            task = asyncio.create_task(runtime.read_test('source-a', SHA, CONFIG, 'responsive-fixture-0001'))
            try:
                # The controller and its caller must both retain their profile,
                # while unrelated work can run before blocking I/O completes.
                while not started.is_set():
                    await asyncio.sleep(0)
                assert not task.done() and profile.get() == 'research'
                release.set()
                receipt = await task
                assert receipt['status'] == 'read_verified'
                assert [stage for stage, _, _ in observed] == ['binding', 'head', 'head', 'binding']
                assert all(thread != loop_thread and owner == 'research' for _, thread, owner in observed)
                assert len(calls) == 1
            finally:
                release.set()
                if not task.done():
                    task.cancel()
        finally:
            profile.reset(token)
    asyncio.run(scenario())
