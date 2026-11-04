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


def test_exact_utf8_request_keeps_all_chunks_and_one_required_context(approved):
    root, _, _, _ = approved
    result = execute(approved)
    raw = (root / result.request_path).read_bytes()
    request = json.loads(raw)
    assert raw == canonical_request_text(request).encode('utf-8')
    assert len(raw) == request['byte_accounting']['request_bytes'] <= 256_000
    assert len(raw) > len(raw.decode('utf-8'))
    assert len(request['chunks']) == result.chunk_count > 1
    assert request['request_limits'] == {'context_max_bytes': 100_000, 'request_max_bytes': 256_000}
    assert all('block_context_package' not in row for row in request['chunks'])
    inputs = request['block_context_package']['inputs']
    assert len([row for row in inputs if row['ref'] == 'AGENTS.md']) == 1
    assert 'Obedeça toda a regra' in next(row['text'] for row in inputs if row['ref'] == 'AGENTS.md')
    assert 'Preserve exceções' in next(row['text'] for row in inputs if row['ref'] == 'memories/lens.md')
    assert 'Template aplicável' in next(row['text'] for row in inputs if row['ref'] == 'template.rules.md')
    assert request['source_authorization']['use'] == 'interpretation'
    assert request['source_authorization']['classification'] == 'source'


def test_large_source_overflow_writes_nothing_and_cannot_advance_cursor(approved):
    root, source, _, _ = approved
    source.write_text('# Explicit large source\n' + ('Mais conteúdo útil e íntegro.\n' * 12_000))
    result = execute(approved, request_max_bytes=16_000, stream_id='synthetic-stream')
    assert result.blocked and not result.written and result.request_path is None
    assert result.context_error_code == 'request_budget_exceeded'
    assert result.chunk_count > 1 and result.pending_llm_calls == result.chunk_count
    assert result.score_event_id is None and not result.stream_cursor_written
    assert not WikiPaths(root, load_config(root)).derived_root.exists()
    schema = json.loads((BASE / 'docs/references/schemas/wiki-task-result-v1.schema.json').read_text())
    validate(result.blockers[0], schema['properties']['blockers']['items'])
    assert result.blockers[0]['interface'] and result.blockers[0]['required_action']
    assert 'Mais conteúdo' not in json.dumps(result.blockers)


def test_mandatory_overflow_and_missing_context_are_recoverable_without_fallback(approved):
    root, _, _, _ = approved
    result = execute(approved, context_max_bytes=32)
    assert result.blocked and result.context_error_code == 'context_budget_exceeded'
    assert not result.written and result.blockers
    missing = run(str(approved[1]), 'system', root, load_config(root), approved_revision=approved[2])
    assert missing.blocked and missing.context_error_code == 'approved_source_context_required'
    assert not missing.written and not WikiPaths(root, load_config(root)).derived_root.exists()


