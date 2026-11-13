"""Production ingestion bounds the exact request and preserves recoverable blocks."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from jsonschema import validate

from tests.test_folder_policy_core import repo
from tests.test_protected_ingestion import AQAL_REFS, prepared_repo, _nested_integrator_repo
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm.context_pass import canonical_request_text, result_matches_request
from wiki_core.paths import WikiPaths

BASE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def approved(tmp_path):
    (tmp_path / 'memories').mkdir()
    (tmp_path / '.gitignore').write_text('data/derived/\nresult.json\n')
    (tmp_path / 'AGENTS.md').write_text('Obedeça toda a regra; preserve a revisão independente.\n')
    (tmp_path / 'template.rules.md').write_text('Template aplicável: preserve condições, exceções e qualificadores.\n')
    (tmp_path / 'memories/root.md').write_text('---\npage_id: root\npage_type: root_entity\n---\n# Synthetic root\n')
    (tmp_path / 'memories/lens.md').write_text('---\npage_id: lens\npage_type: perspective\n---\n# Required lens\nPreserve exceções e qualificadores.\n')
    config = {'repo_id': 'synthetic-bounded-input', 'owner_label': 'Synthetic coordinator',
        'root_entity': {'page': 'memories/root.md', 'perspective_bundle': {'required': ['lens'], 'optional': []}}}
    (tmp_path / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    policy = {'schema_version': 'wiki.context/v1', 'id': 'root', 'parent': None, 'root': '.',
        'purpose': 'Synthetic reading', 'owner': 'Synthetic coordinator', 'instructions': ['AGENTS.md'],
        'skills': [], 'templates': ['template.rules.md'], 'imports': [], 'exports': [],
        'policy': {'read': ['self'], 'write': [], 'capabilities': [], 'publication': [], 'deny': {}}}
    (tmp_path / 'context.yaml').write_text(yaml.safe_dump(policy))
    source = tmp_path / 'source.md'
    source.write_text('# Fonte sintética\n\n' + ('Observação útil e íntegra sobre a árvore.\n' * 240))
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.test')
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-qm', 'Approved synthetic source and context')
    sha = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'update-ref', 'refs/remotes/origin/main', sha)
    return tmp_path, source, sha, policy


def execute(approved, **limits):
    root, source, sha, _ = approved
    return run(str(source), 'system', root, load_config(root), approved_revision=sha,
               policy_context='root', **limits)


def load_script(name):
    spec = importlib.util.spec_from_file_location('bounded_' + name, BASE / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def folder_approved(tmp_path):
    """A host-bound physical folder fixture, independent of legacy v1 manifests."""
    from wiki_core.coordination_context import CoordinationBinding
    (tmp_path / '.gitignore').write_text('data/derived/\n')
    (tmp_path / 'AGENTS.md').write_text('Preserve synthetic independent review.\n')
    (tmp_path / 'index.md').write_text('# Selected root index\n')
    (tmp_path / 'source.md').write_text('# Fonte sintética\n\n' + ('Observação útil e íntegra.\n' * 240))
    for name, ref in AQAL_REFS.items():
        path = tmp_path / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\npage_id: {name}\npage_type: perspective\n---\n# Lens\n')
    config = {'repo_id': 'synthetic-folder-bounded', 'owner_label': 'Synthetic coordinator',
        'context_access': {'.': {'owner': 'Synthetic coordinator', 'policy': {
            'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}}}
    (tmp_path / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.test')
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-qm', 'Approved synthetic folder context')
    sha = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'update-ref', 'refs/remotes/origin/main', sha)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    return tmp_path, tmp_path / 'source.md', sha, binding


def folder_prepare(folder_approved, **limits):
    from wiki_core.ingest.protected import prepare
    root, _, sha, binding = folder_approved
    return prepare(root, binding, context_id='.', approved_revision=sha,
        entry_folder='.', entry_index='index.md', source_ref='source.md',
        source_context='system', context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS, **limits)


def test_exact_utf8_request_keeps_all_chunks_and_one_required_context(folder_approved):
    from wiki_core.ingest.protected import prepare
    root, _, _, binding = folder_approved
    (root / 'memories').mkdir(exist_ok=True)
    (root / 'memories/root.md').write_text('---\npage_id: root\npage_type: root_entity\n---\n# Root\n')
    (root / 'memories/lens.md').write_text('---\npage_id: lens\npage_type: perspective\n---\nPreserve exceções e qualificadores.\n')
    (root / 'template.rules.md').write_text('Template aplicável: preserve condições.\n')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['root_entity'] = {'page': 'memories/root.md', 'perspective_bundle': {'required': ['lens'], 'optional': []}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    sha = approve_files(root)
    request = prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
        source_ref='source.md', source_context='system', request_max_bytes=256_000,
        context_selection={'root_entity': 'memories/root.md', 'templates': ['template.rules.md']},
        perspective_refs={**AQAL_REFS, 'lens': 'memories/lens.md'})['request']
    raw = canonical_request_text(request).encode('utf-8')
    assert len(raw) == request['byte_accounting']['request_bytes'] <= 256_000
    assert len(raw) > len(raw.decode('utf-8'))
    assert len(request['chunks']) > 1
    assert request['request_limits'] == {'context_max_bytes': 100_000, 'request_max_bytes': 256_000}
    assert all('block_context_package' not in row for row in request['chunks'])
    inputs = request['block_context_package']['inputs']
    assert len([row for row in inputs if row['ref'] == 'AGENTS.md']) == 1
    assert 'Preserve synthetic' in next(row['text'] for row in inputs if row['ref'] == 'AGENTS.md')
    assert 'Preserve exceções' in next(row['text'] for row in inputs if row['ref'] == 'memories/lens.md')
    assert 'Template aplicável' in next(row['text'] for row in inputs if row['ref'] == 'template.rules.md')
    assert request['source_authorization']['use'] == 'interpretation'
    assert request['source_authorization']['classification'] == 'source'


def test_large_source_overflow_writes_nothing_and_cannot_advance_cursor(folder_approved):
    root, source, _, _ = folder_approved
    source.write_text('# Explicit large source\n' + ('Mais conteúdo útil e íntegro.\n' * 2000))
    # Protected source stages have no stream cursor: an overflow must leave no capture.
    with pytest.raises(ValueError):
        folder_prepare(folder_approved, request_max_bytes=16_000)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_mandatory_overflow_and_missing_context_are_recoverable_without_fallback(folder_approved):
    from wiki_core.coordination_context import ProtectedCoordinationError
    from wiki_core.ingest.protected import prepare
    root, _, sha, _ = folder_approved
    with pytest.raises(ValueError):
        folder_prepare(folder_approved, context_max_bytes=32)
    with pytest.raises(ProtectedCoordinationError):
        prepare(root, None, context_id='.', approved_revision=sha, entry_folder='.',
            entry_index='index.md', source_ref='source.md', source_context='system')
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_request_limits_change_cache_identity_and_canonical_cli_records_current_binding(folder_approved):
    root, _, sha, _ = folder_approved
    script = BASE / 'scripts/wiki_coordination.py'
    base = {'entry_folder': '.', 'entry_index': 'index.md', 'source_ref': 'source.md',
            'context_max_bytes': 20_000, 'request_max_bytes': 40_000,
            'context_selection': {'omit_root_entity': True}, 'perspective_refs': AQAL_REFS}
    def call(stage, payload):
        return subprocess.run([sys.executable, str(script), '--root', str(root), '--context-id', '.',
            '--approved-revision', sha, '--source-stage', stage], input=json.dumps(payload),
            capture_output=True, text=True)
    first = call('prepare', {**base, 'source_context': 'system'})
    assert first.returncode == 0
    prepared = json.loads(first.stdout)['result']; request = prepared['request']
    assert request['request_limits'] == {'context_max_bytes': 20_000, 'request_max_bytes': 40_000}
    changed = call('prepare', {**base, 'source_context': 'system', 'request_max_bytes': 40_001})
    assert changed.returncode == 0
    assert json.loads(changed.stdout)['result']['request']['chunks'][0]['cache_key'] != request['chunks'][0]['cache_key']
    row = request['chunks'][0]
    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    recorded = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': request['perspectives_required'],
        'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    assert result_matches_request(recorded, request, row, recording=True)
    record = {**base, 'source_id': prepared['source_id'], 'request_id': prepared['request_id'], 'results': [recorded]}
    wrong = call('record', {**record, 'request_max_bytes': 40_001})
    assert wrong.returncode != 0 and not json.loads(wrong.stdout)['ok']
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    assert not (cache / (row['cache_key'] + '.json')).exists()
    accepted = call('record', record)
    assert accepted.returncode == 0 and json.loads(accepted.stdout)['result']['recorded'] == 1
    assert (cache / (row['cache_key'] + '.json')).exists()


def test_exact_request_boundary_accepts_all_bytes_and_one_byte_less_preserves_prior_request(folder_approved):
    root, _, _, _ = folder_approved
    first = folder_prepare(folder_approved, context_max_bytes=20_000, request_max_bytes=50_000)
    original = first['request']
    limit = len(canonical_request_text(original).encode('utf-8'))
    assert len(str(limit)) == len(str(50_000))
    exact = folder_prepare(folder_approved, context_max_bytes=20_000, request_max_bytes=limit)
    assert len(canonical_request_text(exact['request']).encode('utf-8')) == limit
    protected = root / 'data/derived/wiki/.wiki-viva-protected'
    before = {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        folder_prepare(folder_approved, context_max_bytes=20_000, request_max_bytes=limit - 1)
    assert before == {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}


def test_canonical_cli_reports_revoked_context_without_overwriting_previous_request(folder_approved):
    root, _, sha, _ = folder_approved
    script = BASE / 'scripts/wiki_coordination.py'
    payload = {'entry_folder': '.', 'entry_index': 'index.md', 'source_ref': 'source.md', 'source_context': 'system',
               'context_selection': {'omit_root_entity': True}, 'perspective_refs': AQAL_REFS}
    def call(revision):
        return subprocess.run([sys.executable, str(script), '--root', str(root), '--context-id', '.',
            '--approved-revision', revision, '--source-stage', 'prepare'], input=json.dumps(payload),
            capture_output=True, text=True)
    first = call(sha)
    assert first.returncode == 0
    assert json.loads(first.stdout)['caller_boundary'] == 'trusted_local_operator'
    protected = root / 'data/derived/wiki/.wiki-viva-protected'
    before = {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['source.md']}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    current = approve_files(root)
    denied = call(current)
    report = json.loads(denied.stdout)
    assert denied.returncode != 0 and report['ok'] is False
    assert report['blocker']['owner'] and report['blocker']['interface']
    assert 'source.md' not in json.dumps(report['blocker'])
    assert before == {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}


def approve_files(root):
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'Approve synthetic scope update')
    current = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', current)
    return current


def test_denied_or_external_source_never_reaches_extractor_or_catalog(folder_approved, monkeypatch):
    import wiki_core.ingest.protected as protected
    from wiki_core.repository_reader import RepositoryReader
    root, source, _, binding = folder_approved
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['source.md']}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    sha = approve_files(root)
    def forbidden(*args, **kwargs):
        pytest.fail('denied source reached extraction or catalog')
    monkeypatch.setattr(RepositoryReader, 'catalogue', forbidden)
    original_stat = Path.stat
    def guarded_stat(path, *args, **kwargs):
        if path == source:
            pytest.fail('denied source was statted')
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', guarded_stat)
    for target in ('source.md', 'https://synthetic.invalid/source', '../outside.md'):
        with pytest.raises(ValueError):
            protected.prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
                entry_index='index.md', source_ref=target, source_context='system',
                context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_revocation_during_extraction_blocks_before_any_persistence(folder_approved, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, _, _, _ = folder_approved
    original = protected._capture
    def capture_then_revoke(*args, **kwargs):
        capture = original(*args, **kwargs)
        config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
        config['context_access']['.']['policy']['deny'] = {'read': ['source.md']}
        (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
        approve_files(root)
        return capture
    monkeypatch.setattr(protected, '_capture', capture_then_revoke)
    with pytest.raises(ValueError):
        folder_prepare(folder_approved)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_source_hash_change_and_global_routing_are_not_silently_accepted(folder_approved, monkeypatch):
    import wiki_core.ingest.protected as protected
    from wiki_core.repository_reader import RepositoryReader
    root, source, _, _ = folder_approved
    original = protected._capture
    def extract_then_change(*args, **kwargs):
        capture = original(*args, **kwargs)
        source.write_text(source.read_text() + '\nA concurrent source mutation.\n')
        return capture
    def global_routing(*args, **kwargs):
        pytest.fail('approved task used the global input-stage/source catalog')
    monkeypatch.setattr(protected, '_capture', extract_then_change)
    monkeypatch.setattr(RepositoryReader, 'catalogue', global_routing)
    with pytest.raises(ValueError, match='source changed'):
        folder_prepare(folder_approved)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_imported_source_requires_exact_bilateral_source_classification(prepared_repo, monkeypatch):
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.ingest.protected import prepare
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    for context, key in [('.', 'imports'), ('alpha', 'exports')]:
        for rule in config['context_access'][context][key]:
            if rule['selector'] == 'alpha/source.txt': rule['classification'] = 'context'
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    sha = approve_files(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
        source_ref='alpha/source.txt', source_context='alpha', artifact_context='.',
        context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    original_open = Path.open
    def forbidden_open(path, *args, **kwargs):
        if path == root / 'alpha/source.txt': pytest.fail('source read without exact classification')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', forbidden_open)
    with pytest.raises(ValueError): prepare(root, binding, **args)
    monkeypatch.setattr(Path, 'open', original_open)
    for context, key in [('.', 'imports'), ('alpha', 'exports')]:
        for rule in config['context_access'][context][key]:
            if rule['selector'] == 'alpha/source.txt': rule['classification'] = 'source'
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    args['approved_revision'] = approve_files(root)
    request = prepare(root, binding, **args)['request']
    assert request['source_authorization']['producer'] == 'alpha'
    assert request['source_authorization']['classification'] == 'source'
    assert request['block_context_package']['additional_readers'] == ['.']


def test_approved_routing_delivers_only_applicable_channel_config_and_template_bodies(folder_approved, monkeypatch):
    from wiki_core.ingest.protected import prepare
    from wiki_core.repository_reader import RepositoryReader
    root, _, _, binding = folder_approved
    (root / 'memories/system').mkdir(parents=True)
    (root / 'memories/source.md').write_text('---\npage_id: source\npage_type: source\nconfig_ref: memories/source-config.md\n---\n# Source\n')
    (root / 'memories/source-config.md').write_text('---\npage_id: config\npage_type: source_config\ninput_channel_ref: channel\n---\nRegra específica da fonte.\n')
    (root / 'memories/channel.md').write_text('---\npage_id: channel\npage_type: input_channel\n---\nCanal aplicável.\n')
    (root / 'template.rules.md').write_text('Template aplicável.\n')
    stage = root / 'memories/system/input-stage.md'
    marker = 'UNRELATED_GLOBAL_CATALOG_BODY'
    stage.write_text('---\npage_id: global-stage\npage_type: source_catalog\n---\n' + marker * 8000)
    sha = approve_files(root)
    monkeypatch.setattr(RepositoryReader, 'catalogue', lambda *a, **k: pytest.fail('global catalog opened'))
    selection = {'omit_root_entity': True, 'source_page': 'memories/source.md',
        'source_config': 'memories/source-config.md', 'input_channel': 'memories/channel.md',
        'templates': ['template.rules.md']}
    request = prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
        source_ref='source.md', source_context='system', context_selection=selection, perspective_refs=AQAL_REFS)['request']
    texts = {row['ref']: row['text'] for row in request['block_context_package']['inputs']}
    assert 'Regra específica da fonte' in texts['memories/source-config.md']
    assert 'Canal aplicável' in texts['memories/channel.md']
    assert 'Template aplicável' in texts['template.rules.md']
    assert marker not in json.dumps(request) and stage.relative_to(root).as_posix() not in texts
    assert request['input_stage_status'] == 'explicit_authorized_refs_only'


def test_canonical_cli_root_relative_source_keeps_legacy_mode_explicit(approved, monkeypatch, capsys):
    root, source, _, _ = approved
    module = load_script('wiki_ingest')
    monkeypatch.setattr(sys, 'argv', ['wiki_ingest.py', '--root', str(root), '--source', source.name, '--context', 'system'])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    request = json.loads((root / result['request_path']).read_text())
    assert request['block_context_package']['policy_mode'] == 'legacy_working_tree_compatibility'
    assert request['block_context_package']['policy_enforced'] is False
    assert 'source_authorization' not in request


def test_child_can_explicitly_omit_business_root_without_waiving_lineage_rules(prepared_repo):
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.ingest.protected import prepare
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    (root / 'alpha/hub.md').write_text('---\npage_id: local-root\npage_type: context_hub\n---\n# Local root\n')
    (root / 'memories/root.md').write_text('---\npage_id: global\npage_type: root_entity\n---\n# Global\n')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    rule = {'from_context': 'alpha', 'to_context': '.', 'selector': 'alpha/hub.md',
        'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['alpha']['exports'].append(rule)
    config['context_access']['.']['imports'].append(rule)
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    sha = approve_files(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
        source_ref='alpha/source.txt', source_context='alpha', artifact_context='.', perspective_refs=AQAL_REFS)
    with pytest.raises(ValueError): prepare(root, binding, **args)
    request = prepare(root, binding, **args, context_selection={'omit_root_entity': True})['request']
    packet = request['block_context_package']
    assert request['root_entity'] == {} and packet['coverage']['complete'] is False
    assert any('Business root intentionally omitted' in gap for gap in packet['coverage']['missing'])
    refs = {item['ref']: item['text'] for item in packet['inputs']}
    assert 'AGENTS.md' in refs and 'alpha/AGENTS.override.md' in refs
    assert 'memories/root.md' not in refs
    own_request = prepare(root, binding, **args, context_selection={'root_entity': 'alpha/hub.md'})['request']
    assert own_request['root_entity']['page_id'] == 'local-root'
    assert own_request['root_entity']['entity_type'] == 'context_hub'
    assert own_request['perspectives_required'] == list(AQAL_REFS)  # No global-business additions.
    with pytest.raises(ValueError):
        prepare(root, binding, **args, context_selection={'root_entity': 'memories/root.md'})
    # Canonical CLI carries the explicit omission, with no new grant.
    script = BASE / 'scripts/wiki_coordination.py'
    payload = {'entry_folder': 'alpha', 'entry_index': 'alpha/index.md', 'source_ref': 'alpha/source.txt',
        'source_context': 'alpha', 'context_selection': {'omit_root_entity': True}, 'perspective_refs': AQAL_REFS}
    completed = subprocess.run([sys.executable, str(script), '--root', str(root), '--context-id', 'alpha',
        '--integrator-context', '.', '--approved-revision', sha, '--source-stage', 'prepare'],
        input=json.dumps(payload), capture_output=True, text=True)
    assert completed.returncode == 0 and json.loads(completed.stdout)['result']['request']['root_entity'] == {}


@pytest.mark.parametrize('change', ['hash', 'revocation'])
def test_empty_extraction_revalidates_before_replacing_artifacts_or_pruning_index(folder_approved, monkeypatch, change):
    root, source, _, _ = folder_approved
    folder_prepare(folder_approved)
    protected = root / 'data/derived/wiki/.wiki-viva-protected'
    before = {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}
    source.write_text('')
    original_open = Path.open
    class AfterRead:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def read(self, *args):
            data = self.stream.read(*args)
            if change == 'hash':
                source.write_text('A changed source after an empty capture.\n')
            else:
                config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
                config['context_access']['.']['policy']['deny'] = {'read': ['source.md']}
                (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
                approve_files(root)
            return data
    def guarded_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == source and args and args[0] == 'rb':
            return AfterRead(stream)
        return stream
    monkeypatch.setattr(Path, 'open', guarded_open)
    with pytest.raises(ValueError):
        folder_prepare(folder_approved)
    assert before == {p.relative_to(protected): p.read_bytes() for p in protected.rglob('*') if p.is_file()}


def test_nonempty_source_keeps_one_post_extraction_revalidation_fence(folder_approved, monkeypatch):
    import wiki_core.ingest.protected as protected
    original = protected._hash
    calls = []
    def observe(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(protected, '_hash', observe)
    result = folder_prepare(folder_approved)
    assert result['request_id'] and len(calls) >= 2
    # Protected retention has more fences than the retired pipeline: never fewer.


def test_approved_recording_reads_only_its_exact_request_and_capture(folder_approved, monkeypatch):
    from wiki_core.ingest.protected import record
    root, _, sha, binding = folder_approved
    first = folder_prepare(folder_approved)
    request = first['request']; row = request['chunks'][0]
    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': request['perspectives_required'],
        'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    events = root / 'data/derived/wiki/.wiki-viva-protected/extraction-events'
    foreign = events / 'unrelated-source-llm-context-request.json'
    foreign.write_text('Unrelated malformed request; never inspect it for this task.')
    original_open, original_glob = Path.open, Path.glob
    def guarded_open(path, *args, **kwargs):
        if path == foreign:
            pytest.fail('approved record opened another source request')
        return original_open(path, *args, **kwargs)
    def guarded_glob(path, *args, **kwargs):
        if path == events:
            pytest.fail('approved record enumerated global requests')
        return original_glob(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(Path, 'glob', guarded_glob)
    legacy = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(legacy, 'resolve_source_manifest', lambda *a, **k: pytest.fail('legacy discovery'))
    recorded = record(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
        source_ref='source.md', source_id=first['source_id'], request_id=first['request_id'], results=[result],
        context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    assert recorded['recorded'] == 1


def test_approved_missing_exact_capture_blocks_instead_of_legacy_discovery(folder_approved, monkeypatch):
    from wiki_core.ingest.protected import record
    root, _, sha, binding = folder_approved
    legacy = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(legacy, 'resolve_source_manifest', lambda *a, **k: pytest.fail('legacy discovery'))
    with pytest.raises((ValueError, OSError)):
        record(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
            entry_index='index.md', source_ref='source.md', source_id='missing',
            request_id='0' * 64, results=[{}], context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()
