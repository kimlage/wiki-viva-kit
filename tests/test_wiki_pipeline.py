"""Integration test for the ingestion orchestrator (anti-island regression).

Runs the full chain (manifest -> text/chunks -> index -> PII pre-scan ->
LLM context packet -> score-event) over a fixture source in tmp_path and
asserts each artifact is produced and coherent. No network; nothing is written
outside tmp_path. Ensures the modules (score/detectors/llm/index) stop being
islands triggered only by a manual CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, WikiConfig
from wiki_core.index.sqlite import search
from wiki_core.ingest import run

LOREM = ("living wiki pipeline integration with enough text to span several chunks " * 40).strip()
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pipeline_produces_all_artifacts(tmp_path: Path) -> None:
    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config)
    derived = tmp_path / "data/derived/wiki"

    # 1. manifest
    assert result.manifest_path and (tmp_path / result.manifest_path).exists()
    assert (derived / "source-manifests" / f"{result.source_id}.json").exists()

    # 2. text + chunks
    assert result.chunk_count > 0
    assert (derived / "source-text" / f"{result.source_id}.json").exists()
    chunks_file = derived / "chunks" / f"{result.source_id}.json"
    assert chunks_file.exists()
    chunks_data = json.loads(chunks_file.read_text(encoding="utf-8"))
    assert chunks_data["schema_version"] == "wiki_chunks.v1"
    assert len(chunks_data["chunks"]) == result.chunk_count

    # 3. index
    assert result.chunks_indexed == result.chunk_count
    assert (derived / "indexes" / "wiki.sqlite").exists()

    # 4. LLM packet emitted and pending (empty cache) -> the auditor gate now has something to watch
    assert result.request_path and (tmp_path / result.request_path).exists()
    request = json.loads(
        (derived / "extraction-events" / f"{result.source_id}-llm-context-request.json").read_text(encoding="utf-8")
    )
    assert request["pending_llm_calls"] == result.chunk_count
    assert request["prompt_version"] == DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION
    assert result.llm_context_status == "pending"

    # 5. score-event append-only
    assert result.score_event_id
    events = (derived / "score-events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["event_type"] == "ingestar_fonte_valida"
    assert event["context"] == "system"

    # 6. proposal starts in the state machine
    assert result.gate_state == "created"


def test_pipeline_blocks_secret_in_source(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "with_secret.md"
    _write(src, "service config\n\naws_key = " + AWS_KEY + "\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config)
    assert result.secret_findings, "the pre-screening should detect the secret in the source"
    # the raw secret never appears in the redacted excerpt
    assert all(AWS_KEY not in finding["excerpt"] for finding in result.secret_findings)

    # Scan-first: a secret BLOCKS before persisting — NOTHING goes to data/derived.
    assert result.blocked is True
    assert result.written is False
    assert result.gate_state == "blocked"
    assert result.llm_context_status == "blocked"
    assert result.manifest_path is None
    assert result.chunks_path is None
    assert result.request_path is None
    assert result.score_event_id is None
    derived = tmp_path / "data/derived/wiki"
    leaked = [
        str(p)
        for p in derived.rglob("*")
        if p.is_file() and AWS_KEY in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not leaked, f"the secret leaked into derived artifacts: {leaked}"
    sqlite = derived / "indexes" / "wiki.sqlite"
    assert not sqlite.exists() or AWS_KEY.encode() not in sqlite.read_bytes()


def test_pipeline_reingest_prunes_stale_version_from_index(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "source.md"
    _write(src, "# Source\n\nstaleword only in v1\n\n" + LOREM + "\n")
    first = run(str(src), "system", tmp_path, config)

    # Edit the source and re-ingest: new digest, hence a new source_id.
    _write(src, "# Source\n\nfreshword only in v2\n\n" + LOREM + "\n")
    second = run(str(src), "system", tmp_path, config)
    assert first.source_id != second.source_id

    db = tmp_path / "data/derived/wiki/indexes/wiki.sqlite"
    # The old version no longer answers searches; only the new one does.
    assert search(db, "staleword") == []
    fresh_hits = search(db, "freshword")
    assert fresh_hits and {h["source_id"] for h in fresh_hits} == {second.source_id}
    assert {h["source_id"] for h in search(db, "pipeline")} == {second.source_id}


def test_pipeline_dry_run_writes_nothing(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config, write=False)
    assert result.chunk_count > 0  # computed in memory
    assert result.manifest_path is None  # but not written
    assert result.chunks_path is None
    assert result.score_event_id is None
    assert not (tmp_path / "data/derived/wiki/chunks").exists()


def test_stream_cursor_written_only_after_durable_writes(tmp_path: Path) -> None:
    """F8: with a --stream id, the cursor lands ONLY after every durable write,
    and a dry-run writes NO cursor (nothing durable happened)."""
    from wiki_core.paths import WikiPaths
    from wiki_core.source_state import read_state, stream_cursor

    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")
    paths = WikiPaths(tmp_path, config)

    # Dry run: nothing durable => no cursor.
    dry = run(str(src), "system", tmp_path, config, write=False, stream_id="#financeiro", ts="2026-07-03T00:00:00Z")
    assert dry.stream_cursor_written is False
    assert read_state(paths.source_state, dry.source_id)["streams"] == {}

    # Real run: cursor written after the event, keyed by the stream id.
    result = run(str(src), "system", tmp_path, config, stream_id="#financeiro", ts="2026-07-03T00:00:00Z")
    assert result.stream_cursor_written is True
    cursor = stream_cursor(read_state(paths.source_state, result.source_id), "#financeiro")
    assert cursor["updated_at"] == "2026-07-03"
    assert cursor["last_unit"]  # a real chunk id


def test_stream_cursor_updated_at_is_a_real_date_without_an_explicit_ts(tmp_path: Path) -> None:
    """F8 freshness: the standard CLI passes no ts. The cursor's updated_at must
    still be a parseable ISO date (from the manifest's captured_at), never empty —
    otherwise a just-synced stream reads as 'never'."""
    import datetime as dt

    from wiki_core.paths import WikiPaths
    from wiki_core.source_state import read_state, stream_cursor

    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")
    paths = WikiPaths(tmp_path, config)

    result = run(str(src), "system", tmp_path, config, stream_id="#financeiro")  # ts=None
    assert result.stream_cursor_written is True
    cursor = stream_cursor(read_state(paths.source_state, result.source_id), "#financeiro")
    # A real ISO date that the freshness read can parse (never "").
    assert cursor["updated_at"]
    dt.date.fromisoformat(cursor["updated_at"])  # raises if not a date


def test_no_stream_id_leaves_cursor_state_untouched(tmp_path: Path) -> None:
    from wiki_core.paths import WikiPaths

    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")
    result = run(str(src), "system", tmp_path, config)
    assert result.stream_cursor_written is False
    assert not (WikiPaths(tmp_path, config).source_state).exists()


def test_pipeline_delivers_actual_policy_and_perspective_bodies_and_invalidates_same_id(tmp_path):
    config = WikiConfig(root_entity={"page": "memories/root.md", "perspective_bundle": {"required": ["perspective-synthetic"], "optional": []}})
    config.audit['core_pages'] = ['memories/policy.md']
    _write(tmp_path / 'AGENTS.md', 'Preserve synthetic independent review.\n')
    _write(tmp_path / 'memories/root.md', '---\npage_id: root\npage_type: root_entity\nblocks: [{id: wiki.block.quadrants.v1}]\n---\n# Synthetic root\n')
    _write(tmp_path / 'wiki.templates.yaml', 'schema_version: wiki_templates.v1\nblocks:\n  wiki.block.quadrants.v1:\n    kind: interpretation\n')
    _write(tmp_path / 'memories/policy.md', '---\npage_id: policy\npage_type: operational_rule\n---\n# Synthetic policy\nReview before promotion.\n')
    perspective = tmp_path / 'memories/perspective.md'
    _write(perspective, '---\npage_id: perspective-synthetic\npage_type: perspective\n---\n# Synthetic perspective\nInspect exceptions in the original evidence.\n')
    src = tmp_path / 'source.md'
    _write(src, '# Synthetic source\n' + LOREM)
    first = run(str(src), 'system', tmp_path, config)
    before = json.loads((tmp_path / first.request_path).read_text())
    package = before['block_context_package']
    assert package['stack'][0]['id'] == 'wiki.block.quadrants.v1'
    documents = {row['path']: row['text'] for row in package['documents']}
    assert 'Preserve synthetic independent review.' in documents['AGENTS.md']
    assert 'Review before promotion.' in documents['memories/policy.md']
    assert 'Inspect exceptions in the original evidence.' in documents['memories/perspective.md']
    assert package['policy_enforced'] is False
    perspective.write_text(perspective.read_text().replace('Inspect exceptions in the original evidence.', 'Inspect revised exceptions and conflicting evidence.'))
    second = run(str(src), 'system', tmp_path, config)
    after = json.loads((tmp_path / second.request_path).read_text())
    assert before['perspectives_required'] == after['perspectives_required']
    assert before['source_id'] == after['source_id']
    assert before['chunks'][0]['cache_key'] != after['chunks'][0]['cache_key']


def test_approved_pipeline_reads_current_policy_and_committed_perspective_before_cache_binding(tmp_path):
    import subprocess
    import yaml
    import pytest
    from jsonschema import validate
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.ingest.protected import prepare
    from wiki_core.context_packet import validate_result as validate_task_result
    from tests.test_protected_ingestion import AQAL_REFS
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True, text=True).stdout.strip()
    _write(tmp_path / '.gitignore', 'data/derived/\n')
    _write(tmp_path / 'AGENTS.md', 'Approved instruction body.\n')
    _write(tmp_path / 'index.md', '# Selected index\n')
    _write(tmp_path / 'memories/root.md', '---\npage_id: root\npage_type: root_entity\n---\n# Root\n')
    _write(tmp_path / 'memories/policy.md', 'Approved mandatory policy body.\n')
    perspective = tmp_path / 'memories/perspective.md'
    _write(perspective, '---\npage_id: perspective-synthetic\npage_type: perspective\n---\n# Perspective\nOriginal required interpretation.\n')
    for name, ref in AQAL_REFS.items():
        _write(tmp_path / ref, f'---\npage_id: {name}\npage_type: perspective\n---\n# Lens\n')
    config = {'repo_id': 'synthetic', 'context_access': {'.': {'owner': 'operator',
        'policy': {'read': ['self'], 'write': ['self'], 'capabilities': [], 'publication': [], 'deny': {}}}},
        'root_entity': {'page': 'memories/root.md', 'perspective_bundle': {'required': ['perspective-synthetic'], 'optional': []}}}
    _write(tmp_path / 'wiki.config.yaml', yaml.safe_dump(config))
    _write(tmp_path / 'source.md', '# Source\n' + LOREM)
    git('init', '-q'); git('config', 'user.name', 'Synthetic'); git('config', 'user.email', 'synthetic@example.test')
    git('add', '.'); git('commit', '-qm', 'Approved synthetic fixture')
    approved = git('rev-parse', 'HEAD'); git('update-ref', 'refs/remotes/origin/main', approved)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=approved, entry_folder='.', entry_index='index.md',
        source_ref='source.md', source_context='system',
        context_selection={'root_entity': 'memories/root.md', 'templates': ['memories/policy.md']},
        perspective_refs={**AQAL_REFS, 'perspective-synthetic': 'memories/perspective.md'})
    before = prepare(tmp_path, binding, **args)['request']; package = before['block_context_package']
    schema = json.loads((ROOT / 'docs/references/schemas/wiki-task-context-v1.schema.json').read_text())
    validate(package, schema)
    bound_result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
        'task_id': package['task_id'], 'context_id': package['context_id'], 'packet_digest': package['packet_digest'],
        'blockers': [], 'changes': [], 'read_coverage': {'observed_refs': package['declared_read_set'],
            'missing': package['coverage']['missing']}}
    assert validate_task_result(bound_result, package) is True
    inputs = {row['ref']: row['text'] for row in package['inputs']}
    assert inputs['AGENTS.md'] == 'Approved instruction body.\n'
    assert inputs['memories/policy.md'] == 'Approved mandatory policy body.\n'
    assert 'Original required interpretation.' in inputs['memories/perspective.md']
    perspective.write_text(perspective.read_text().replace('Original required interpretation.', 'Revised required interpretation.'))
    (tmp_path / 'memories/policy.md').write_text('Unapproved policy proposal.\n')
    same = prepare(tmp_path, binding, **args)['request']
    assert same['chunks'][0]['cache_key'] == before['chunks'][0]['cache_key']
    git('add', 'memories/perspective.md'); git('commit', '-qm', 'Approve selected perspective')
    current = git('rev-parse', 'HEAD'); git('update-ref', 'refs/remotes/origin/main', current)
    after = prepare(tmp_path, binding, **{**args, 'approved_revision': current})['request']
    inputs = {row['ref']: row['text'] for row in after['block_context_package']['inputs']}
    assert inputs['memories/policy.md'] == 'Approved mandatory policy body.\n'
    assert 'Revised required interpretation.' in inputs['memories/perspective.md']
    assert before['chunks'][0]['cache_key'] != after['chunks'][0]['cache_key']
    assert after['block_context_package']['policy_revision'] == after['block_context_package']['content_revision'] == current
    config['context_access']['.']['policy']['deny'] = {'read': ['memories/perspective.md']}
    (tmp_path / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git('add', 'wiki.config.yaml'); git('commit', '-qm', 'Revoke perspective read')
    revoked = git('rev-parse', 'HEAD'); git('update-ref', 'refs/remotes/origin/main', revoked)
    for revision in (current, revoked):
        with pytest.raises(ValueError): prepare(tmp_path, binding, **{**args, 'approved_revision': revision})


def test_legacy_local_source_change_before_persistence_blocks_all_outputs(tmp_path, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline

    source = tmp_path / 'synthetic.md'
    source.write_text('# Synthetic\n' + ('original synthetic content ' * 80))
    original = pipeline.build_context_request

    def change_during_preparation(*args, **kwargs):
        request = original(*args, **kwargs)
        source.write_text('# Synthetic\nchanged before persistence')
        return request

    monkeypatch.setattr(pipeline, 'build_context_request', change_during_preparation)
    result = pipeline.run(str(source), 'system', tmp_path, WikiConfig(), record_score=False)
    assert result.blocked and not result.written
    assert result.context_error_code == 'source_changed_before_persistence'
    assert result.request_path is None and result.manifest_path is None
    assert not (tmp_path / 'data/derived/wiki').exists()


def test_legacy_source_removed_during_preparation_preserves_prior_capture(tmp_path, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline

    source = tmp_path / 'synthetic.md'
    source.write_text('# Synthetic\n' + ('original synthetic content ' * 80))
    config = WikiConfig()
    first = pipeline.run(str(source), 'system', tmp_path, config, record_score=False)
    assert first.written and not first.blocked
    derived = tmp_path / 'data/derived/wiki'
    prior = {p.relative_to(derived): p.read_bytes() for p in derived.rglob('*') if p.is_file()}
    original = pipeline.build_context_request

    def remove_during_preparation(*args, **kwargs):
        request = original(*args, **kwargs)
        source.unlink()
        return request

    monkeypatch.setattr(pipeline, 'build_context_request', remove_during_preparation)
    result = pipeline.run(str(source), 'system', tmp_path, config, record_score=False)
    assert result.blocked and not result.written
    assert result.context_error_code == 'source_changed_before_persistence'
    assert {p.relative_to(derived): p.read_bytes() for p in derived.rglob('*') if p.is_file()} == prior


def test_legacy_source_replaced_by_fifo_does_not_block(tmp_path, monkeypatch):
    import os
    import pytest
    import wiki_core.ingest.pipeline as pipeline

    if not hasattr(os, 'mkfifo') or not hasattr(os, 'O_NONBLOCK'):
        pytest.skip('FIFO or nonblocking open unavailable')
    source = tmp_path / 'synthetic.md'
    source.write_text('# Synthetic\n' + ('original synthetic content ' * 80))
    original = pipeline.build_context_request

    def replace_during_preparation(*args, **kwargs):
        request = original(*args, **kwargs)
        source.unlink()
        os.mkfifo(source)
        return request

    monkeypatch.setattr(pipeline, 'build_context_request', replace_during_preparation)
    result = pipeline.run(str(source), 'system', tmp_path, WikiConfig(), record_score=False)
    assert result.blocked and not result.written
    assert result.context_error_code == 'source_changed_before_persistence'
    assert result.request_path is None and result.manifest_path is None
    assert not (tmp_path / 'data/derived/wiki').exists()


def test_legacy_ingestion_without_nonblocking_open_warns_and_remains_available(tmp_path, monkeypatch):
    import os
    import wiki_core.ingest.pipeline as pipeline

    source = tmp_path / 'synthetic.md'
    source.write_text('# Synthetic\n' + ('original synthetic content ' * 80))
    monkeypatch.delattr(os, 'O_NONBLOCK', raising=False)
    result = pipeline.run(str(source), 'system', tmp_path, WikiConfig(), record_score=False)
    assert not result.blocked and result.written
    assert result.request_path and (tmp_path / result.request_path).is_file()
    assert 'Local source recheck unavailable: nonblocking open is not supported.' in result.warnings