def test_request_limits_change_cache_identity_and_canonical_cli_records_current_binding(approved, monkeypatch, capsys):
    root, source, sha, _ = approved
    ingest = load_script('wiki_ingest')
    limits = ['--context-max-bytes', '20_000', '--request-max-bytes', '40_000']
    flags = ['--approved-revision', sha, '--policy-context', 'root', *limits]
    monkeypatch.setattr(sys, 'argv', ['wiki_ingest.py', '--root', str(root), '--source', str(source), '--context', 'system', *flags])
    assert ingest.main() == 0
    result = json.loads(capsys.readouterr().out)
    request_path = root / result['request_path']
    request = json.loads(request_path.read_bytes())
    assert request['request_limits'] == {'context_max_bytes': 20_000, 'request_max_bytes': 40_000}
    changed = execute(approved, context_max_bytes=20_000, request_max_bytes=40_001)
    assert json.loads((root / changed.request_path).read_text())['chunks'][0]['cache_key'] != request['chunks'][0]['cache_key']
    # Re-emit the original explicit budgets through the canonical caller.
    assert ingest.main() == 0
    capsys.readouterr()
    request = json.loads(request_path.read_text())
    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    recorded = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': request['perspectives_required'],
        'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    assert result_matches_request(recorded, request, row, recording=True)
    payload = root / 'result.json'; payload.write_text(json.dumps(recorded))
    llm = load_script('wiki_llm_context_pass'); monkeypatch.setattr(llm, 'ROOT', root)
    argv = ['wiki_llm_context_pass.py', '--source', str(source), '--context', 'system', '--record-result', str(payload)]
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'working-tree', '--context', 'system',
        '--record-result', str(payload), *limits])
    assert llm.main() == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'approved_context_revalidation_required'
    assert not (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    monkeypatch.setattr(sys, 'argv', [*argv, *flags])
    assert llm.main() == 0
    capsys.readouterr()
    assert (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    monkeypatch.setattr(sys, 'argv', [*argv, '--mode', 'v1', '--approved-revision', sha, '--policy-context', 'root', '--request-max-bytes', '1_000'])
    assert llm.main() == 2
    block = json.loads(capsys.readouterr().out)
    assert block['blocked'] and block['error_code'] == 'request_budget_exceeded'


def test_exact_request_boundary_accepts_all_bytes_and_one_byte_less_preserves_prior_request(approved):
    root = approved[0]
    first = execute(approved, context_max_bytes=20_000, request_max_bytes=50_000)
    old = (root / first.request_path).read_bytes()
    limit = len(old)
    assert len(str(limit)) == len(str(50_000))
    fitted = execute(approved, context_max_bytes=20_000, request_max_bytes=limit)
    fitted_path = root / fitted.request_path
    exact = fitted_path.read_bytes()
    assert len(exact) == limit
    blocked = execute(approved, context_max_bytes=20_000, request_max_bytes=limit - 1)
    assert blocked.blocked and blocked.context_error_code == 'request_budget_exceeded'
    assert not blocked.written and fitted_path.read_bytes() == exact


def test_canonical_cli_reports_revoked_context_without_overwriting_previous_request(approved, monkeypatch, capsys):
    root, source, sha, policy = approved
    module = load_script('wiki_ingest')
    argv = ['wiki_ingest.py', '--root', str(root), '--source', str(source), '--context', 'system', '--policy-context', 'root']
    monkeypatch.setattr(sys, 'argv', [*argv, '--approved-revision', sha])
    assert module.main() == 0
    first = json.loads(capsys.readouterr().out)
    path = root / first['request_path']; retained = path.read_bytes()
    policy['policy']['deny'] = {'read': ['memories/lens.md']}
    (root / 'context.yaml').write_text(yaml.safe_dump(policy))
    git(root, 'add', 'context.yaml'); git(root, 'commit', '-qm', 'Approve narrower context')
    current = git(root, 'rev-parse', 'HEAD'); git(root, 'update-ref', 'refs/remotes/origin/main', current)
    monkeypatch.setattr(sys, 'argv', [*argv, '--approved-revision', current])
    assert module.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['blocked'] and not report['written'] and report['request_path'] is None
    assert report['score_event_id'] is None and not report['stream_cursor_written']
    assert report['blockers'][0]['owner'] == 'Synthetic coordinator'
    assert 'memories/lens.md' not in json.dumps(report['blockers'])
    assert path.read_bytes() == retained


def approve_files(root):
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'Approve synthetic scope update')
    current = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', current)
    return current


def test_denied_or_external_source_never_reaches_extractor_or_catalog(approved, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    from wiki_core.repository_reader import RepositoryReader
    root, source, _, policy = approved
    policy['policy']['deny'] = {'read': ['source.md']}
    (root / 'context.yaml').write_text(yaml.safe_dump(policy))
    current = approve_files(root)
    def forbidden(*args, **kwargs):
        pytest.fail('denied source reached extraction or catalog')
    monkeypatch.setattr(pipeline, 'extract_source', forbidden)
    monkeypatch.setattr(pipeline, 'build_manifest', forbidden)
    monkeypatch.setattr(RepositoryReader, 'catalogue', forbidden)
    original_stat = Path.stat
    def guarded_stat(path, *args, **kwargs):
        if path == source:
            pytest.fail('denied source was statted')
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', guarded_stat)
    for target, code in [(str(source), 'source_read_denied'),
                         ('https://synthetic.invalid/source', 'source_staging_required'),
                         (str(root.parent / 'outside.md'), 'source_staging_required')]:
        result = run(target, 'system', root, load_config(root), approved_revision=current,
                     policy_context='root', stream_id='same-task')
        assert result.blocked and result.context_error_code == code
        assert result.chunk_count == 0 and not result.written and result.score_event_id is None
        assert not result.stream_cursor_written and result.request_path is None
        assert not WikiPaths(root, load_config(root)).derived_root.exists()
        assert target not in json.dumps(result.blockers)


def test_revocation_during_extraction_blocks_before_any_persistence(approved, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    root, source, sha, policy = approved
    original = pipeline.extract_source
    def extract_then_revoke(*args, **kwargs):
        extracted = original(*args, **kwargs)
        policy['policy']['deny'] = {'read': ['source.md']}
        (root / 'context.yaml').write_text(yaml.safe_dump(policy))
        approve_files(root)
        return extracted
    monkeypatch.setattr(pipeline, 'extract_source', extract_then_revoke)
    result = run(str(source), 'system', root, load_config(root), approved_revision=sha,
                 policy_context='root', stream_id='same-task')
    assert result.blocked and not result.written and result.score_event_id is None
    assert not result.stream_cursor_written and result.request_path is None
    assert not WikiPaths(root, load_config(root)).derived_root.exists()


def test_source_hash_change_and_global_routing_are_not_silently_accepted(approved, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    root, source, sha, _ = approved
    original = pipeline.extract_source
    def extract_then_change(*args, **kwargs):
        extracted = original(*args, **kwargs)
        source.write_text(source.read_text() + '\nA concurrent source mutation.\n')
        return extracted
    def global_routing(*args, **kwargs):
        pytest.fail('approved task used the global input-stage/source catalog')
    monkeypatch.setattr(pipeline, 'extract_source', extract_then_change)
    monkeypatch.setattr(pipeline, 'input_context_for_source', global_routing)
    monkeypatch.setattr(pipeline, 'find_source_config', global_routing)
    result = run(str(source), 'system', root, load_config(root), approved_revision=sha, policy_context='root')
    assert result.blocked and result.context_error_code == 'source_changed'
    assert not result.written and not WikiPaths(root, load_config(root)).derived_root.exists()


def test_imported_source_requires_exact_bilateral_source_classification(approved):
    root, _, _, policy = approved
    area = root / 'shared'; area.mkdir()
    source = area / 'source.md'; source.write_text('# Imported synthetic source\nIndependent evidence.\n')
    child = {'schema_version': 'wiki.context/v1', 'id': 'producer', 'parent': 'root', 'root': 'shared',
        'purpose': 'Synthetic producer', 'owner': 'Producer', 'instructions': [], 'skills': [], 'templates': [],
        'imports': [], 'exports': [], 'policy': {'read': ['self']}}
    rule = {'from_context': 'producer', 'to_context': 'root', 'selector': 'shared/source.md',
        'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    policy['imports'] = [dict(rule)]; child['exports'] = [dict(rule)]
    (root / 'context.yaml').write_text(yaml.safe_dump(policy)); (area / 'context.yaml').write_text(yaml.safe_dump(child))
    sha = approve_files(root)
    denied = run(str(source), 'system', root, load_config(root), approved_revision=sha, policy_context='root')
    assert denied.blocked and denied.context_error_code == 'source_read_denied'
    policy['imports'][0]['classification'] = child['exports'][0]['classification'] = 'source'
    (root / 'context.yaml').write_text(yaml.safe_dump(policy)); (area / 'context.yaml').write_text(yaml.safe_dump(child))
    sha = approve_files(root)
    admitted = run(str(source), 'system', root, load_config(root), approved_revision=sha, policy_context='root')
    assert not admitted.blocked and admitted.request_path
    request = json.loads((root / admitted.request_path).read_text())
    assert request['source_authorization']['producer'] == 'producer'
    assert request['source_authorization']['classification'] == 'source'


def test_approved_routing_delivers_only_applicable_channel_config_and_template_bodies(approved, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    root, source, _, _ = approved
    source.write_text('---\npage_id: synthetic-source\npage_type: source\nconfig_ref: memories/source-config.md\n---\n' + source.read_text())
    (root / 'memories/source-config.md').write_text('---\npage_id: source-config\npage_type: source_config\ninput_channel_ref: channel\n---\nRegra específica da fonte: mantenha os qualificadores.\n')
    (root / 'memories/channel.md').write_text('---\npage_id: channel\npage_type: input_channel\ncontext: system\n---\nCanal aplicável: leia o recorte com evidência.\n')
    stage = root / 'memories/system/input-stage.md'; stage.parent.mkdir()
    marker = 'UNRELATED_GLOBAL_CATALOG_BODY'
    stage.write_text('---\npage_id: global-stage\npage_type: source_catalog\n---\n' + marker * 8000)
    sha = approve_files(root)
    def forbidden(*args, **kwargs):
        pytest.fail('approved ingestion opened global routing')
    monkeypatch.setattr(pipeline, 'input_context_for_source', forbidden)
    monkeypatch.setattr(pipeline, 'find_source_config', forbidden)
    result = run(str(source), 'system', root, load_config(root), approved_revision=sha, policy_context='root')
    assert not result.blocked
    request_text = (root / result.request_path).read_text()
    request = json.loads(request_text)
    texts = {row['ref']: row['text'] for row in request['block_context_package']['inputs']}
    assert 'Regra específica da fonte' in texts['memories/source-config.md']
    assert 'Canal aplicável' in texts['memories/channel.md']
    assert 'Template aplicável' in texts['template.rules.md']
    assert marker not in request_text and stage.relative_to(root).as_posix() not in texts
    assert request['input_stage_status'] == 'explicit_authorized_refs_only'


def test_canonical_cli_root_relative_source_keeps_legacy_mode_explicit(approved, monkeypatch, capsys):
    root, source, _, _ = approved
    module = load_script('wiki_ingest')
    monkeypatch.setattr(sys, 'argv', ['wiki_ingest.py', '--mode', 'working-tree', '--root', str(root), '--source', source.name, '--context', 'system'])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    request = json.loads((root / result['request_path']).read_text())
    assert request['block_context_package']['policy_mode'] == 'legacy_working_tree_compatibility'
    assert request['block_context_package']['policy_enforced'] is False
    assert 'source_authorization' not in request


def test_child_can_explicitly_omit_business_root_without_waiving_lineage_rules(approved, monkeypatch, capsys):
    root, _, _, _ = approved
    area = root / 'area'; area.mkdir()
    local = area / 'source.md'; local.write_text('# Local source\nOnly authorized local evidence.\n')
    (area / 'hub.md').write_text('---\npage_id: local-root\npage_type: context_hub\n---\n# Local business root\nPurpose of this local task.\n')
    (area / 'rules.md').write_text('Child rule: preserve the exact scope.\n')
    child = {'schema_version': 'wiki.context/v1', 'id': 'child', 'parent': 'root', 'root': 'area',
        'purpose': 'Independent local reading', 'owner': 'Child owner', 'instructions': ['area/rules.md'],
        'skills': [], 'templates': [], 'imports': [], 'exports': [], 'policy': {'read': ['self']}}
    (area / 'context.yaml').write_text(yaml.safe_dump(child)); sha = approve_files(root)
    config = load_config(root)
    default = run(str(local), 'system', root, config, approved_revision=sha, policy_context='child')
    assert default.blocked and default.context_error_code == 'context_read_denied'
    omitted = run(str(local), 'system', root, config, approved_revision=sha, policy_context='child', omit_root_entity=True)
    assert not omitted.blocked
    request = json.loads((root / omitted.request_path).read_text()); packet = request['block_context_package']
    assert request['root_entity'] == {} and packet['coverage']['complete'] is False
    assert any('Business root intentionally omitted' in gap for gap in packet['coverage']['missing'])
    refs = {item['ref']: item['text'] for item in packet['inputs']}
    assert 'Obedeça toda a regra' in refs['AGENTS.md']
    assert 'Template aplicável' in refs['template.rules.md']
    assert 'Child rule' in refs['area/rules.md']
    assert 'memories/root.md' not in refs
    own_root = run(str(local), 'system', root, config, approved_revision=sha, policy_context='child', root_entity_ref='area/hub.md')
    own_request = json.loads((root / own_root.request_path).read_text())
    assert not own_root.blocked and own_request['root_entity']['page_id'] == 'local-root'
    assert own_request['root_entity']['entity_type'] == 'context_hub'
    assert own_request['perspectives_required'] == []  # No implicit global-business lenses.
    external = run(str(local), 'system', root, config, approved_revision=sha, policy_context='child', root_entity_ref='memories/root.md')
    assert external.blocked and external.context_error_code == 'context_read_denied'
    # Canonical CLI carries the explicit omission, with no new grant.
    cli = load_script('wiki_ingest')
    monkeypatch.setattr(sys, 'argv', ['wiki_ingest.py', '--mode', 'v1', '--root', str(root), '--source', 'area/source.md',
        '--context', 'system', '--approved-revision', sha, '--policy-context', 'child', '--omit-root-entity'])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['blocked'] is False


@pytest.mark.parametrize('change', ['hash', 'revocation'])
def test_empty_extraction_revalidates_before_replacing_artifacts_or_pruning_index(approved, monkeypatch, change):
    import wiki_core.ingest.pipeline as pipeline
    from wiki_core.extractors import ExtractedDocument
    root, source, sha, policy = approved
    first = execute(approved, stream_id='same-stream')
    assert not first.blocked and first.chunks_indexed > 0
    derived = WikiPaths(root, load_config(root)).derived_root
    before = {path.relative_to(derived).as_posix(): path.read_bytes() for path in derived.rglob('*') if path.is_file()}
    def empty_then_change(*args, **kwargs):
        if change == 'hash':
            source.write_text('A changed source after an empty extraction.\n')
        else:
            policy['policy']['deny'] = {'read': ['source.md']}
            (root / 'context.yaml').write_text(yaml.safe_dump(policy)); approve_files(root)
        return ExtractedDocument(str(source), 'markdown', '', [], [])
    def forbidden(*args, **kwargs):
        pytest.fail('blocked empty extraction persisted or modified the index')
    monkeypatch.setattr(pipeline, 'extract_source', empty_then_change)
    for name in ('write_manifest', 'write_source_artifact', 'index_source', 'record_event'):
        monkeypatch.setattr(pipeline, name, forbidden)
    result = run(str(source), 'system', root, load_config(root), approved_revision=sha,
                 policy_context='root', stream_id='same-stream')
    assert result.blocked and not result.written and result.chunk_count == 0
    assert result.request_path is None and result.score_event_id is None and not result.stream_cursor_written
    assert result.context_error_code == ('source_changed' if change == 'hash' else 'context_preparation_unavailable')
    assert before == {path.relative_to(derived).as_posix(): path.read_bytes() for path in derived.rglob('*') if path.is_file()}


def test_nonempty_source_keeps_one_post_extraction_revalidation_fence(approved, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    original = pipeline.revalidate_ingestion_source
    calls = []
    def observe(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'revalidate_ingestion_source', observe)
    result = execute(approved)
    assert not result.blocked and len(calls) == 2  # Before extraction and before persistence.


def test_approved_recording_reads_only_its_exact_request_and_capture(approved, monkeypatch, capsys):
    root, source, sha, _ = approved
    first = execute(approved)
    request = json.loads((root / first.request_path).read_text())
    row = request['chunks'][0]
    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    recorded = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': request['perspectives_required'],
        'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    payload = root / 'result.json'; payload.write_text(json.dumps(recorded))
    paths = WikiPaths(root, load_config(root))
    foreign = paths.extraction_events / 'unrelated-source-llm-context-request.json'
    foreign.write_text('Unrelated malformed request; never inspect it for this task.')
    original_read = Path.read_text
    original_glob = Path.glob
    def read(path, *args, **kwargs):
        if path == foreign:
            pytest.fail('approved record opened another source request')
        return original_read(path, *args, **kwargs)
    def glob(path, *args, **kwargs):
        if path == paths.extraction_events:
            pytest.fail('approved record enumerated global requests')
        return original_glob(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    monkeypatch.setattr(Path, 'glob', glob)
    module = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(module, 'resolve_source_manifest', lambda *a, **k: pytest.fail('approved record used compatibility capture discovery'))
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'v1', '--root', str(root), '--source', str(source),
        '--context', 'system', '--approved-revision', sha, '--policy-context', 'root', '--record-result', str(payload)])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1


def test_approved_missing_exact_capture_blocks_instead_of_legacy_discovery(approved, monkeypatch, capsys):
    root, source, sha, _ = approved
    module = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(module, 'resolve_source_manifest', lambda *a, **k: pytest.fail('approved source attempted legacy discovery'))
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'v1', '--root', str(root), '--source', str(source),
        '--context', 'system', '--approved-revision', sha, '--policy-context', 'root', '--check'])
    assert module.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['blocked'] and report['error_code'] == 'source_capture_required'
    assert report['blockers'][0]['interface'] and report['blockers'][0]['owner']
    assert not WikiPaths(root, load_config(root)).derived_root.exists()
