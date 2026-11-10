"""Synthetic opening/return handoffs, not evidence of a running T3 host."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError, prepare_packet
from wiki_core.context_packet import validate_result
from wiki_core.context_policy import PolicyError


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def case(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    (tmp_path / 'AGENTS.md').write_text('# Synthetic root rules\n')
    (tmp_path / 'index.md').write_text('# Synthetic root index\n')
    source = Path(__file__).resolve().parents[1] / '.skills/wiki-viva/reference/coordinator.md'
    target = tmp_path / '.skills/wiki-viva/reference/coordinator.md'
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
    config = {'context_access': {'.': {'owner': 'Synthetic', 'policy': {
        'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}}}
    (tmp_path / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'synthetic approved authority')
    base = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'update-ref', 'refs/remotes/origin/main', base)
    return tmp_path, base, target


def payload(base: str, goal: str):
    return {'context_id': '.', 'approved_revision': base, 'content_revision': base,
            'entry_folder': '.', 'entry_index': 'index.md',
            'task': {'task_id': 'synthetic-action', 'goal': goal, 'output': 'result',
                     'integrator': 'synthetic-integrator', 'max_bytes': 100_000,
                     'role': 'coordinator', 'evidence': []}}


def test_open_and_resume_packet_include_approved_coordinator_contract(case):
    root, base, target = case
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    for goal in ('Open coordination', 'Old queued request: resume paused work'):
        packet = prepare_packet(root, binding, payload(base, goal))['packet']
        role = [entry for entry in packet['inputs'] if entry['ref'] == '.skills/wiki-viva/reference/coordinator.md']
        assert len(role) == 1 and role[0]['revision'] == base
        assert role[0]['text'] == target.read_text(encoding='utf-8')
        assert 'old queued message is not a resume authorization' in role[0]['text']
        assert 'Do not turn the coordinator into a product implementation' in role[0]['text']
        assert packet['enforcement_claim'].startswith('none')
        result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
                  'task_id': 'synthetic-action', 'context_id': '.',
                  'packet_digest': packet['packet_digest'], 'changes': [],
                  'read_coverage': {'observed_refs': packet['declared_read_set'],
                                    'missing': packet['coverage']['missing']}, 'blockers': []}
        assert validate_result(result, packet)
        result['read_coverage']['observed_refs'] = [row for row in packet['declared_read_set']
                                                   if row['ref'] != role[0]['ref']]
        with pytest.raises(PolicyError, match='every delivered input'):
            validate_result(result, packet)


def test_role_body_obeys_denies_and_cannot_use_an_old_revision(case, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, base, _ = case
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['self/.skills']}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'synthetic deny')
    current = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', current)
    original = RepositoryReader.read
    def guarded(reader, ref, *args, **kwargs):
        if ref == '.skills/wiki-viva/reference/coordinator.md':
            pytest.fail('denied role body was opened')
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(ProtectedCoordinationError) as error:
        prepare_packet(root, binding, payload(current, 'Open coordination'))
    assert '.skills' not in str(error.value)
    old = payload(current, 'Resume coordination')
    old['content_revision'] = base
    with pytest.raises(ProtectedCoordinationError) as error:
        prepare_packet(root, binding, old)
    assert error.value.code == 'coordination_content_not_approved'
