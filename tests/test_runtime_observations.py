"""Generic operator observations remain pure and distinguish installed inputs."""
import hashlib
import subprocess

from tests.test_web_server import _repo, _Server
from wiki_core.config import load_config
from wiki_core.web import server as web


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def commit(root, message):
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.test')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', message)


def forbidden(*args, **kwargs):
    raise AssertionError('read invoked an effect or external adapter')


def test_observation_is_read_only_without_global_snapshot_or_agent_probe(tmp_path, monkeypatch):
    config = _repo(tmp_path)
    srv = _Server(tmp_path, config)
    try:
        assert srv.server.jobs._worker is None
        monkeypatch.setattr(srv.server, 'snapshot_payloads', forbidden)
        for name in ('probe_codex_for', 'probe_claude_for', 'build_admin_plan', 'execute_admin_plan'):
            monkeypatch.setattr(web, name, forbidden)
        before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
        status, result = srv.get('/api/runtime/observations')
        assert status == 200
        assert set(result) == {'ok', 'schema_version', 'observed_at', 'operator'}
        assert result['schema_version'] == 'wiki_runtime_observations.v1'
        assert result['operator']['frontend']['status'] == 'not_served'
        assert before == {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    finally:
        srv.close()


def test_versions_separate_code_boot_content_and_served_frontend(tmp_path, monkeypatch, tmp_path_factory):
    root = tmp_path
    config = _repo(root)
    commit(root, 'Content at startup')
    code = tmp_path_factory.mktemp('synthetic-operator-code')
    (code / 'wiki_core').mkdir()
    module = code / 'wiki_core/operator.py'
    module.write_text('version = 1\n')
    git(code, 'init', '-b', 'main')
    commit(code, 'Code at startup')
    monkeypatch.setattr(web, '_operator_code_root', lambda: code)
    srv = _Server(root, config)
    try:
        first = srv.get('/api/runtime/observations')[1]['operator']
        assert first['boot_source_commit'] == first['current_source_commit'] == git(code, 'rev-parse', 'HEAD')
        assert first['content_source_commit'] == git(root, 'rev-parse', 'HEAD')
        assert first['restart_required'] is False
        (root / 'memories/index.md').write_text('Synthetic changed content\n')
        commit(root, 'Content update')
        (code / 'README.md').write_text('Synthetic documentation only\n')
        commit(code, 'Documentation update')
        second = srv.get('/api/runtime/observations')[1]['operator']
        assert second['content_source_commit'] != first['content_source_commit']
        assert second['current_source_commit'] != first['current_source_commit']
        assert second['boot_source_commit'] == first['boot_source_commit']
        assert second['restart_required'] is False
        frontend = root / 'frontend'
        frontend.mkdir()
        (frontend / 'index.html').write_text('<html>Synthetic entry</html>')
        srv.server.frontend_dir = frontend
        module.write_text('version = 2\n')
        third = srv.get('/api/runtime/observations')[1]['operator']
        assert third['restart_required'] is True
        assert third['boot_code_sha256'] != third['current_code_sha256']
        assert third['frontend'] == {'status': 'observed', 'source_commit': None,
            'entry_sha256': hashlib.sha256((frontend / 'index.html').read_bytes()).hexdigest()}
        module.write_text('version = 1\n')
        config_file = root / 'wiki.config.yaml'
        config_file.write_text(config_file.read_text() + 'owner_label: Changed configuration\n')
        assert srv.get('/api/runtime/observations')[1]['operator']['restart_required'] is True
    finally:
        srv.close()


def test_optional_execution_is_absent_and_http_effects_require_current_authority(tmp_path, monkeypatch):
    config = _repo(tmp_path)
    assert not config.codex_enabled and not config.claude_enabled
    srv = _Server(tmp_path, config)
    try:
        status, catalog = srv.get('/api/admin/commands')
        assert status == 200
        assert 'sources.review_pending' not in {entry['id'] for entry in catalog['commands']}
        monkeypatch.setattr(web, 'run_gate', forbidden)
        monkeypatch.setattr(web, 'compose_and_save', forbidden)
        monkeypatch.setattr(web, 'probe_codex_for', forbidden)
        for route, payload in [('/api/gates/run', {'gate_id': 'audit'}),
                               ('/api/briefs', {'spec': {}}),
                               ('/api/codex/jobs', {'brief_id': 'synthetic', 'brief_sha': 'synthetic'})]:
            status, result = srv.post(route, payload)
            assert status == 403 and result['ok'] is False
        assert srv.server.jobs._worker is None
    finally:
        srv.close()
